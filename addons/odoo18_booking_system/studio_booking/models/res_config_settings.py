# Copyright 2025
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl.html).

from odoo import api, fields, models

from ..utils.jwt_helper import JWT_SECRET_PARAM
from ..utils.push_helper import VAPID_PRIVATE_KEY_PARAM


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    jwt_secret = fields.Char(
        string="JWT Secret",
        help="Secret key for signing member app JWT tokens. Required for access_token in login response.",
    )
    vapid_private_key = fields.Char(
        string="VAPID Private Key",
        help="Secret key for Web Push (VAPID). Must match NEXT_PUBLIC_VAPID_PUBLIC_KEY on frontend. Generate with: npx web-push generate-vapid-keys",
    )

    @api.model
    def get_values(self):
        res = super().get_values()
        ICP = self.env["ir.config_parameter"].sudo()
        value = (ICP.get_param(JWT_SECRET_PARAM) or "").strip()
        res["jwt_secret"] = "********" if value else ""
        vapid = (ICP.get_param(VAPID_PRIVATE_KEY_PARAM) or "").strip()
        res["vapid_private_key"] = "********" if vapid else ""
        return res

    def set_values(self):
        super().set_values()
        ICP = self.env["ir.config_parameter"].sudo()
        value = (self.jwt_secret or "").strip()
        if value and value != "********":
            ICP.set_param(JWT_SECRET_PARAM, value)
        elif value == "":
            ICP.set_param(JWT_SECRET_PARAM, "")
        vapid = (self.vapid_private_key or "").strip()
        if vapid and vapid != "********":
            ICP.set_param(VAPID_PRIVATE_KEY_PARAM, vapid)
        elif vapid == "":
            ICP.set_param(VAPID_PRIVATE_KEY_PARAM, "")
