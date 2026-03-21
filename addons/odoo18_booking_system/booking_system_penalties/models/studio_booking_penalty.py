# Copyright 2025
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl.html).

from odoo import api, fields, models


class StudioBookingPenalty(models.Model):
    _name = "studio.booking_penalty"
    _description = "Booking Penalty"
    _order = "create_date desc, id desc"

    name = fields.Char(
        string="Title",
        required=True,
        help="Short label, e.g. Late cancel — Yoga Mon 6pm.",
    )
    active = fields.Boolean(default=True)
    tenant_id = fields.Many2one(
        "studio.tenant",
        string="Studio",
        required=True,
        index=True,
        ondelete="cascade",
    )
    booking_id = fields.Many2one(
        "studio.booking",
        string="Booking",
        ondelete="set null",
        index=True,
        domain="[('tenant_id', '=', tenant_id)]",
    )
    penalty_type = fields.Selection(
        selection=[
            ("late_cancel", "Late cancellation"),
            ("no_show", "No-show"),
            ("other", "Other"),
        ],
        string="Type",
        default="other",
        required=True,
    )
    amount = fields.Monetary(
        string="Amount",
        currency_field="currency_id",
        help="Optional monetary penalty (configure company currency).",
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        default=lambda self: self.env.company.currency_id,
    )
    notes = fields.Text(string="Notes")

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if "tenant_id" in fields_list and not res.get("tenant_id"):
            tenants = self.env.user.studio_tenant_ids
            if len(tenants) == 1:
                res["tenant_id"] = tenants.id
        return res

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            tid = vals.get("tenant_id")
            if tid:
                self.env.user.ensure_studio_tenant_allowed(
                    self.env["studio.tenant"].browse(tid)
                )
        return super().create(vals_list)

    def write(self, vals):
        if vals.get("tenant_id"):
            self.env.user.ensure_studio_tenant_allowed(
                self.env["studio.tenant"].browse(vals["tenant_id"])
            )
        return super().write(vals)
