# Copyright 2025
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl.html).

import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class StudioClassTemplate(models.Model):
    _inherit = "studio.class_template"

    category_id = fields.Many2one(
        "studio.class_category",
        string="Category",
        ondelete="set null",
        index=True,
        domain="[('tenant_id', '=', tenant_id)]",
        help="Optional category grouping (e.g. Backbend, Props, Strength).",
    )
