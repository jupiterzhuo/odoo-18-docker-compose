# Copyright 2025
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl.html).

import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class StudioClassCategory(models.Model):
    _name = "studio.class_category"
    _description = "Class Category"
    _order = "tenant_id, sequence, name"

    @api.model
    def _default_tenant_id(self):
        user = self.env.user
        if user.studio_tenant_ids:
            return user.studio_tenant_ids[:1].id
        return False

    tenant_id = fields.Many2one(
        "studio.tenant",
        string="Tenant",
        required=True,
        ondelete="restrict",
        index=True,
        default=_default_tenant_id,
    )
    name = fields.Char(
        string="Name",
        required=True,
        index=True,
        help="Examples: Props, Backbend, Strength, Stretch.",
    )
    active = fields.Boolean(default=True)
    sequence = fields.Integer(
        string="Sequence",
        default=10,
        help="Display order in lists and dropdowns.",
    )
    class_template_ids = fields.One2many(
        "studio.class_template",
        "category_id",
        string="Class Templates",
    )
    template_count = fields.Integer(
        string="Template Count",
        compute="_compute_template_count",
    )

    @api.depends("class_template_ids")
    def _compute_template_count(self):
        for rec in self:
            rec.template_count = len(rec.class_template_ids)

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

    @api.constrains("tenant_id", "name")
    def _check_unique_name_per_tenant(self):
        for rec in self:
            existing = self.search(
                [
                    ("tenant_id", "=", rec.tenant_id.id),
                    ("name", "=ilike", rec.name),
                    ("id", "!=", rec.id),
                ],
                limit=1,
            )
            if existing:
                raise ValidationError(
                    _("Category '%(name)s' already exists for this tenant.")
                    % {"name": rec.name}
                )

    def action_view_templates(self):
        """Smart button: open class templates filtered by this category."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Class Templates — %s") % self.name,
            "res_model": "studio.class_template",
            "view_mode": "list,form",
            "domain": [("category_id", "=", self.id)],
            "context": {
                "default_tenant_id": self.tenant_id.id,
                "default_category_id": self.id,
            },
        }
