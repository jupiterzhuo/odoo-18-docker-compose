# Copyright 2025
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl.html).

import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class StudioBooking(models.Model):
    _inherit = "studio.booking"

    def _studio_member_subscription_after_booking_change(self):
        """Keep subscription credit fields in sync; mark single-use drop-ins consumed."""
        Subscription = self.env["studio.membership_subscription"]
        keys = set()
        for booking in self:
            if booking.member_profile_id and booking.tenant_id:
                keys.add((booking.member_profile_id.id, booking.tenant_id.id))
        for member_profile_id, tenant_id in keys:
            Subscription._studio_member_subscription_recompute_credits_for_booking_event(
                member_profile_id, tenant_id
            )
        self._studio_member_subscription_mark_single_use()

    def _studio_member_subscription_mark_single_use(self):
        """Mark time-based single-use subscriptions consumed after first active booking."""
        Subscription = self.env["studio.membership_subscription"]
        for booking in self:
            if booking.booking_status not in ("booked", "promoted", "waitlisted"):
                continue
            if not booking.member_profile_id:
                continue
            subs = Subscription.search(
                [
                    ("member_profile_id", "=", booking.member_profile_id.id),
                    ("state", "=", "active"),
                    ("plan_id.plan_type", "=", "time_based"),
                    ("plan_id.is_single_use", "=", True),
                    ("is_single_use_consumed", "=", False),
                ],
                limit=1,
            )
            if subs:
                subs.write({"is_single_use_consumed": True})

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._studio_member_subscription_after_booking_change()
        return records

    def write(self, vals):
        res = super().write(vals)
        if (
            "booking_status" in vals
            or "member_profile_id" in vals
            or "session_id" in vals
            or "tenant_id" in vals
        ):
            self._studio_member_subscription_after_booking_change()
        return res
