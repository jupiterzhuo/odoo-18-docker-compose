# Copyright 2025
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl.html).

import logging
from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class StudioClassTemplate(models.Model):
    _name = "studio.class_template"
    _description = "Studio Class Template"
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
    duration_minutes = fields.Integer(default=60, required=True)
    session_ids = fields.One2many(
        "studio.class_session",
        "template_id",
        string="Sessions",
        copy=False,
    )

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
