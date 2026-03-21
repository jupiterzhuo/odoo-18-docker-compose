# Copyright 2025
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl.html).

import logging
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from ..utils import timezone as tz_utils

_logger = logging.getLogger(__name__)


class StudioClassSession(models.Model):
    _name = "studio.class_session"
    _description = "Studio Class Session"
    _order = "session_start desc"

    _sql_constraints = [
        (
            "studio_class_session_template_start_uniq",
            "unique(session_template_id, session_start)",
            "Only one generated class session is allowed per session template and start time.",
        ),
    ]  # ✅ Idempotency guard for cron-generated sessions

    @api.model
    def _default_tenant_id(self):
        user = self.env.user
        if user.studio_tenant_ids:
            return user.studio_tenant_ids[:1].id
        if user.is_studio_manager():
            return self.env["studio.tenant"].search([], limit=1).id
        return False

    tenant_id = fields.Many2one(
        "studio.tenant",
        required=True,
        ondelete="restrict",
        index=True,
        default=_default_tenant_id,
    )
    branch_id = fields.Many2one("studio.branch", required=True, ondelete="restrict", index=True)
    room_id = fields.Many2one("studio.room", required=True, ondelete="restrict", index=True)
    instructor_id = fields.Many2one(
        "studio.instructor", required=True, ondelete="restrict", index=True
    )
    template_id = fields.Many2one(
        "studio.class_template",
        ondelete="set null",
        index=True,
    )  # 🔁 Existing class/program reference
    session_template_id = fields.Many2one(
        "studio.session_template",
        ondelete="set null",
        index=True,
        copy=False,
    )  # ✅ Traceability to recurring source layer
    # ❌ Removed mandatory manual session name input
    name = fields.Char(required=False, index=True)  # 🔁 Backend display label only
    session_start = fields.Datetime(required=True, index=True)
    session_end = fields.Datetime(required=True, index=True)
    state = fields.Selection(
        [
            ("scheduled", "Scheduled"),
            ("cancelled", "Cancelled"),
            ("completed", "Completed"),
        ],
        required=True,
        default="scheduled",
        index=True,
    )
    generated_by_cron = fields.Boolean(default=False, copy=False, index=True)
    cancel_reason = fields.Char(copy=False)
    capacity = fields.Integer(required=True, default=20, help="Default from room; can override.")
    booked_count = fields.Integer(compute="_compute_booking_counts", store=True, readonly=True)
    waitlist_count = fields.Integer(compute="_compute_booking_counts", store=True, readonly=True)
    checkin_close_at = fields.Datetime(
        help="After this time, pending attendance becomes no_show."
    )
    checkin_close_minutes_before = fields.Integer(
        compute="_compute_checkin_close_minutes_before",
        store=True,
        readonly=True,
        help="Minutes before session start when booking closes. 0 = allow until session end.",
    )
    booking_ids = fields.One2many("studio.booking", "session_id", string="Bookings", copy=False)
    # For calendar pop-up: who is booking / who is waitlist (excluding cancelled)
    booked_display = fields.Char(
        compute="_compute_booked_waitlist_display",
        string="Who is Booking",
        help="Summary of booked members for calendar view.",
    )
    waitlist_display = fields.Char(
        compute="_compute_booked_waitlist_display",
        string="Who is Waitlist",
        help="Summary of waitlist members for calendar view.",
    )

    @api.depends("checkin_close_at", "session_start", "session_template_id", "session_template_id.checkin_close_minutes_before")
    def _compute_checkin_close_minutes_before(self):
        for rec in self:
            if rec.session_template_id and rec.session_template_id.checkin_close_minutes_before:
                rec.checkin_close_minutes_before = rec.session_template_id.checkin_close_minutes_before
            elif rec.checkin_close_at and rec.session_start:
                delta = rec.session_start - rec.checkin_close_at
                rec.checkin_close_minutes_before = int(delta.total_seconds() / 60)
            else:
                rec.checkin_close_minutes_before = 0

    @api.depends("booking_ids", "booking_ids.booking_status", "booking_ids.member_profile_id", "booking_ids.waitlist_sequence")
    def _compute_booked_waitlist_display(self):
        for rec in self:
            active = rec.booking_ids.filtered(
                lambda b: b.booking_status not in ("cancelled", "late_cancel")
            )
            booked = active.filtered(
                lambda b: b.booking_status in ("booked", "promoted", "completed")
            )
            waitlist = active.filtered(lambda b: b.booking_status == "waitlisted").sorted(
                "waitlist_sequence"
            )
            names_booked = [n or "" for n in booked.mapped("member_profile_id.name")]
            rec.booked_display = ", ".join(filter(None, names_booked)) or _("—")
            parts = [
                "%s (%s)" % (b.member_profile_id.name or _("—"), b.waitlist_sequence)
                for b in waitlist
            ]
            rec.waitlist_display = ", ".join(parts) or _("—")

    @api.depends("booking_ids", "booking_ids.booking_status")
    def _compute_booking_counts(self):
        for rec in self:
            rec.booked_count = len(
                rec.booking_ids.filtered(
                    lambda b: b.booking_status in ("booked", "promoted", "completed")
                )
            )
            rec.waitlist_count = len(
                rec.booking_ids.filtered(lambda b: b.booking_status == "waitlisted")
            )

    # ✅ Conflict domain helper required by business spec
    def _get_conflicting_sessions_domain(self):
        self.ensure_one()
        return [
            ("id", "!=", self.id),
            ("tenant_id", "=", self.tenant_id.id),
            ("state", "!=", "cancelled"),
            ("session_start", "<", self.session_end),
            ("session_end", ">", self.session_start),
        ]

    # ✅ Conflict helper required by business spec
    def _check_room_conflict(self):
        for rec in self:
            if (
                rec.state == "cancelled"
                or not rec.room_id
                or not rec.session_start
                or not rec.session_end
            ):
                continue
            conflict = self.search(
                rec._get_conflicting_sessions_domain() + [("room_id", "=", rec.room_id.id)],
                limit=1,
            )
            if conflict:
                raise ValidationError(
                    _(
                        "Room conflict: room %(room)s overlaps with session %(session)s."
                    )
                    % {
                        "room": rec.room_id.display_name,
                        "session": conflict.display_name,
                    }
                )

    # ✅ Conflict helper required by business spec
    def _check_instructor_conflict(self):
        for rec in self:
            if (
                rec.state == "cancelled"
                or not rec.instructor_id
                or not rec.session_start
                or not rec.session_end
            ):
                continue
            conflict = self.search(
                rec._get_conflicting_sessions_domain()
                + [("instructor_id", "=", rec.instructor_id.id)],
                limit=1,
            )
            if conflict:
                raise ValidationError(
                    _(
                        "Instructor conflict: instructor %(instructor)s overlaps with session %(session)s."
                    )
                    % {
                        "instructor": rec.instructor_id.display_name,
                        "session": conflict.display_name,
                    }
                )

    # ✅ Conflict helper required by business spec
    def _check_session_conflicts(self):
        for rec in self:
            if rec.state == "cancelled":
                continue
            if (
                not rec.session_start
                or not rec.session_end
                or rec.session_end <= rec.session_start
            ):
                raise ValidationError(_("Session end must be after session start."))
            rec._check_room_conflict()
            rec._check_instructor_conflict()

    @api.constrains("branch_id", "tenant_id")
    def _check_branch_tenant(self):
        for rec in self:
            if rec.branch_id and rec.tenant_id and rec.branch_id.tenant_id != rec.tenant_id:
                raise ValidationError(_("Branch must belong to the session's tenant."))

    @api.constrains("room_id", "branch_id")
    def _check_room_branch(self):
        for rec in self:
            if rec.room_id and rec.branch_id and rec.room_id.branch_id != rec.branch_id:
                raise ValidationError(_("Room must belong to the session's branch."))

    @api.constrains("instructor_id", "tenant_id")
    def _check_instructor_tenant(self):
        for rec in self:
            if rec.instructor_id and rec.tenant_id and rec.instructor_id.tenant_id != rec.tenant_id:
                raise ValidationError(_("Instructor must belong to the session's tenant."))

    @api.constrains("template_id", "tenant_id")
    def _check_class_template_tenant(self):
        for rec in self:
            if rec.template_id and rec.tenant_id and rec.template_id.tenant_id != rec.tenant_id:
                raise ValidationError(_("Class template must belong to the session's tenant."))

    @api.constrains("session_template_id", "tenant_id")
    def _check_session_template_tenant(self):
        for rec in self:
            if (
                rec.session_template_id
                and rec.tenant_id
                and rec.session_template_id.tenant_id != rec.tenant_id
            ):
                raise ValidationError(_("Session template must belong to the session's tenant."))

    @api.constrains("room_id", "instructor_id", "session_start", "session_end", "state")
    def _constrains_session_conflicts(self):
        self._check_session_conflicts()

    @api.onchange("room_id")
    def _onchange_room_id(self):
        if self.room_id:
            self.capacity = self.room_id.capacity

    @api.onchange("template_id", "session_start")
    def _onchange_template_session_start(self):
        if self.template_id and self.session_start:
            self.session_end = self.session_start + timedelta(minutes=self.template_id.duration_minutes)

    def _get_auto_session_name(self):
        """Build session name using studio's local timezone (Bangkok), not UTC."""
        self.ensure_one()
        class_name = self.template_id.name or _("Class")
        when = self._session_start_to_studio_local_string(self.session_start)
        return _("%(clazz)s - %(when)s") % {"clazz": class_name, "when": when}

    def _session_start_to_studio_local_string(self, dt):
        """Convert session_start (stored UTC) to studio's local time (GMT+7) for display."""
        if not dt:
            return _("TBD")
        return tz_utils.utc_to_studio_local_str(dt)

    def _ensure_session_name(self):
        for rec in self:
            if rec.session_start:
                new_name = rec._get_auto_session_name()
                if rec.name != new_name:
                    rec.with_context(skip_ensure_session_name=True).write(
                        {"name": new_name}
                    )

    @api.model
    def _fix_all_session_names_gmt7(self):
        """Migration: fix all session names to use GMT+7 (run on module update)."""
        sessions = self.search([("session_start", "!=", False)])
        sessions._ensure_session_name()
        _logger.info("Studio: fixed %s session names to GMT+7", len(sessions))

    @api.model
    def _cron_finalize_completed_sessions(self):
        now = fields.Datetime.now()
        sessions = self.search(
            [
                ("session_end", "<", now),
                ("state", "not in", ["cancelled", "completed"]),
            ]
        )
        for session in sessions:
            for booking in session.booking_ids.filtered(
                lambda b: b.booking_status in ("booked", "promoted")
            ):
                if booking.attendance_status == "pending":
                    booking.write({"attendance_status": "no_show"})
                booking.write({"booking_status": "completed"})
            session.write({"state": "completed"})
        if sessions:
            _logger.info("Studio session: finalized %s past sessions", len(sessions))

    @api.model
    def _run_recurring_session_generation(self):
        # ✅ Backward-compatible bridge for existing cron server action code
        return self.env["studio.session_template"]._cron_generate_upcoming_sessions(
            horizon_days=7
        )

    @api.model
    def _get_eligible_members_for_session(self, session, at_dt=None):
        """Return member_profile_ids eligible to book this session at given datetime."""
        at_dt = at_dt or session.session_start
        at_date = at_dt.date() if hasattr(at_dt, "date") else at_dt
        # Members with active subscription valid at at_date, for this tenant
        subs = self.env["studio.membership_subscription"].search(
            [
                ("tenant_id", "=", session.tenant_id.id),
                ("state", "=", "active"),
                ("date_start", "<=", at_date),
                "|",
                ("date_end", "=", False),
                ("date_end", ">=", at_date),
            ]
        )
        member_ids = subs.member_profile_id.ids
        # Filter by allowed branches in plan.
        # Empty plan.branch_ids means all branches are allowed.
        allowed = []
        for mid in member_ids:
            profile = self.env["studio.member_profile"].browse(mid)
            sub = profile.active_subscription_id
            if not sub or not sub.plan_id:
                continue
            plan = sub.plan_id
            if not plan.branch_ids:
                allowed.append(mid)
            elif session.branch_id in plan.branch_ids:
                allowed.append(mid)
        return self.env["studio.member_profile"].browse(allowed)

    def _has_capacity(self):
        self.ensure_one()
        return self.booked_count < self.capacity

    def _serialize_for_api(self, member_profile_id=None):
        """Return session dict for list view (Classes screen). Times in GMT+7."""
        self.ensure_one()
        start_str = tz_utils.utc_to_studio_local_str(
            self.session_start, "%H:%M"
        ) if self.session_start else ""
        end_str = tz_utils.utc_to_studio_local_str(
            self.session_end, "%H:%M"
        ) if self.session_end else ""
        has_cap = self._has_capacity()
        status = "available" if has_cap else "full"
        is_user_booked = False
        is_bookable = False
        can_join_waitlist = False
        my_booking_id = None
        my_booking_status = None
        my_waitlist_position = None
        waitlist_total = None
        if member_profile_id:
            Booking = self.env["studio.booking"]
            my_booking = Booking.search(
                [
                    ("session_id", "=", self.id),
                    ("member_profile_id", "=", member_profile_id),
                    ("booking_status", "in", ("booked", "promoted", "waitlisted")),
                ],
                limit=1,
            )
            is_user_booked = bool(my_booking)
            if my_booking:
                my_booking_id = my_booking.id
                my_booking_status = my_booking.booking_status
                if my_booking.booking_status == "waitlisted":
                    waitlist = Booking.search(
                        [
                            ("session_id", "=", self.id),
                            ("booking_status", "=", "waitlisted"),
                        ],
                        order="waitlist_sequence asc",
                    )
                    waitlist_total = len(waitlist)
                    for idx, b in enumerate(waitlist, start=1):
                        if b.id == my_booking.id:
                            my_waitlist_position = idx
                            break
            if not is_user_booked and self.state == "scheduled":
                eligible = self.env["studio.booking"]._is_member_eligible_for_session(
                    member_profile_id, self.id
                )
                # Eligible members can book a seat OR join waitlist when full
                is_bookable = eligible
                can_join_waitlist = eligible and not has_cap
        return {
            "id": self.id,
            "start_time": start_str,
            "end_time": end_str,
            "timezone": "GMT+7",
            "class_name": self.template_id.name or _("Class"),
            "studio_name": self.room_id.name or "",
            "instructor_name": self.instructor_id.name or "",
            "attendance": self.booked_count,
            "capacity": self.capacity,
            "status": status,
            "is_user_booked": is_user_booked,
            "is_bookable": is_bookable,
            "can_join_waitlist": can_join_waitlist,
            "my_booking_id": my_booking_id,
            "my_booking_status": my_booking_status,
            "my_waitlist_position": my_waitlist_position,
            "waitlist_total": waitlist_total,
            "date": tz_utils.utc_to_studio_local_str(
                self.session_start, "%Y-%m-%d"
            ) if self.session_start else "",
            "branch_id": self.branch_id.id,
            "branch_name": self.branch_id.name or "",
        }

    def _serialize_detail_for_api(self, member_profile_id=None):
        """Return full session dict for detail view."""
        self.ensure_one()
        list_data = self._serialize_for_api(member_profile_id=member_profile_id)
        description = getattr(self.template_id, "description", None) or ""
        list_data["description"] = description
        return list_data

    @api.model_create_multi
    def create(self, vals_list):
        Tenant = self.env["studio.tenant"]
        for vals in vals_list:
            tenant = Tenant.browse(vals.get("tenant_id"))
            self.env.user.ensure_studio_tenant_allowed(tenant)
        records = super().create(vals_list)
        records._ensure_session_name()  # 🔁 Auto-fill display label in backend
        records._check_session_conflicts()  # 🔁 Explicit conflict checks on create
        return records

    def write(self, vals):
        Tenant = self.env["studio.tenant"]
        if vals.get("tenant_id"):
            tenant = Tenant.browse(vals.get("tenant_id"))
            self.env.user.ensure_studio_tenant_allowed(tenant)
        for rec in self:
            self.env.user.ensure_studio_tenant_allowed(rec.tenant_id)
        res = super().write(vals)
        if not self.env.context.get("skip_ensure_session_name"):
            self._ensure_session_name()  # 🔁 Keep auto-fill behavior on updates
        self._check_session_conflicts()  # 🔁 Explicit conflict checks on write
        return res

    def _try_promote_from_waitlist(self, source=None):
        """
        Promote first eligible waitlist member (FIFO).
        Skips ineligible members and continues to next.
        Returns promoted booking or empty recordset.
        """
        self.ensure_one()
        if source is None:
            source = self.env.context.get("promotion_source", "admin_backend")
        if self.booked_count >= self.capacity:
            return self.env["studio.booking"].browse()
        waitlist = self.booking_ids.filtered(
            lambda b: b.booking_status == "waitlisted"
        ).sorted("waitlist_sequence")
        for booking in waitlist:
            can, _msg = booking._can_book()
            if can:
                booking.write({
                    "booking_status": "promoted",
                    "waitlist_sequence": 0,
                    "promoted_at": fields.Datetime.now(),
                    "promotion_source": source,
                })
                _logger.info(
                    "Studio session: promoted waitlist booking %s for session %s",
                    booking.id,
                    self.id,
                )
                try:
                    from ..utils.push_helper import send_promotion_push

                    send_promotion_push(
                        self.env,
                        booking.member_profile_id.id,
                        self,
                        class_name=self.template_id.name if self.template_id else None,
                    )
                except Exception as e:
                    _logger.warning(
                        "Push notification failed for promoted member %s: %s",
                        booking.member_profile_id.id,
                        e,
                    )
                # Send promotion email (alternative to push; always attempted)
                try:
                    self._send_promotion_email(booking)
                except Exception as e:
                    _logger.warning(
                        "Promotion email failed for member %s: %s",
                        booking.member_profile_id.id,
                        e,
                    )
                return booking
        return self.env["studio.booking"].browse()

    def _send_promotion_email(self, booking):
        """
        Send promotion email to the member when promoted from waitlist.
        Uses mail.template mail_template_waitlist_promotion.
        """
        self.ensure_one()
        booking.ensure_one()
        member = booking.member_profile_id
        if not member or not member.email:
            _logger.debug(
                "Skipping promotion email: member %s has no email",
                member.id if member else "?",
            )
            return
        template = self.env.ref(
            "studio_booking.mail_template_waitlist_promotion",
            raise_if_not_found=False,
        )
        if not template:
            _logger.warning("Promotion email template not found. Skipping.")
            return
        email_from = (
            self.tenant_id.email
            or (self.env.company.email if self.env.company else None)
            or False
        )
        mail_id = template.sudo().send_mail(
            booking.id,
            force_send=False,
            raise_exception=False,
            email_values={
                "email_to": member.email,
                "email_from": email_from,
            },
        )
        if mail_id:
            mail = self.env["mail.mail"].sudo().browse(mail_id)
            if mail.exists():
                mail.send(raise_exception=False)
                _logger.info(
                    "Sent promotion email to member %s for session %s",
                    member.id,
                    self.id,
                )

    def _resequence_waitlist(self):
        """
        Renumber remaining waitlisted bookings for this session to 1, 2, 3, ...
        (queue with no gaps after a cancel).
        """
        self.ensure_one()
        waitlist = self.booking_ids.filtered(
            lambda b: b.booking_status == "waitlisted"
        ).sorted("waitlist_sequence")
        for seq, booking in enumerate(waitlist, start=1):
            if booking.waitlist_sequence != seq:
                booking.waitlist_sequence = seq

    def action_book(self, member_profile_id):
        """Service: book a seat for member. Returns created booking."""
        self.ensure_one()
        if self.state == "cancelled":
            raise UserError(_("Cannot book a cancelled session."))
        Booking = self.env["studio.booking"]
        dummy = Booking.new(
            {"session_id": self.id, "member_profile_id": member_profile_id}
        )
        can, msg = dummy._can_book(member_profile_id)
        if not can:
            raise UserError(msg or _("Cannot book."))
        return Booking.create(
            {
                "session_id": self.id,
                "member_profile_id": member_profile_id,
                "booking_status": "booked",
                "attendance_status": "pending",
            }
        )

    def action_join_waitlist(self, member_profile_id):
        """Service: add member to waitlist (FIFO). Returns created booking."""
        self.ensure_one()
        if self.state == "cancelled":
            raise UserError(_("Cannot join waitlist for a cancelled session."))
        Booking = self.env["studio.booking"]
        dummy = Booking.new(
            {"session_id": self.id, "member_profile_id": member_profile_id}
        )
        can, msg = dummy._can_join_waitlist(member_profile_id)
        if not can:
            raise UserError(msg or _("Cannot join waitlist."))
        last = Booking.search(
            [
                ("session_id", "=", self.id),
                ("booking_status", "=", "waitlisted"),
            ],
            order="waitlist_sequence desc",
            limit=1,
        )
        next_seq = (last.waitlist_sequence + 1) if last else 1
        return Booking.create(
            {
                "session_id": self.id,
                "member_profile_id": member_profile_id,
                "booking_status": "waitlisted",
                "waitlist_sequence": next_seq,
                "attendance_status": "pending",
            }
        )

    # ✅ Session cancellation flow for single dated occurrence
    def action_cancel_session(self):
        for rec in self:
            if rec.state == "cancelled":
                continue
            rec.booking_ids.write(
                {
                    "booking_status": "cancelled",
                    "waitlist_sequence": 0,
                    "attendance_status": "pending",
                    "checkin_source": False,
                    "checked_in_at": False,
                    "checked_in_by_user_id": False,
                }
            )
            rec.write({"state": "cancelled", "cancel_reason": rec.cancel_reason or _("Cancelled by staff")})
        return True

    def action_booking_detail(self):
        """Open pop-up with two tables: Who is Booking and Who is Waitlist (cancelled excluded)."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Booking detail: %s") % (self.name or self.session_start),
            "res_model": "studio.session_booking_detail",
            "view_mode": "form",
            "target": "new",
            "context": {"default_session_id": self.id},
        }
