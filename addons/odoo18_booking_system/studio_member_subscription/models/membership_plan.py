# Copyright 2025
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl.html).

import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class StudioMembershipPlan(models.Model):
    _inherit = "studio.membership_plan"

    plan_type = fields.Selection(
        [
            ("time_based", "Time-Based"),
            ("session_based", "Session-Based"),
        ],
        string="Plan Type",
        required=True,
        default="time_based",
        help="Time-Based: unlimited booking within the subscription date range. "
        "Session-Based: credit quota deducted per completed session.",
    )
    total_credits = fields.Integer(
        string="Total Credits",
        default=0,
        help="Total session credits for session-based plans (e.g. 55 = 50 + 5 bonus).",
    )
    validity_days = fields.Integer(
        string="Validity (days)",
        default=0,
        help="If set, subscription end date can default to start date + this many days. "
        "0 means set end date manually.",
    )
    price = fields.Float(
        string="Price",
        digits=(12, 2),
        default=0.0,
        help="Display price (informational only).",
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        default=lambda self: self.env.ref("base.IDR", raise_if_not_found=False)
        or self.env.company.currency_id,
    )
    max_bookings_per_day = fields.Integer(
        string="Max Bookings Per Day",
        default=0,
        help="0 = unlimited.",
    )
    is_single_use = fields.Boolean(
        string="Single Drop-In",
        default=False,
        help="If set, subscription is consumed after one booking (time-based drop-in).",
    )
    description = fields.Text(
        string="Description",
        help="Plan description or admin notes.",
    )

    @api.constrains("plan_type", "total_credits")
    def _check_session_credits(self):
        for rec in self:
            if rec.plan_type == "session_based" and rec.total_credits <= 0:
                raise ValidationError(
                    _("Session-based plans must have total credits greater than zero.")
                )

    @api.onchange("plan_type")
    def _onchange_plan_type(self):
        if self.plan_type == "time_based":
            self.total_credits = 0
            self.is_single_use = False
        elif self.plan_type == "session_based":
            self.is_single_use = False
