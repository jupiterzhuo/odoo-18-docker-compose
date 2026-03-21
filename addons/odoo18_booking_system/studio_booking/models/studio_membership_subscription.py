# Copyright 2025
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl.html).

import logging
from odoo import _, api, fields, models

from ..utils import timezone as tz_utils
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class StudioMembershipSubscription(models.Model):
    _name = "studio.membership_subscription"
    _description = "Studio Membership Subscription (history)"
    _order = "member_profile_id, date_start desc"

    member_profile_id = fields.Many2one(
        "studio.member_profile",
        required=True,
        ondelete="restrict",
        index=True,
    )
    tenant_id = fields.Many2one(
        "studio.tenant",
        related="member_profile_id.tenant_id",
        store=True,
        index=True,
    )
    plan_id = fields.Many2one(
        "studio.membership_plan",
        required=True,
        ondelete="restrict",
        index=True,
        domain="[('tenant_id', '=', tenant_id)]",
    )
    date_start = fields.Date(required=True)
    date_end = fields.Date()
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("active", "Active"),
            ("expired", "Expired"),
            ("cancelled", "Cancelled"),
        ],
        default="draft",
        required=True,
        index=True,
    )

    @api.onchange("date_start", "date_end")
    def _onchange_dates(self):
        if self.date_end and self.date_start and self.date_end <= self.date_start:
            self.date_end = False
            return {
                "warning": {
                    "title": _("Invalid Date Range"),
                    "message": _("End date must be later than start date."),
                }
            }

    @api.constrains("date_start", "date_end")
    def _check_dates(self):
        for rec in self:
            if rec.date_end and rec.date_end <= rec.date_start:
                raise ValidationError(
                    _("End date must be later than start date.")
                )

    @api.constrains("member_profile_id", "state")
    def _check_single_active_subscription_per_member(self):
        for rec in self:
            if rec.state != "active" or not rec.member_profile_id:
                continue
            other_active = self.search(
                [
                    ("id", "!=", rec.id),
                    ("member_profile_id", "=", rec.member_profile_id.id),
                    ("state", "=", "active"),
                ],
                limit=1,
            )
            if other_active:
                raise ValidationError(
                    _("Only one active subscription is allowed per member profile.")
                )

    @api.constrains("tenant_id", "plan_id")
    def _check_plan_matches_tenant(self):
        for rec in self:
            if rec.plan_id and rec.tenant_id and rec.plan_id.tenant_id != rec.tenant_id:
                raise ValidationError(
                    _("Selected plan must belong to the member tenant.")
                )

    @api.model
    def _cron_expire_ended_subscriptions(self):
        """Expire subscriptions that ended before today (GMT+7)."""
        today = tz_utils.studio_today()
        subs = self.search(
            [
                ("state", "=", "active"),
                ("date_end", "!=", False),
                ("date_end", "<", today),
            ]
        )
        if subs:
            subs.with_context(allow_set_expired=True).write({"state": "expired"})
            _logger.info(
                "Studio membership: expired %s subscriptions ending before %s",
                len(subs),
                today,
            )

    @api.model
    def _cron_activate_started_subscriptions(self):
        """Activate draft subscriptions in the current validity window (GMT+7)."""
        today = tz_utils.studio_today()
        candidates = self.search(
            [
                ("state", "=", "draft"),
                ("date_start", "<=", today),
                "|",
                ("date_end", "=", False),
                ("date_end", ">=", today),
            ],
            order="member_profile_id, date_start desc, id desc",
        )
        activated = 0
        skipped = 0
        seen_members = set()
        for sub in candidates:
            member_id = sub.member_profile_id.id
            if member_id in seen_members:
                continue
            seen_members.add(member_id)
            has_active = self.search_count(
                [
                    ("member_profile_id", "=", member_id),
                    ("state", "=", "active"),
                ]
            )
            if has_active:
                skipped += 1
                continue
            sub.write({"state": "active"})
            activated += 1
        if activated or skipped:
            _logger.info(
                "Studio membership: auto-activated %s subscriptions, skipped %s members already active",
                activated,
                skipped,
            )

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("allow_set_expired"):
            for vals in vals_list:
                if vals.get("state") == "expired":
                    raise ValidationError(
                        _("Expired status is managed by the system and cannot be set manually.")
                    )
        return super().create(vals_list)

    def write(self, vals):
        if (
            any(rec.state == "expired" for rec in self)
            and not self.env.context.get("allow_set_expired")
        ):
            raise ValidationError(
                _("Expired subscriptions are locked and cannot be modified.")
            )
        if "state" in vals:
            target_state = vals.get("state")
            if target_state == "expired" and not self.env.context.get(
                "allow_set_expired"
            ):
                raise ValidationError(
                    _("Expired status is managed by the system and cannot be set manually.")
                )
            if target_state != "expired" and any(rec.state == "expired" for rec in self):
                raise ValidationError(
                    _("Expired subscriptions are locked and cannot be changed to another status.")
                )
        return super().write(vals)

    def unlink(self):
        if any(rec.state == "expired" for rec in self):
            raise ValidationError(
                _("Expired subscriptions cannot be deleted.")
            )
        return super().unlink()
