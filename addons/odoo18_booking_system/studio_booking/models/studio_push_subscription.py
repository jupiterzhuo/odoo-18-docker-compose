# Copyright 2025
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl.html).

from odoo import _, api, fields, models


class StudioPushSubscription(models.Model):
    _name = "studio.push_subscription"
    _description = "Web Push subscription for member notifications"

    member_profile_id = fields.Many2one(
        "studio.member_profile",
        required=True,
        ondelete="cascade",
        index=True,
    )
    endpoint = fields.Text(required=True, index=True)
    p256dh = fields.Text(required=True, string="P-256 DH Key")
    auth = fields.Text(required=True, string="Auth Secret")
    expiration_time = fields.Datetime(
        help="Optional expiration from subscription.expirationTime (ms since epoch)."
    )
    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            "studio_push_subscription_endpoint_uniq",
            "unique(endpoint)",
            "This subscription endpoint is already registered.",
        )
    ]

    @api.model
    def upsert_from_payload(self, member_profile_id, subscription_payload):
        """
        Create or update a push subscription from the Web Push API payload.
        subscription_payload: dict with endpoint, keys.p256dh, keys.auth, expirationTime.
        Returns the subscription record.
        """
        endpoint = (subscription_payload.get("endpoint") or "").strip()
        keys = subscription_payload.get("keys") or {}
        p256dh = (keys.get("p256dh") or "").strip()
        auth = (keys.get("auth") or "").strip()
        if not endpoint or not p256dh or not auth:
            return self.env["studio.push_subscription"]
        exp = subscription_payload.get("expirationTime")
        expiration_time = False
        if exp is not None:
            try:
                exp_ms = int(exp)
                if exp_ms > 0:
                    from datetime import datetime

                    expiration_time = datetime.utcfromtimestamp(exp_ms / 1000.0)
            except (TypeError, ValueError, OSError):
                pass
        existing = self.search([("endpoint", "=", endpoint)], limit=1)
        vals = {
            "member_profile_id": member_profile_id,
            "endpoint": endpoint,
            "p256dh": p256dh,
            "auth": auth,
            "expiration_time": expiration_time or False,
            "active": True,
        }
        if existing:
            existing.write(vals)
            return existing
        return self.create(vals)
