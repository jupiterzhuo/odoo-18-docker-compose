# Copyright 2025
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl.html).

import logging
from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class StudioBranch(models.Model):
    _name = "studio.branch"
    _description = "Studio Branch"
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
    room_ids = fields.One2many(
        "studio.room",
        "branch_id",
        string="Rooms",
        copy=False,
    )
    room_count = fields.Integer(compute="_compute_room_count", store=True)

    @api.model_create_multi
    def create(self, vals_list):
        Tenant = self.env["studio.tenant"]
        for vals in vals_list:
            tenant = Tenant.browse(vals.get("tenant_id"))
            self.env.user.ensure_studio_tenant_allowed(tenant)
        return super().create(vals_list)

    def write(self, vals):
        Tenant = self.env["studio.tenant"]
        if vals.get("tenant_id"):
            tenant = Tenant.browse(vals.get("tenant_id"))
            self.env.user.ensure_studio_tenant_allowed(tenant)
        for rec in self:
            self.env.user.ensure_studio_tenant_allowed(rec.tenant_id)
        return super().write(vals)

    @api.depends("room_ids")
    def _compute_room_count(self):
        for r in self:
            r.room_count = len(r.room_ids)

    def _serialize_for_api(self):
        """Return a dict safe for external API responses."""
        self.ensure_one()
        return {
            "id": self.id,
            "name": self.name,
            "tenant_id": self.tenant_id.id,
        }

    def action_view_rooms(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "studio_booking.action_studio_room"
        )
        action["domain"] = [("branch_id", "=", self.id)]
        action["context"] = {
            "default_branch_id": self.id,
            "default_tenant_id": self.tenant_id.id,
        }
        return action
