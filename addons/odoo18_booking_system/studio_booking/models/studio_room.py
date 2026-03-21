# Copyright 2025
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl.html).

import logging
from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class StudioRoom(models.Model):
    _name = "studio.room"
    _description = "Studio Room"
    _order = "branch_id, name"

    @api.model
    def _default_tenant_id(self):
        user = self.env.user
        if user.studio_tenant_ids:
            return user.studio_tenant_ids[:1].id
        return False

    tenant_id = fields.Many2one(
        "studio.tenant",
        required=True,
        index=True,
        default=_default_tenant_id,
    )
    branch_id = fields.Many2one(
        "studio.branch",
        required=True,
        ondelete="restrict",
        index=True,
    )
    name = fields.Char(required=True, index=True)
    active = fields.Boolean(default=True)
    capacity = fields.Integer(
        default=20,
        required=True,
        help="Default capacity for class sessions in this room.",
    )
    @api.onchange("branch_id")
    def _onchange_branch_id(self):
        if self.branch_id:
            self.tenant_id = self.branch_id.tenant_id

    @api.onchange("tenant_id")
    def _onchange_tenant_id(self):
        if self.branch_id and self.branch_id.tenant_id != self.tenant_id:
            self.branch_id = False

    @api.model_create_multi
    def create(self, vals_list):
        Branch = self.env["studio.branch"]
        for vals in vals_list:
            branch = Branch.browse(vals.get("branch_id"))
            self.env.user.ensure_studio_tenant_allowed(branch.tenant_id)
            vals["tenant_id"] = branch.tenant_id.id
        return super().create(vals_list)

    def write(self, vals):
        Branch = self.env["studio.branch"]
        if vals.get("branch_id"):
            branch = Branch.browse(vals.get("branch_id"))
            self.env.user.ensure_studio_tenant_allowed(branch.tenant_id)
            vals["tenant_id"] = branch.tenant_id.id
        for rec in self:
            self.env.user.ensure_studio_tenant_allowed(rec.tenant_id)
        return super().write(vals)
