# Copyright 2025
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl.html).

import logging
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError, UserError

_logger = logging.getLogger(__name__)

BOOKING_STATUSES = [
    ("booked", "Booked"),
    ("waitlisted", "Waitlisted"),
    ("promoted", "Promoted"),
    ("cancelled", "Cancelled"),
    ("late_cancel", "Late Cancel"),
    ("completed", "Completed"),
]

ATTENDANCE_STATUSES = [
    ("pending", "Pending"),
    ("attended", "Attended"),
    ("no_show", "No Show"),
]

# ✅ add booking source selection for audit
BOOKING_SOURCE_SELECTION = [
    ("admin_backend", "Admin Backend"),
    ("member_app", "Member App"),
    ("api", "API"),
]


class StudioBooking(models.Model):
    _name = "studio.booking"
    _description = "Studio Booking"
    _order = "session_id, waitlist_sequence, id"

    session_id = fields.Many2one(
        "studio.class_session",
        required=True,
        ondelete="restrict",
        index=True,
    )
    tenant_id = fields.Many2one(
        "studio.tenant",
        related="session_id.tenant_id",
        store=True,
        index=True,
    )
    member_profile_id = fields.Many2one(
        "studio.member_profile",
        required=True,
        ondelete="restrict",
        index=True,
    )
    booking_status = fields.Selection(
        BOOKING_STATUSES,
        required=True,
        default="booked",
        index=True,
    )
    attendance_status = fields.Selection(
        ATTENDANCE_STATUSES,
        default="pending",
        required=True,
        index=True,
    )
    waitlist_sequence = fields.Integer(
        default=0,
        help="FIFO order on waitlist; lower = earlier.",
    )
    checkin_source = fields.Selection(
        [
            ("staff", "Staff"),
            ("member_app", "Member App"),
        ],
        string="Check-in Source",
    )
    checked_in_at = fields.Datetime(readonly=True)
    checked_in_by_user_id = fields.Many2one(
        "res.users",
        string="Checked in by",
        readonly=True,
    )
    # ✅ add booking audit fields
    booked_by_user_id = fields.Many2one(
        "res.users",
        string="Booked by",
        readonly=True,
        index=True,
    )
    booked_at = fields.Datetime(
        string="Booked at",
        readonly=True,
        copy=False,
    )
    booking_source = fields.Selection(
        BOOKING_SOURCE_SELECTION,
        string="Booking Source",
        readonly=True,
        index=True,
    )
    # Cancel audit fields
    canceled_by_user_id = fields.Many2one(
        "res.users",
        string="Canceled by",
        readonly=True,
        index=True,
    )
    canceled_at = fields.Datetime(
        string="Canceled at",
        readonly=True,
        copy=False,
    )
    cancel_source = fields.Selection(
        BOOKING_SOURCE_SELECTION,
        string="Cancel Source",
        readonly=True,
        copy=False,
    )
    # Promotion audit fields (when promoted from waitlist)
    promoted_at = fields.Datetime(
        string="Promoted at",
        readonly=True,
        copy=False,
    )
    promotion_source = fields.Selection(
        BOOKING_SOURCE_SELECTION,
        string="Promotion Source",
        readonly=True,
        copy=False,
    )
    # ✅ Computed: members who already have a booking for this session (used in domain to hide from dropdown)
    existing_booking_member_ids = fields.Many2many(
        "studio.member_profile",
        compute="_compute_existing_booking_member_ids",
        string="Members already booked for this session",
        help="Used in domain so these members do not appear in the member selection.",
    )

    @api.depends("session_id", "session_id.booking_ids", "session_id.booking_ids.booking_status", "member_profile_id")
    def _compute_existing_booking_member_ids(self):
        for rec in self:
            if not rec.session_id:
                rec.existing_booking_member_ids = self.env["studio.member_profile"]
                continue
            bookings = rec.session_id.booking_ids.filtered(
                lambda b: b.booking_status in ("booked", "promoted", "waitlisted")
            )
            members = bookings.mapped("member_profile_id")
            # Exclude current booking's member so when editing, the selected member stays in list
            if rec.member_profile_id:
                members = members - rec.member_profile_id
            rec.existing_booking_member_ids = members

    def _get_session_display_date(self):
        """
        Return session start formatted in studio timezone (GMT+7) for display in emails.
        Used by mail template mail_template_waitlist_promotion.
        """
        self.ensure_one()
        if not self.session_id or not self.session_id.session_start:
            return ""
        from ..utils import timezone as tz_utils

        return tz_utils.utc_to_studio_local_str(
            self.session_id.session_start, "%A, %B %d, %Y at %H:%M"
        )

    # --- Helpers: eligibility and validation for backend save ---

    @api.model
    def _validate_checkin_close_for_booking(self, session, at_dt=None):
        """
        Validate booking against checkin_close_minutes_before.
        - If 0: allow until session_end (reject only if session ended).
        - If > 0: reject when now >= session_start - minutes_before.
        - Sessions on a future date (studio timezone): always allow.
        """
        from datetime import timedelta

        from ..utils import timezone as tz_utils

        session.ensure_one()
        now = at_dt or tz_utils.utc_now()
        if session.session_end and now >= session.session_end:
            raise ValidationError(_("Booking is closed. The class has already ended."))
        if not session.session_start:
            return
        session_date_local = tz_utils.utc_to_studio_local(session.session_start).date()
        today_local = tz_utils.studio_today()
        if session_date_local > today_local:
            return  # Session on future date, allow
        minutes_before = getattr(
            session, "checkin_close_minutes_before", 0
        ) or 0
        if minutes_before > 0:
            cutoff = session.session_start - timedelta(minutes=minutes_before)
            if now >= cutoff:
                raise ValidationError(
                    _(
                        "Booking is closed. Bookings must be made at least %(minutes)s minutes before the class starts."
                    )
                    % {"minutes": minutes_before}
                )

    @api.model
    def _validate_eligibility_for_save(self, member_profile_id, session_id, at_dt=None):
        """
        Validate full eligibility for manual/backend booking. Raises ValidationError if invalid.
        Rules: member exists, session exists, member tenant matches session tenant,
        member has exactly one active subscription, subscription active and not overdue/expired
        at session datetime, session branch in plan allowed branches (empty = all).
        """
        Session = self.env["studio.class_session"]
        Member = self.env["studio.member_profile"]
        session = Session.browse(session_id)
        member = Member.browse(member_profile_id)
        if not session.exists():
            raise ValidationError(_("Session is required and must exist."))
        self._validate_checkin_close_for_booking(session, at_dt=at_dt)
        if session.state == "cancelled":
            raise ValidationError(_("Cannot book a cancelled session."))
        if session.state == "completed":
            raise ValidationError(_("Cannot book a completed session."))
        if not member.exists():
            raise ValidationError(_("Member is required and must exist."))
        if member.tenant_id != session.tenant_id:
            raise ValidationError(
                _("Member tenant must match the session tenant.")
            )
        at_dt = at_dt or session.session_start
        at_date = at_dt.date() if hasattr(at_dt, "date") else at_dt
        sub = member.active_subscription_id
        if not sub:
            raise ValidationError(
                _("Member must have an active subscription to book.")
            )
        if sub.state != "active":
            raise ValidationError(
                _("Member subscription must be active (not draft, expired or cancelled).")
            )
        if sub.date_start and sub.date_start > at_date:
            raise ValidationError(
                _("Subscription is not yet active at the session date.")
            )
        if sub.date_end and sub.date_end < at_date:
            raise ValidationError(
                _("Subscription has expired before the session date.")
            )
        plan = sub.plan_id
        if plan.branch_ids and session.branch_id not in plan.branch_ids:
            raise ValidationError(
                _("Session branch is not allowed by the member's membership plan.")
            )

    @api.model
    def _member_has_active_booking_for_same_session(
        self, member_profile_id, session_id, exclude_booking_id=None
    ):
        """True if member already has an active booking or waitlist for the same session."""
        domain = [
            ("member_profile_id", "=", member_profile_id),
            ("session_id", "=", session_id),
            ("booking_status", "in", ["booked", "promoted", "waitlisted"]),
        ]
        if exclude_booking_id:
            domain.append(("id", "!=", exclude_booking_id))
        return self.search_count(domain) > 0

    @api.model
    def _resolve_booking_status_for_save(self, session):
        """
        Resolve booking_status for backend save: booked if seat available, else waitlisted.
        Reusable for create/write so status is never trusted from input.
        """
        session.ensure_one()
        if session.booked_count < session.capacity:
            return "booked"
        return "waitlisted"

    def _get_booking_audit_vals(self, source=None):
        """Return vals for booked_by_user_id, booked_at, and booking_source."""
        if source is None:
            source = self.env.context.get("booking_source", "admin_backend")
        return {
            "booked_by_user_id": self.env.user.id,
            "booked_at": fields.Datetime.now(),
            "booking_source": source,
        }

    def _prepare_booking_vals_for_save(self, vals, session):
        """
        Enforce business rules on vals: do not trust booking_status; set status and audit.
        Returns updated vals dict (copy) for create/write.
        """
        resolved_status = self._resolve_booking_status_for_save(session)
        audit = self._get_booking_audit_vals()
        out = dict(vals)
        out["booking_status"] = resolved_status
        out["booked_by_user_id"] = audit["booked_by_user_id"]
        out["booked_at"] = audit["booked_at"]
        out["booking_source"] = audit["booking_source"]
        return out

    def _validate_create_write_booking(self, vals, exclude_booking_id=None):
        """
        Run all validations for create/write: eligibility, duplicate same session, overlap.
        Uses member_profile_id and session_id from vals or self. Raises on failure.
        """
        session_id = vals.get("session_id") or (self.session_id.id if self else None)
        member_profile_id = vals.get("member_profile_id") or (
            self.member_profile_id.id if self else None
        )
        if not session_id or not member_profile_id:
            return
        session = self.env["studio.class_session"].browse(session_id)
        if not session.exists():
            return
        at_dt = session.session_start
        self._validate_eligibility_for_save(
            member_profile_id, session_id, at_dt=at_dt
        )
        if self._member_has_active_booking_for_same_session(
            member_profile_id, session_id, exclude_booking_id=exclude_booking_id
        ):
            raise ValidationError(
                _(
                    "This member already has a booking or is on the waitlist for this session. "
                    "A member cannot book the same session twice. Cancel the existing booking first to rebook."
                )
            )
        # Overlap: no other confirmed or waitlisted in same time window
        if self._member_has_booking_overlap(
            member_profile_id, session_id, exclude_booking_id=exclude_booking_id
        ):
            raise ValidationError(_("Member has another booking at the same time."))
        if self._member_has_waitlist_overlap(
            member_profile_id, session_id, exclude_booking_id=exclude_booking_id
        ):
            raise ValidationError(_("Member is on a waitlist at the same time."))

    @api.model_create_multi
    def create(self, vals_list):
        Session = self.env["studio.class_session"]
        created = self.browse()
        for vals in vals_list:
            session_id = vals.get("session_id")
            if not session_id:
                raise ValidationError(_("Session is required."))
            session = Session.browse(session_id)
            if not session.exists():
                raise ValidationError(_("Session does not exist."))
            self.env.user.ensure_studio_tenant_allowed(session.tenant_id)
            self._validate_create_write_booking(vals, exclude_booking_id=None)
            # 🔁 do not trust manual booking_status; set status and audit (update vals in place)
            prepared = self._prepare_booking_vals_for_save(vals, session)
            vals.update(prepared)
            # ✅ set waitlist_sequence when status is waitlisted
            if vals.get("booking_status") == "waitlisted":
                last = self.search(
                    [
                        ("session_id", "=", session.id),
                        ("booking_status", "=", "waitlisted"),
                    ],
                    order="waitlist_sequence desc",
                    limit=1,
                )
                vals["waitlist_sequence"] = (last.waitlist_sequence + 1) if last else 1
            else:
                vals.setdefault("waitlist_sequence", 0)
        return super().create(vals_list)

    def write(self, vals):
        Session = self.env["studio.class_session"]
        if vals.get("session_id"):
            session = Session.browse(vals.get("session_id"))
            if session.exists():
                self.env.user.ensure_studio_tenant_allowed(session.tenant_id)
        for rec in self:
            self.env.user.ensure_studio_tenant_allowed(rec.tenant_id)
        # 🔁 when changing session or member, re-validate and re-resolve status and audit
        changing_session = "session_id" in vals
        changing_member = "member_profile_id" in vals
        if changing_session or changing_member:
            for rec in self:
                session = (
                    Session.browse(vals["session_id"])
                    if changing_session and vals.get("session_id")
                    else rec.session_id
                )
                member_profile_id = (
                    vals.get("member_profile_id")
                    if changing_member
                    else rec.member_profile_id.id
                )
                if not session.exists() or not member_profile_id:
                    continue
                rec._validate_create_write_booking(
                    {"session_id": session.id, "member_profile_id": member_profile_id},
                    exclude_booking_id=rec.id,
                )
                new_vals = rec._prepare_booking_vals_for_save(
                    {**vals, "session_id": session.id, "member_profile_id": member_profile_id},
                    session,
                )
                vals.update({
                    "booking_status": new_vals["booking_status"],
                    "booked_by_user_id": new_vals["booked_by_user_id"],
                    "booked_at": new_vals.get("booked_at"),
                    "booking_source": new_vals["booking_source"],
                })
                if new_vals.get("booking_status") == "waitlisted":
                    last = self.search(
                        [
                            ("session_id", "=", session.id),
                            ("booking_status", "=", "waitlisted"),
                        ],
                        order="waitlist_sequence desc",
                        limit=1,
                    )
                    vals["waitlist_sequence"] = (
                        (last.waitlist_sequence + 1) if last else 1
                    )
                break
        else:
            # ✅ do not trust manual booking_status when user tries to set booked/waitlisted/promoted
            if "booking_status" in vals and vals.get("booking_status") in (
                "booked",
                "waitlisted",
                "promoted",
            ):
                for rec in self:
                    if not rec.session_id.exists():
                        continue
                    resolved = rec._resolve_booking_status_for_save(rec.session_id)
                    audit = rec._get_booking_audit_vals()
                    vals["booking_status"] = resolved
                    vals["booked_by_user_id"] = audit["booked_by_user_id"]
                    vals["booked_at"] = audit.get("booked_at")
                    vals["booking_source"] = audit["booking_source"]
                    break
        # ✅ When cancelling: set waitlist_sequence = 0, audit fields, and trigger promotion
        if vals.get("booking_status") == "cancelled":
            vals.setdefault("waitlist_sequence", 0)
            cancel_source = self.env.context.get("cancel_source", "admin_backend")
            vals.setdefault("canceled_by_user_id", self.env.user.id)
            vals.setdefault("canceled_at", fields.Datetime.now())
            vals.setdefault("cancel_source", cancel_source)
            to_promote_sessions = self.filtered(
                lambda r: r.booking_status in ("booked", "promoted")
            ).mapped("session_id")
        else:
            to_promote_sessions = self.env["studio.class_session"]
        res = super().write(vals)
        for session in to_promote_sessions:
            session._try_promote_from_waitlist()
        if vals.get("booking_status") == "cancelled":
            for session in self.mapped("session_id"):
                session._resequence_waitlist()
        return res

    # --- Service: eligibility at session datetime ---

    @api.model
    def _is_member_eligible_for_session(self, member_profile_id, session_id, at_dt=None):
        """Check if member is eligible to book this session at given datetime (membership + branch)."""
        session = self.env["studio.class_session"].browse(session_id)
        member = self.env["studio.member_profile"].browse(member_profile_id)
        if not session.exists() or not member.exists():
            return False
        if member.tenant_id != session.tenant_id:
            return False
        at_dt = at_dt or session.session_start
        at_date = at_dt.date() if hasattr(at_dt, "date") else at_dt
        sub = member.active_subscription_id
        if not sub or sub.state != "active":
            return False
        if sub.date_start and sub.date_start > at_date:
            return False
        if sub.date_end and sub.date_end < at_date:
            return False
        plan = sub.plan_id
        # Empty allowed branches means all branches are allowed.
        if not plan.branch_ids:
            return True
        if session.branch_id in plan.branch_ids:
            return True
        return False

    @api.model
    def _member_has_booking_overlap(self, member_profile_id, session_id, exclude_booking_id=None):
        """True if member has another confirmed booking overlapping this session."""
        session = self.env["studio.class_session"].browse(session_id)
        domain = [
            ("member_profile_id", "=", member_profile_id),
            ("session_id", "!=", session_id),
            ("booking_status", "in", ["booked", "promoted", "completed"]),
            ("session_id.session_start", "<", session.session_end),
            ("session_id.session_end", ">", session.session_start),
        ]
        if exclude_booking_id:
            domain.append(("id", "!=", exclude_booking_id))
        return self.search_count(domain) > 0

    @api.model
    def _member_has_waitlist_overlap(self, member_profile_id, session_id, exclude_booking_id=None):
        """True if member is on waitlist for another session overlapping this one."""
        session = self.env["studio.class_session"].browse(session_id)
        domain = [
            ("member_profile_id", "=", member_profile_id),
            ("session_id", "!=", session_id),
            ("booking_status", "=", "waitlisted"),
            ("session_id.session_start", "<", session.session_end),
            ("session_id.session_end", ">", session.session_start),
        ]
        if exclude_booking_id:
            domain.append(("id", "!=", exclude_booking_id))
        return self.search_count(domain) > 0

    @api.model
    def _member_has_confirmed_plus_waitlist_overlap(self, member_profile_id, session_id):
        """True if member has both a confirmed booking and a waitlist in overlapping time."""
        session = self.env["studio.class_session"].browse(session_id)
        confirmed = self.search_count(
            [
                ("member_profile_id", "=", member_profile_id),
                ("booking_status", "in", ["booked", "promoted", "completed"]),
                ("session_id.session_start", "<", session.session_end),
                ("session_id.session_end", ">", session.session_start),
            ]
        )
        waitlist = self.search_count(
            [
                ("member_profile_id", "=", member_profile_id),
                ("booking_status", "=", "waitlisted"),
                ("session_id.session_start", "<", session.session_end),
                ("session_id.session_end", ">", session.session_start),
            ]
        )
        return (confirmed > 0 and waitlist > 0) or self._member_has_booking_overlap(
            member_profile_id, session_id
        ) or self._member_has_waitlist_overlap(member_profile_id, session_id)

    def _can_book(self, member_profile_id=None):
        """Reusable: can this member book this session (capacity + eligibility + no overlaps)."""
        self.ensure_one()
        member_profile_id = member_profile_id or self.member_profile_id.id
        if not self._is_member_eligible_for_session(member_profile_id, self.session_id.id):
            return False, _("Member not eligible (membership or branch).")
        if self._member_has_booking_overlap(member_profile_id, self.session_id.id, self.id if self.id else None):
            return False, _("Member has another booking at the same time.")
        if self._member_has_waitlist_overlap(member_profile_id, self.session_id.id, self.id if self.id else None):
            return False, _("Member is on a waitlist at the same time.")
        if self.session_id.booked_count >= self.session_id.capacity:
            return False, _("Session is full.")
        return True, None

    def _can_join_waitlist(self, member_profile_id=None):
        """Reusable: can this member join waitlist (eligibility + no overlaps)."""
        self.ensure_one()
        member_profile_id = member_profile_id or self.member_profile_id.id
        if not self._is_member_eligible_for_session(member_profile_id, self.session_id.id):
            return False, _("Member not eligible (membership or branch).")
        if self._member_has_booking_overlap(member_profile_id, self.session_id.id, self.id if self.id else None):
            return False, _("Member has another booking at the same time.")
        if self._member_has_waitlist_overlap(member_profile_id, self.session_id.id, self.id if self.id else None):
            return False, _("Member is already on a waitlist at the same time.")
        if self.session_id.booked_count < self.session_id.capacity:
            return False, _("Session has capacity; book instead of waitlist.")
        return True, None

    # --- API-style service methods (for backend + future mobile API) ---

    def action_book(self, member_profile_id=None):
        """Book a seat for member. Use from existing booking record or via session.action_book()."""
        self.ensure_one()
        member_profile_id = member_profile_id or self.member_profile_id.id
        can, msg = self._can_book(member_profile_id)
        if not can:
            raise UserError(msg or _("Cannot book."))
        vals = {
            "session_id": self.session_id.id,
            "member_profile_id": member_profile_id,
            "booking_status": "booked",
            "attendance_status": "pending",
        }
        if self.id:
            self.write(vals)
            return self, _("Booked.")
        return self.create(vals), _("Booked.")

    def action_join_waitlist(self, member_profile_id=None):
        """Add member to waitlist (FIFO). Use from session.action_join_waitlist() or existing record."""
        self.ensure_one()
        member_profile_id = member_profile_id or self.member_profile_id.id
        can, msg = self._can_join_waitlist(member_profile_id)
        if not can:
            raise UserError(msg or _("Cannot join waitlist."))
        last = self.search(
            [("session_id", "=", self.session_id.id), ("booking_status", "=", "waitlisted")],
            order="waitlist_sequence desc",
            limit=1,
        )
        next_seq = (last.waitlist_sequence + 1) if last else 1
        vals = {
            "session_id": self.session_id.id,
            "member_profile_id": member_profile_id,
            "booking_status": "waitlisted",
            "waitlist_sequence": next_seq,
            "attendance_status": "pending",
        }
        if self.id:
            self.write(vals)
            return self, _("Added to waitlist.")
        return self.create(vals), _("Added to waitlist.")

    def action_cancel(self):
        """Cancel booking(s)/waitlist. Triggers promotion and resequences waitlist (1,2,3...)."""
        for rec in self:
            if rec.booking_status in ("cancelled", "late_cancel", "completed"):
                raise UserError(
                    _("Booking already in final state: %s") % rec.display_name
                )
            was_booked = rec.booking_status in ("booked", "promoted")
            rec.write({"booking_status": "cancelled", "waitlist_sequence": 0})
            if was_booked:
                rec.session_id._try_promote_from_waitlist()
            rec.session_id._resequence_waitlist()
        return True

    def action_check_in(self, source="staff", user_id=None):
        """Check in member. source: staff | member_app."""
        self.ensure_one()
        if self.attendance_status == "attended":
            return True
        if self.booking_status not in ("booked", "promoted"):
            raise UserError(_("Only confirmed bookings can be checked in."))
        user_id = user_id or self.env.user.id
        self.write(
            {
                "attendance_status": "attended",
                "checkin_source": source,
                "checked_in_at": fields.Datetime.now(),
                "checked_in_by_user_id": user_id,
            }
        )
        return True

    # --- Constraints ---

    @api.constrains("member_profile_id", "session_id", "booking_status")
    def _check_member_no_overlap(self):
        for rec in self:
            if rec.booking_status in ("cancelled", "late_cancel", "completed"):
                continue
            if self._member_has_booking_overlap(
                rec.member_profile_id.id, rec.session_id.id, exclude_booking_id=rec.id
            ):
                raise ValidationError(_("Member has another booking at the same time."))
            if self._member_has_waitlist_overlap(
                rec.member_profile_id.id, rec.session_id.id, exclude_booking_id=rec.id
            ) and rec.booking_status != "waitlisted":
                raise ValidationError(_("Member is on a waitlist at the same time."))

    @api.constrains("member_profile_id", "session_id", "booking_status")
    def _check_no_duplicate_same_session(self):
        """Block duplicate: one active booking or waitlist per member per session."""
        for rec in self:
            if rec.booking_status in ("cancelled", "late_cancel", "completed"):
                continue
            if self._member_has_active_booking_for_same_session(
                rec.member_profile_id.id,
                rec.session_id.id,
                exclude_booking_id=rec.id,
            ):
                raise ValidationError(
                    _(
                        "This member already has a booking or is on the waitlist for this session. "
                        "A member cannot book the same session twice."
                    )
                )

    @api.model
    def _cron_apply_no_show(self):
        """
        Set attendance to no_show when:
        - checkin_close_at has passed and still pending, or
        - session has ended (session_end < now) and still pending (covers no grace window).
        """
        now = fields.Datetime.now()
        # Case 1: checkin_close_at set and past
        domain_close = [
            ("attendance_status", "=", "pending"),
            ("booking_status", "in", ["booked", "promoted"]),
            ("session_id.checkin_close_at", "!=", False),
            ("session_id.checkin_close_at", "<", now),
        ]
        bookings = self.search(domain_close)
        if bookings:
            bookings.write({"attendance_status": "no_show"})
            _logger.info(
                "Studio booking: applied no_show (checkin_close) to %s bookings",
                len(bookings),
            )
        # ✅ Case 2: session ended, no check-in yet (e.g. no grace window)
        domain_ended = [
            ("attendance_status", "=", "pending"),
            ("booking_status", "in", ["booked", "promoted"]),
            ("session_id.session_end", "<", now),
        ]
        bookings_ended = self.search(domain_ended)
        if bookings_ended:
            bookings_ended.write({"attendance_status": "no_show"})
            _logger.info(
                "Studio booking: applied no_show (session ended) to %s bookings",
                len(bookings_ended),
            )

    @api.model
    def _fix_cancelled_waitlist_sequence(self):
        """
        One-time fix: set waitlist_sequence = 0 for all cancelled/late_cancel bookings
        where it is not already 0 (they are no longer waiting).
        """
        domain = [
            ("booking_status", "in", ["cancelled", "late_cancel"]),
            ("waitlist_sequence", "!=", 0),
        ]
        to_fix = self.search(domain)
        if to_fix:
            to_fix.write({"waitlist_sequence": 0})
            _logger.info(
                "Studio booking: fixed waitlist_sequence to 0 for %s cancelled booking(s)",
                len(to_fix),
            )
