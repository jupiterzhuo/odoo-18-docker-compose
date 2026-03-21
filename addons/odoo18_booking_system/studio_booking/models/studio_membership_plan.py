# Copyright 2025
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl.html).

import logging
from odoo import api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class StudioMembershipPlan(models.Model):
    _name = "studio.membership_plan"
    _description = "Studio Membership Plan"
    _order = "tenant_id, name"

    @api.model
    def _default_tenant_id(self):
        user = self.env.user
        if user.studio_tenant_ids:
            return user.studio_tenant_ids[:1].id
        return False

    tenant_id = fields.Many2one(
        "studio.tenant",
        required=True,
        ondelete="restrict",
        index=True,
        default=_default_tenant_id,
    )
    name = fields.Char(required=True, index=True)
    active = fields.Boolean(default=True)
    branch_ids = fields.Many2many(
        "studio.branch",
        "studio_plan_branch_rel",
        "plan_id",
        "branch_id",
        string="Allowed Branches",
        help="Leave empty for all_club to mean all branches.",
    )
    subscription_ids = fields.One2many(
        "studio.membership_subscription",
        "plan_id",
        string="Subscriptions",
    )
    member_count = fields.Integer(compute="_compute_member_count")

    @api.onchange("tenant_id")
    def _onchange_tenant_id(self):
        if self.tenant_id:
            self.branch_ids = self.branch_ids.filtered(
                lambda b: b.tenant_id == self.tenant_id
            )
        else:
            self.branch_ids = [(5, 0, 0)]

    @api.constrains("tenant_id", "branch_ids")
    def _check_branches_match_tenant(self):
        for rec in self:
            invalid = rec.branch_ids.filtered(lambda b: b.tenant_id != rec.tenant_id)
            if invalid:
                raise ValidationError(
                    "Allowed branches must belong to the selected tenant."
                )

    def _compute_member_count(self):
        for rec in self:
            rec.member_count = len(rec.subscription_ids.mapped("member_profile_id"))

    def action_view_members(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "studio_booking.action_studio_member_profile"
        )
        member_ids = self.subscription_ids.mapped("member_profile_id").ids
        action["domain"] = [("id", "in", member_ids)]
        action["context"] = {
            "default_tenant_id": self.tenant_id.id,
        }
        return action
