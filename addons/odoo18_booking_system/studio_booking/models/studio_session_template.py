# Copyright 2025
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl.html).

import logging
from datetime import datetime, time, timedelta
from calendar import monthrange

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from ..utils import timezone as tz_utils

_logger = logging.getLogger(__name__)


class StudioSessionTemplate(models.Model):
    _name = "studio.session_template"
    _description = "Studio Session Template (Recurring Source)"
    _order = "tenant_id, branch_id, day_of_week, start_time"

    @api.model
    def _default_tenant_id(self):
        user = self.env.user
        # Admin SaaS chooses tenant manually in the form.
        if user.is_studio_manager():
            return False
        if user.studio_tenant_ids:
            return user.studio_tenant_ids[:1].id
        return False

    @api.model
    def _get_forced_tenant_for_user(self):
        """Return tenant forced by current user role (Admin Tenant)."""
        user = self.env.user
        if user.is_studio_manager():
            return False
        return user.studio_tenant_ids[:1] if user.studio_tenant_ids else False

    DAY_OF_WEEK_SELECTION = [
        ("0", "Monday"),
        ("1", "Tuesday"),
        ("2", "Wednesday"),
        ("3", "Thursday"),
        ("4", "Friday"),
        ("5", "Saturday"),
        ("6", "Sunday"),
    ]

    @api.model
    def _selection_time_slots(self):
        slots = []
        for hour in range(24):
            for minute in (0, 15, 30, 45):
                value = f"{hour:02d}:{minute:02d}"
                slots.append((value, value))
        return slots

    tenant_id = fields.Many2one(
        "studio.tenant",
        required=True,
        ondelete="restrict",
        index=True,
        default=_default_tenant_id,
    )
    branch_id = fields.Many2one(
        "studio.branch",
        required=True,
        ondelete="restrict",
        index=True,
    )
    room_id = fields.Many2one(
        "studio.room",
        required=True,
        ondelete="restrict",
        index=True,
    )
    instructor_id = fields.Many2one(
        "studio.instructor",
        required=True,
        ondelete="restrict",
        index=True,
    )
    template_id = fields.Many2one(
        "studio.class_template",
        required=True,
        ondelete="restrict",
        index=True,
    )
    # Backward-compatible alias used by some existing tests/views.
    class_template_id = fields.Many2one(
        related="template_id",
        readonly=False,
        store=True,
    )
    name = fields.Char(required=False, index=True)
    capacity = fields.Integer(required=True, default=20)
    day_of_week = fields.Selection(
        DAY_OF_WEEK_SELECTION,
        required=False,
        index=True,
    )
    start_time = fields.Selection(
        selection=_selection_time_slots,
        required=True,
        default="09:00",
        help="Session start time (HH:MM).",
    )  # 🔁 Controlled dropdown time, not free-text input
    end_time = fields.Selection(
        selection=_selection_time_slots,
        required=True,
        default="10:00",
        help="Session end time (HH:MM).",
    )  # 🔁 Controlled dropdown time, not free-text input
    active = fields.Boolean(default=True, index=True)
    # Backward-compatible alias.
    is_active = fields.Boolean(
        related="active",
        readonly=False,
        store=True,
        index=True,
    )
    is_recurring = fields.Boolean(default=False, index=True)
    recurring_number = fields.Integer(
        default=1,
        help="Repeat every N units based on recurring range.",
    )
    recurring_range = fields.Selection(
        [
            ("day", "Day"),
            ("week", "Week"),
            ("month", "Month"),
        ],
        default="week",
        help="Recurring unit used with recurring number.",
    )
    start_date = fields.Date(required=True, default=fields.Date.context_today, index=True)
    end_date = fields.Date(index=True)
    last_generated_at = fields.Datetime(copy=False, readonly=True)
    next_generation_date = fields.Date(copy=False, readonly=True)
    checkin_close_minutes_before = fields.Integer(default=15)
    session_ids = fields.One2many(
        "studio.class_session",
        "session_template_id",
        string="Generated Sessions",
        copy=False,
    )

    @api.model
    def _time_value_to_time(self, value):
        if not value:
            return time(hour=0, minute=0)
        if isinstance(value, float):
            # 🔁 Backward-compatible support for older float-based records
            hours = int(value)
            minutes = int(round((value - hours) * 60))
            if minutes == 60:
                hours += 1
                minutes = 0
            return time(hour=hours, minute=minutes)
        if isinstance(value, str) and ":" in value:
            hours, minutes = value.split(":")
            return time(hour=int(hours), minute=int(minutes))
        if isinstance(value, str):
            # ✅ Backward-compatible support for legacy numeric strings like "7.25"
            try:
                float_value = float(value)
            except ValueError:
                raise ValidationError(_("Invalid time value: %s") % value)
            hours = int(float_value)
            minutes = int(round((float_value - hours) * 60))
            if minutes == 60:
                hours += 1
                minutes = 0
            return time(hour=hours, minute=minutes)
        raise ValidationError(_("Invalid time value: %s") % value)

    def _build_display_name(self):
        self.ensure_one()
        day_label = dict(self.DAY_OF_WEEK_SELECTION).get(
            self.day_of_week, self.day_of_week
        )
        start_label = self._time_value_to_time(self.start_time).strftime("%H:%M")
        return _("%(clazz)s - %(day)s - %(start)s") % {
            "clazz": self.template_id.name or _("Class"),
            "day": day_label,
            "start": start_label,
        }

    def _compute_display_name(self):
        for rec in self:
            rec.display_name = rec._build_display_name()

    def _ensure_template_name(self):
        for rec in self:
            if not rec.name:
                rec.name = rec._build_display_name()

    def _get_weekday_index(self):
        self.ensure_one()
        mapping = {
            "0": 0,
            "1": 1,
            "2": 2,
            "3": 3,
            "4": 4,
            "5": 5,
            "6": 6,
            # Backward-compatible read for legacy values.
            "monday": 0,
            "tuesday": 1,
            "wednesday": 2,
            "thursday": 3,
            "friday": 4,
            "saturday": 5,
            "sunday": 6,
        }
        if self.day_of_week not in mapping:
            raise ValidationError(_("Day of week is required for weekly recurrence."))
        return mapping[self.day_of_week]

    def _is_time_overlap(self, other):
        self.ensure_one()
        self_start = self._time_value_to_time(self.start_time)
        self_end = self._time_value_to_time(self.end_time)
        other_start = other._time_value_to_time(other.start_time)
        other_end = other._time_value_to_time(other.end_time)
        return self_start < other_end and self_end > other_start

    def _get_template_conflicting_domain(self):
        self.ensure_one()
        domain = [
            ("id", "!=", self.id),
            ("tenant_id", "=", self.tenant_id.id),
            ("active", "=", True),
        ]
        if self.recurring_range == "week" and self.day_of_week:
            domain.append(("day_of_week", "=", self.day_of_week))
        return domain

    def _validate_template_on_save(self):
        self._check_time_range()
        self._check_template_schedule_conflicts()
        for rec in self:
            if rec.capacity <= 0:
                raise ValidationError(_("Capacity must be greater than zero."))
            if rec.room_id and rec.capacity > rec.room_id.capacity:
                raise ValidationError(
                    _(
                        "Session capacity (%(session)s) cannot be greater than room capacity (%(room)s)."
                    )
                    % {
                        "session": rec.capacity,
                        "room": rec.room_id.capacity,
                    }
                )
            if rec.checkin_close_minutes_before < 0:
                raise ValidationError(
                    _("Check-in close minutes before must be zero or positive.")
                )
            if rec.is_recurring and rec.recurring_number <= 0:
                raise ValidationError(
                    _("Recurring number must be greater than zero when recurring is enabled.")
                )
            if rec.is_recurring and not rec.recurring_range:
                raise ValidationError(
                    _("Recurring range is required when recurring is enabled.")
                )
            if (
                rec.is_recurring
                and rec.recurring_range == "week"
                and not rec.day_of_week
            ):
                raise ValidationError(
                    _("Day of week is required when recurring range is week.")
                )
            if rec.end_date and rec.end_date < rec.start_date:
                raise ValidationError(_("End date must be on or after start date."))

    def _month_occurrence_from_start(self, offset_months):
        self.ensure_one()
        base = self.start_date
        year = base.year + ((base.month - 1 + offset_months) // 12)
        month = ((base.month - 1 + offset_months) % 12) + 1
        day = min(base.day, monthrange(year, month)[1])
        return base.replace(year=year, month=month, day=day)

    def _get_generation_horizon_end(self, horizon_days=7):
        self.ensure_one()
        today = tz_utils.studio_today()
        return today + timedelta(days=max(horizon_days, 0))

    def _get_target_dates_for_horizon(self, horizon_days=7, from_date=None):
        self.ensure_one()
        start_boundary = max(from_date or tz_utils.studio_today(), self.start_date)
        horizon_end = self._get_generation_horizon_end(horizon_days=horizon_days)
        if self.end_date:
            horizon_end = min(horizon_end, self.end_date)
        if start_boundary > horizon_end:
            return []
        if not self.is_recurring:
            return []

        interval = max(self.recurring_number or 0, 1)
        dates = []
        if self.recurring_range == "day":
            cursor = self.start_date
            while cursor < start_boundary:
                cursor += timedelta(days=interval)
            while cursor <= horizon_end:
                dates.append(cursor)
                cursor += timedelta(days=interval)
            return dates

        if self.recurring_range == "week":
            target_weekday = self._get_weekday_index()
            week_anchor = self.start_date - timedelta(days=self.start_date.weekday())
            cursor = start_boundary
            while cursor <= horizon_end:
                if cursor.weekday() == target_weekday:
                    week_index = ((cursor - week_anchor).days // 7) if cursor >= week_anchor else -1
                    if week_index >= 0 and week_index % interval == 0:
                        dates.append(cursor)
                cursor += timedelta(days=1)
            return dates

        if self.recurring_range == "month":
            occurrence_index = 0
            cursor = self._month_occurrence_from_start(occurrence_index)
            while cursor < start_boundary:
                occurrence_index += interval
                cursor = self._month_occurrence_from_start(occurrence_index)
            while cursor <= horizon_end:
                dates.append(cursor)
                occurrence_index += interval
                cursor = self._month_occurrence_from_start(occurrence_index)
            return dates

        return []

    def _get_candidate_session_datetimes(self, horizon_days=7, from_date=None):
        self.ensure_one()
        now = fields.Datetime.now()
        starts = []
        for target_date in self._get_target_dates_for_horizon(
            horizon_days=horizon_days,
            from_date=from_date,
        ):
            start_dt, _end_dt = self._build_session_start_end(target_date)
            if start_dt > now:
                starts.append(start_dt)
        return starts

    def _build_session_start_end(self, target_date):
        self.ensure_one()
        local_start = datetime.combine(target_date, self._time_value_to_time(self.start_time))
        # Always interpret template schedule times in GMT+7 (Asia/Bangkok).
        start_dt = tz_utils.studio_local_to_utc(local_start)
        if self.template_id and self.template_id.duration_minutes > 0:
            end_dt = start_dt + timedelta(minutes=self.template_id.duration_minutes)
        else:
            local_end = datetime.combine(target_date, self._time_value_to_time(self.end_time))
            end_dt = tz_utils.studio_local_to_utc(local_end)
        return start_dt, end_dt

    def _prepare_class_session_vals(self, session_start, session_end):
        self.ensure_one()
        checkin_close_at = False
        if self.checkin_close_minutes_before > 0:
            checkin_close_at = session_start - timedelta(
                minutes=self.checkin_close_minutes_before
            )
        return {
            "session_template_id": self.id,
            "tenant_id": self.tenant_id.id,
            "branch_id": self.branch_id.id,
            "room_id": self.room_id.id,
            "instructor_id": self.instructor_id.id,
            "template_id": self.template_id.id,
            "capacity": self.capacity,
            "session_start": session_start,
            "session_end": session_end,
            "state": "scheduled",
            "generated_by_cron": True,
            "checkin_close_at": checkin_close_at,
        }

    def _session_exists(self, target_start):
        self.ensure_one()
        return self.env["studio.class_session"].search(
            [
                ("session_template_id", "=", self.id),
                ("session_start", "=", target_start),
            ],
            limit=1,
        )

    def _has_room_conflict(self, session_start, session_end):
        self.ensure_one()
        return bool(
            self.env["studio.class_session"].search_count(
                [
                    ("tenant_id", "=", self.tenant_id.id),
                    ("state", "!=", "cancelled"),
                    ("room_id", "=", self.room_id.id),
                    ("session_start", "<", session_end),
                    ("session_end", ">", session_start),
                ]
            )
        )

    def _has_instructor_conflict(self, session_start, session_end):
        self.ensure_one()
        return bool(
            self.env["studio.class_session"].search_count(
                [
                    ("tenant_id", "=", self.tenant_id.id),
                    ("state", "!=", "cancelled"),
                    ("instructor_id", "=", self.instructor_id.id),
                    ("session_start", "<", session_end),
                    ("session_end", ">", session_start),
                ]
            )
        )

    def _generate_session_for_date(self, target_date):
        self.ensure_one()
        if not self.active or not self.is_recurring:
            return False, False
        start_dt, end_dt = self._build_session_start_end(target_date)
        vals = self._prepare_class_session_vals(start_dt, end_dt)
        existing = self._session_exists(vals["session_start"])
        if existing:
            return existing, False
        if self._has_room_conflict(start_dt, end_dt):
            raise ValidationError(_("Room conflict while generating recurring session."))
        if self._has_instructor_conflict(start_dt, end_dt):
            raise ValidationError(
                _("Instructor conflict while generating recurring session.")
            )
        if self.capacity > self.room_id.capacity:
            raise ValidationError(
                _(
                    "Session capacity (%(session)s) cannot be greater than room capacity (%(room)s)."
                )
                % {
                    "session": self.capacity,
                    "room": self.room_id.capacity,
                }
            )
        preview = self.env["studio.class_session"].new(vals)
        preview._check_session_conflicts()
        return self.env["studio.class_session"].create(vals), True

    def _generate_upcoming_sessions(self, horizon_days=7):
        created_count = 0
        for rec in self.filtered(lambda r: r.active and r.is_recurring):
            latest_next_date = False
            for start_dt in rec._get_candidate_session_datetimes(horizon_days=horizon_days):
                target_date = start_dt.date()
                try:
                    _session, created = rec._generate_session_for_date(target_date)
                    if created:
                        created_count += 1
                    latest_next_date = target_date
                except ValidationError as err:
                    _logger.warning(
                        "Studio session template %s skipped date %s due to conflict: %s",
                        rec.id,
                        target_date,
                        err,
                    )
                except Exception as err:  # pragma: no cover - defensive cron safety
                    _logger.warning(
                        "Studio session template %s skipped date %s due to error: %s",
                        rec.id,
                        target_date,
                        err,
                    )
            rec.with_context(skip_template_save_validation=True).write(
                {
                    "last_generated_at": fields.Datetime.now(),
                    "next_generation_date": latest_next_date,
                }
            )
        return created_count

    @api.model
    def _cron_generate_upcoming_sessions(self, horizon_days=7):
        templates = self.search([("active", "=", True), ("is_recurring", "=", True)])
        total = 0
        for template in templates:
            before = self.env["studio.class_session"].search_count(
                [("session_template_id", "=", template.id)]
            )
            template._generate_upcoming_sessions(horizon_days=horizon_days)
            after = self.env["studio.class_session"].search_count(
                [("session_template_id", "=", template.id)]
            )
            total += max(after - before, 0)
        if total:
            _logger.info("Studio session template cron generated %s sessions", total)
        return total

    @api.constrains("start_time", "end_time")
    def _check_time_range(self):
        for rec in self:
            start_time = rec._time_value_to_time(rec.start_time)
            end_time = rec._time_value_to_time(rec.end_time)
            if end_time <= start_time:
                raise ValidationError(_("End time must be later than start time."))

    @api.constrains("branch_id", "tenant_id")
    def _check_branch_tenant(self):
        for rec in self:
            if rec.branch_id and rec.tenant_id and rec.branch_id.tenant_id != rec.tenant_id:
                raise ValidationError(_("Branch must belong to the session template's tenant."))

    @api.constrains("room_id", "branch_id")
    def _check_room_branch(self):
        for rec in self:
            if rec.room_id and rec.branch_id and rec.room_id.branch_id != rec.branch_id:
                raise ValidationError(_("Room must belong to the session template's branch."))

    @api.constrains("instructor_id", "tenant_id")
    def _check_instructor_tenant(self):
        for rec in self:
            if rec.instructor_id and rec.tenant_id and rec.instructor_id.tenant_id != rec.tenant_id:
                raise ValidationError(_("Instructor must belong to the session template's tenant."))

    @api.constrains("class_template_id", "tenant_id")
    def _check_class_template_tenant(self):
        for rec in self:
            if (
                rec.template_id
                and rec.tenant_id
                and rec.template_id.tenant_id != rec.tenant_id
            ):
                raise ValidationError(_("Class template must belong to the session template's tenant."))

    @api.constrains("capacity", "room_id")
    def _check_capacity_not_exceed_room(self):
        for rec in self:
            if rec.room_id and rec.capacity > rec.room_id.capacity:
                raise ValidationError(
                    _(
                        "Session capacity (%(session)s) cannot be greater than room capacity (%(room)s)."
                    )
                    % {
                        "session": rec.capacity,
                        "room": rec.room_id.capacity,
                    }
                )

    @api.constrains("is_recurring", "recurring_number")
    def _check_recurring_number(self):
        for rec in self:
            if rec.is_recurring and rec.recurring_number <= 0:
                raise ValidationError(
                    _("Recurring number must be greater than zero when recurring is enabled.")
                )

    @api.constrains("is_recurring", "recurring_range")
    def _check_recurring_range_required(self):
        for rec in self:
            if rec.is_recurring and not rec.recurring_range:
                raise ValidationError(
                    _("Recurring range is required when recurring is enabled.")
                )

    @api.constrains("is_recurring", "recurring_range", "day_of_week")
    def _check_weekly_requires_day_of_week(self):
        for rec in self:
            if rec.is_recurring and rec.recurring_range == "week" and not rec.day_of_week:
                raise ValidationError(
                    _("Day of week is required when recurring range is week.")
                )

    @api.constrains("start_date", "end_date")
    def _check_date_range(self):
        for rec in self:
            if rec.end_date and rec.end_date < rec.start_date:
                raise ValidationError(_("End date must be on or after start date."))

    @api.onchange("tenant_id")
    def _onchange_tenant_id(self):
        branch_domain = [("id", "=", False)]
        instructor_domain = [("id", "=", False)]
        class_template_domain = [("id", "=", False)]
        room_domain = [("id", "=", False)]
        for rec in self:
            # Requirement: tenant change clears dependent assignment fields.
            rec.branch_id = False
            rec.instructor_id = False
            rec.room_id = False
            rec.template_id = False
            if rec.tenant_id:
                branch_domain = [("tenant_id", "=", rec.tenant_id.id)]
                instructor_domain = [("tenant_id", "=", rec.tenant_id.id)]
                class_template_domain = [("tenant_id", "=", rec.tenant_id.id)]

        return {
            "domain": {
                "branch_id": branch_domain,
                "instructor_id": instructor_domain,
                "template_id": class_template_domain,
                "class_template_id": class_template_domain,
                "room_id": room_domain,
            }
        }

    @api.onchange("branch_id")
    def _onchange_branch_id(self):
        room_domain = [("id", "=", False)]
        for rec in self:
            rec.room_id = False
            if rec.branch_id:
                room_domain = [("branch_id", "=", rec.branch_id.id)]
        return {"domain": {"room_id": room_domain}}

    @api.onchange("room_id")
    def _onchange_room_id(self):
        for rec in self:
            if rec.room_id and not rec.capacity:
                rec.capacity = rec.room_id.capacity

    @api.constrains(
        "day_of_week",
        "start_time",
        "end_time",
        "room_id",
        "instructor_id",
        "active",
        "is_recurring",
    )
    def _check_template_schedule_conflicts(self):
        for rec in self:
            if not rec.active:
                continue
            if rec.recurring_range != "week":
                continue
            candidates = self.search(rec._get_template_conflicting_domain())
            for other in candidates:
                if not rec._is_time_overlap(other):
                    continue
                if rec.room_id == other.room_id:
                    raise ValidationError(
                        _(
                            "Room schedule conflict: %(room)s overlaps with template %(template)s on %(day)s."
                        )
                        % {
                            "room": rec.room_id.display_name,
                            "template": other.display_name,
                            "day": rec.day_of_week,
                        }
                    )
                if rec.instructor_id == other.instructor_id:
                    raise ValidationError(
                        _(
                            "Instructor schedule conflict: %(instructor)s overlaps with template %(template)s on %(day)s."
                        )
                        % {
                            "instructor": rec.instructor_id.display_name,
                            "template": other.display_name,
                            "day": rec.day_of_week,
                        }
                    )

    @api.model_create_multi
    def create(self, vals_list):
        Tenant = self.env["studio.tenant"]
        forced_tenant = self._get_forced_tenant_for_user()
        for vals in vals_list:
            if vals.get("class_template_id") and not vals.get("template_id"):
                vals["template_id"] = vals.get("class_template_id")
            if forced_tenant:
                vals["tenant_id"] = forced_tenant.id
            tenant = Tenant.browse(vals.get("tenant_id"))
            if not tenant:
                raise ValidationError(_("Tenant is required for session template."))
            self.env.user.ensure_studio_tenant_allowed(tenant)
        records = super().create(vals_list)
        records._ensure_template_name()  # 🔁 Keep backend name auto-filled
        records._validate_template_on_save()  # 🔁 Explicit create-time restrictions
        return records

    def write(self, vals):
        Tenant = self.env["studio.tenant"]
        forced_tenant = self._get_forced_tenant_for_user()
        if vals.get("class_template_id") and not vals.get("template_id"):
            vals["template_id"] = vals.get("class_template_id")
        if forced_tenant:
            if vals.get("tenant_id") and vals.get("tenant_id") != forced_tenant.id:
                raise ValidationError(_("Admin Tenant users cannot change tenant."))
            vals["tenant_id"] = forced_tenant.id
        if vals.get("tenant_id"):
            tenant = Tenant.browse(vals.get("tenant_id"))
            self.env.user.ensure_studio_tenant_allowed(tenant)
        for rec in self:
            self.env.user.ensure_studio_tenant_allowed(rec.tenant_id)
        res = super().write(vals)
        if not self.env.context.get("skip_template_save_validation"):
            self._ensure_template_name()
            self._validate_template_on_save()
        return res
