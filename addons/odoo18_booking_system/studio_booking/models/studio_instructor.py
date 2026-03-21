# Copyright 2025
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl.html).

import logging
from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class StudioInstructor(models.Model):
    _name = "studio.instructor"
    _description = "Studio Instructor"
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
    first_name = fields.Char()
    last_name = fields.Char()
    name = fields.Char(
        compute="_compute_name",
        store=True,
        index=True,
    )
    email = fields.Char(index=True)
    phone = fields.Char()
    partner_id = fields.Many2one(
        "res.partner",
        ondelete="set null",
        string="Related Contact",
        help="Auto-created/linked contact for interoperability with standard Odoo apps.",
    )
    active = fields.Boolean(default=True)

    @api.depends("first_name", "last_name")
    def _compute_name(self):
        for rec in self:
            rec.name = " ".join(
                [x for x in [rec.first_name, rec.last_name] if x]
            ).strip()

    @api.model
    def _prepare_partner_vals(self, vals):
        full_name = " ".join(
            [x for x in [vals.get("first_name"), vals.get("last_name")] if x]
        ).strip()
        return {
            "name": full_name,
            "email": vals.get("email"),
            "phone": vals.get("phone"),
            "type": "contact",
            "is_company": False,
        }

    @api.model_create_multi
    def create(self, vals_list):
        Tenant = self.env["studio.tenant"]
        for vals in vals_list:
            tenant = Tenant.browse(vals.get("tenant_id"))
            self.env.user.ensure_studio_tenant_allowed(tenant)
        records = super().create(vals_list)
        for rec, vals in zip(records, vals_list):
            if not rec.partner_id:
                rec.partner_id = self.env["res.partner"].create(
                    rec._prepare_partner_vals(vals)
                )
        return records

    def write(self, vals):
        Tenant = self.env["studio.tenant"]
        if vals.get("tenant_id"):
            tenant = Tenant.browse(vals.get("tenant_id"))
            self.env.user.ensure_studio_tenant_allowed(tenant)
        for rec in self:
            self.env.user.ensure_studio_tenant_allowed(rec.tenant_id)
        res = super().write(vals)
        for rec in self:
            if rec.partner_id and any(
                k in vals for k in ["first_name", "last_name", "email", "phone"]
            ):
                rec.partner_id.write(
                    {
                        "name": rec.name,
                        "email": rec.email,
                        "phone": rec.phone,
                    }
                )
            elif not rec.partner_id and any(
                k in vals for k in ["first_name", "last_name", "email", "phone"]
            ):
                rec.partner_id = self.env["res.partner"].create(
                    {
                        "name": rec.name,
                        "email": rec.email,
                        "phone": rec.phone,
                        "type": "contact",
                        "is_company": False,
                    }
                )
        return res
