# Copyright 2025
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl.html).

"""
Web Push helper for waitlist promotion notifications.
Uses pywebpush with VAPID private key from config.
"""

import json
import logging

_logger = logging.getLogger(__name__)

VAPID_PRIVATE_KEY_PARAM = "studio_booking.vapid_private_key"


def _get_vapid_private_key(env):
    """Return VAPID private key from config. None if not set."""
    return (
        env["ir.config_parameter"]
        .sudo()
        .get_param(VAPID_PRIVATE_KEY_PARAM)
        or ""
    ).strip() or None


def send_promotion_push(env, member_profile_id, session, class_name=None, date_str=None):
    """
    Send Web Push to all stored subscriptions for the member when promoted from waitlist.
    Uses session data for class name and date.
    Removes subscriptions that fail (e.g. expired).
    """
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        _logger.warning(
            "pywebpush not installed. Run: pip install pywebpush. Skipping push notification."
        )
        return
    vapid_key = _get_vapid_private_key(env)
    if not vapid_key:
        _logger.debug("VAPID private key not configured. Skipping push notification.")
        return
    PushSub = env["studio.push_subscription"].sudo()
    subs = PushSub.search(
        [
            ("member_profile_id", "=", member_profile_id),
            ("active", "=", True),
        ]
    )
    if not subs:
        _logger.debug("No push subscriptions for member %s", member_profile_id)
        return
    class_name = class_name or (session.template_id.name if session else "Class")
    date_str = date_str or ""
    if session and session.session_start:
        from . import timezone as tz_utils

        date_str = tz_utils.utc_to_studio_local_str(
            session.session_start, "%Y-%m-%d"
        )
    payload = {
        "title": "You've been promoted!",
        "body": f"A spot opened up — you're now booked for {class_name} on {date_str}.",
        "url": f"/classes/{session.id}" if session else "/classes",
        "tag": "promotion",
    }
    data = json.dumps(payload)
    to_unlink = env["studio.push_subscription"].sudo().browse()
    for sub in subs:
        try:
            subscription_info = {
                "endpoint": sub.endpoint,
                "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
            }
            webpush(
                subscription_info=subscription_info,
                data=data,
                vapid_private_key=vapid_key,
                vapid_claims={"sub": "mailto:studio@example.com"},
            )
            _logger.info(
                "Sent promotion push to member %s subscription %s",
                member_profile_id,
                sub.id,
            )
        except Exception as e:
            _logger.warning(
                "Push failed for subscription %s (member %s): %s. Removing.",
                sub.id,
                member_profile_id,
                e,
            )
            to_unlink |= sub
    if to_unlink:
        to_unlink.unlink()
