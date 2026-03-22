# Copyright 2025
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl.html).

import logging
from datetime import timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class StudioMembershipSubscription(models.Model):
    _inherit = "studio.membership_subscription"

    plan_type = fields.Selection(
        related="plan_id.plan_type",
        store=True,
        index=True,
        readonly=True,
    )
    total_credits = fields.Integer(
        string="Total Credits",
        default=0,
        help="Copied from plan at creation; frozen if the plan is edited later.",
    )
    used_credits = fields.Integer(
        compute="_compute_credit_usage",
        store=True,
        string="Used Credits",
        help="Completed sessions in this subscription window (bookings finalized).",
    )
    pending_credits = fields.Integer(
        compute="_compute_credit_usage",
        store=True,
        string="Pending Credits",
        help="Active bookings not yet finalized (booked / promoted / waitlisted).",
    )
    available_credits = fields.Integer(
        compute="_compute_credit_usage",
        store=True,
        string="Available Credits",
        help="total_credits - used - pending (session-based only).",
    )
    is_single_use = fields.Boolean(
        related="plan_id.is_single_use",
        store=True,
        readonly=True,
    )
    is_single_use_consumed = fields.Boolean(
        string="Single-Use Consumed",
        default=False,
        help="Set after the first qualifying booking for single-use (drop-in) plans.",
    )

    @api.depends(
        "total_credits",
        "plan_type",
        "member_profile_id",
        "tenant_id",
        "date_start",
        "date_end",
    )
    def _compute_credit_usage(self):
        """
        Bookings are the source of truth. Session-based only; time-based → zeros.

        - Used: booking_status == completed (covers attended + no_show after session finalization).
        - Pending: booked, promoted, waitlisted.
        """
        Booking = self.env["studio.booking"]
        for rec in self:
            if rec.plan_type != "session_based":
                rec.used_credits = 0
                rec.pending_credits = 0
                rec.available_credits = 0
                continue

            domain = [
                ("member_profile_id", "=", rec.member_profile_id.id),
                ("tenant_id", "=", rec.tenant_id.id),
            ]
            if rec.date_start:
                domain.append(
                    (
                        "session_id.session_start",
                        ">=",
                        fields.Datetime.to_datetime(rec.date_start),
                    )
                )
            if rec.date_end:
                end_dt = fields.Datetime.to_datetime(rec.date_end) + timedelta(days=1)
                domain.append(("session_id.session_start", "<", end_dt))

            used = Booking.search_count(
                domain + [("booking_status", "=", "completed")]
            )
            pending = Booking.search_count(
                domain
                + [
                    (
                        "booking_status",
                        "in",
                        ["booked", "promoted", "waitlisted"],
                    )
                ]
            )

            rec.used_credits = used
            rec.pending_credits = pending
            rec.available_credits = max(rec.total_credits - used - pending, 0)

    @api.model
    def _studio_member_subscription_recompute_credits_for_booking_event(
        self, member_profile_id, tenant_id
    ):
        """Refresh stored credit counters when a member's bookings change (ORM only)."""
        if not member_profile_id or not tenant_id:
            return
        subs = self.search(
            [
                ("member_profile_id", "=", member_profile_id),
                ("tenant_id", "=", tenant_id),
                ("plan_type", "=", "session_based"),
            ]
        )
        if subs:
            subs._compute_credit_usage()

    @api.onchange("plan_id", "date_start")
    def _onchange_plan_validity_days(self):
        plan = self.plan_id
        if plan and self.date_start and getattr(plan, "validity_days", 0):
            self.date_end = self.date_start + timedelta(days=plan.validity_days)

    @api.model_create_multi
    def create(self, vals_list):
        Plan = self.env["studio.membership_plan"]
        for vals in vals_list:
            plan_id = vals.get("plan_id")
            if not plan_id:
                continue
            plan = Plan.browse(plan_id)
            if plan.plan_type == "session_based" and not vals.get("total_credits"):
                vals["total_credits"] = plan.total_credits
            if plan.validity_days and vals.get("date_start") and not vals.get("date_end"):
                ds = vals["date_start"]
                if isinstance(ds, str):
                    ds = fields.Date.to_date(ds)
                vals["date_end"] = ds + timedelta(days=plan.validity_days)
        return super().create(vals_list)
