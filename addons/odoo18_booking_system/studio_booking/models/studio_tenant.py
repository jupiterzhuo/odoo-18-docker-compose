# Copyright 2025
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl.html).

import logging
from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class StudioTenant(models.Model):
    _name = "studio.tenant"
    _description = "Studio Tenant"
    _order = "name"

    _sql_constraints = [
        ("code_unique", "UNIQUE(code)", "Tenant code must be unique."),
    ]

    name = fields.Char(required=True, index=True)
    code = fields.Char(
        string="Code",
        index=True,
        copy=False,
        help="Short unique identifier used by the external member app for login.",
    )
    email = fields.Char()
    phone = fields.Char()
    website_url = fields.Char(string="Website URL")
    login_url = fields.Char(string="Login URL")
    logo = fields.Binary(string="Logo", attachment=True)
    active = fields.Boolean(default=True)
    branch_ids = fields.One2many(
        "studio.branch",
        "tenant_id",
        string="Branches",
        copy=False,
    )
    branch_count = fields.Integer(compute="_compute_branch_count", store=True)

    @api.depends("branch_ids")
    def _compute_branch_count(self):
        for r in self:
            r.branch_count = len(r.branch_ids)

    @api.model
    def _resolve_from_code_or_id(self, code=None, tenant_id=None):
        """Resolve an active tenant by app-facing code or by database ID."""
        if code:
            return self.search(
                [("code", "=", str(code).strip()), ("active", "=", True)], limit=1
            )
        if isinstance(tenant_id, int) and tenant_id:
            return self.search(
                [("id", "=", tenant_id), ("active", "=", True)], limit=1
            )
        return self.browse()
