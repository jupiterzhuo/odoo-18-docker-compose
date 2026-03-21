# Copyright 2025
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl.html).

"""
Class booking and cancellation API endpoints.
Thin controller: delegates to BookingService for business logic.
"""

import json
import logging

from odoo import http
from odoo.exceptions import AccessError, ValidationError
from odoo.http import Response, request

from odoo.addons.studio_booking.utils import jwt_helper
from odoo.addons.studio_booking.services.booking_service import BookingService

_logger = logging.getLogger(__name__)


class ClassBookingController(http.Controller):
    """REST endpoints for class booking and cancellation."""

    @staticmethod
    def _json_response(data, status=200):
        return Response(
            json.dumps(data, default=str),
            content_type="application/json",
            status=status,
        )

    @staticmethod
    def _get_auth_from_request():
        """
        Resolve auth: Bearer JWT first, then session.
        Returns (member_profile_id, uid, tenant_id).
        """
        auth_header = (request.httprequest.headers.get("Authorization") or "").strip()
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()
            payload = jwt_helper.decode_token(
                request.env, token, expected_type=jwt_helper.TOKEN_TYPE_ACCESS
            )
            if payload and "uid" in payload:
                return (
                    payload.get("member_profile_id"),
                    payload["uid"],
                    payload.get("tenant_id"),
                )
        if request.session.uid:
            return (None, request.session.uid, None)
        return (None, None, None)

    def _resolve_member_for_api(self, member_profile_id=None):
        """
        Resolve member for API: from JWT or from body with admin access check.
        Returns (member, source) where source is 'member_app' or 'admin'.
        """
        jwt_member_id, uid, _ = self._get_auth_from_request()
        if not uid:
            return None, None

        MemberProfile = request.env["studio.member_profile"].sudo()
        if member_profile_id:
            member = MemberProfile.browse(member_profile_id)
            if not member.exists():
                return None, None
            if jwt_member_id and member.id != jwt_member_id:
                # JWT member trying to book for another - reject
                return None, None
            if jwt_member_id:
                return member, "member_app"
            # Admin/staff: must have tenant access
            request.env.user.ensure_studio_tenant_allowed(member.tenant_id)
            return member, "admin"
        if jwt_member_id:
            member = MemberProfile.browse(jwt_member_id)
            if member.exists() and member.user_id.id == uid and member.active_subscription_id:
                return member, "member_app"
            member = MemberProfile.search(
                [("user_id", "=", uid), ("active_subscription_id", "!=", False)],
                limit=1,
            )
            return member if member else None, "member_app"
        return None, None

    # ----- POST /api/class/booking ------------------------------------------

    @http.route(
        "/api/class/booking",
        type="http",
        auth="none",
        methods=["POST", "OPTIONS"],
        csrf=False,
        cors="*",
    )
    def class_booking(self, **kw):
        """
        Book a class for a member.
        Body: { "session_id": int, "member_profile_id": int? }
        - If member_profile_id omitted and JWT present: use member from token (member app).
        - If member_profile_id provided: admin booking (requires tenant access).
        """
        member_profile_id, uid, _ = self._get_auth_from_request()
        if not uid:
            return self._json_response(
                {"success": False, "message": "Authentication required"}, 401
            )
        try:
            payload = json.loads(request.httprequest.data or b"{}")
        except (ValueError, TypeError):
            return self._json_response(
                {"success": False, "message": "Invalid request body"}, 400
            )
        session_id = payload.get("session_id")
        body_member_id = payload.get("member_profile_id")
        member, source = self._resolve_member_for_api(body_member_id or member_profile_id)
        if not member:
            return self._json_response(
                {
                    "success": False,
                    "message": "Member profile not found",
                    "reason": "no_member_with_active_subscription",
                },
                404,
            )
        if not session_id:
            return self._json_response(
                {"success": False, "message": "session_id is required"}, 400
            )
        try:
            session_id = int(session_id)
        except (TypeError, ValueError):
            return self._json_response(
                {"success": False, "message": "session_id must be an integer"}, 400
            )
        source_label = "member_app" if source == "member_app" else "api"
        env = request.env
        if uid and uid != request.env.uid:
            env = request.env(user=uid)
        try:
            service = BookingService(env)
            booking, status = service.book(
                session_id=session_id,
                member_profile_id=member.id,
                source=source_label,
            )
        except ValidationError as e:
            return self._json_response(
                {"success": False, "message": str(e)}, 400
            )
        except AccessError as e:
            return self._json_response(
                {"success": False, "message": str(e)}, 403
            )
        except Exception as e:
            _logger.exception("Booking API error: %s", e)
            return self._json_response(
                {"success": False, "message": str(e)}, 500
            )
        return self._json_response({
            "success": True,
            "message": "Booked" if status == "booked" else "Added to waitlist",
            "booking": {
                "id": booking.id,
                "session_id": booking.session_id.id,
                "member_profile_id": booking.member_profile_id.id,
                "status": status,
                "booked_at": str(booking.booked_at) if booking.booked_at else None,
            },
        })

    # ----- POST /api/class/cancel -------------------------------------------

    @http.route(
        "/api/class/cancel",
        type="http",
        auth="none",
        methods=["POST", "OPTIONS"],
        csrf=False,
        cors="*",
    )
    def class_cancel(self, **kw):
        """
        Cancel a booking.
        Body: { "booking_id": int } OR { "session_id": int, "member_profile_id": int? }
        - If member_profile_id omitted and JWT present: cancel member's booking for session (member app).
        - If booking_id: cancel by ID (admin or member if owns it).
        """
        member_profile_id, uid, _ = self._get_auth_from_request()
        if not uid:
            return self._json_response(
                {"success": False, "message": "Authentication required"}, 401
            )
        try:
            payload = json.loads(request.httprequest.data or b"{}")
        except (ValueError, TypeError):
            return self._json_response(
                {"success": False, "message": "Invalid request body"}, 400
            )
        booking_id = payload.get("booking_id")
        session_id = payload.get("session_id")
        body_member_id = payload.get("member_profile_id")
        member, source = self._resolve_member_for_api(body_member_id or member_profile_id)
        source_label = "member_app" if source == "member_app" else "api"
        # For cancel by session_id, member is required (member_app uses JWT member)
        if session_id and not member:
            return self._json_response(
                {
                    "success": False,
                    "message": "Member profile not found",
                    "reason": "no_member_with_active_subscription",
                },
                404,
            )
        # For cancel by booking_id as member_app, member required for ownership check
        if booking_id and source == "member_app" and not member:
            return self._json_response(
                {
                    "success": False,
                    "message": "Member profile not found",
                    "reason": "no_member_with_active_subscription",
                },
                404,
            )
        env = request.env
        if uid and uid != request.env.uid:
            env = request.env(user=uid)
        try:
            service = BookingService(env)
            if booking_id:
                try:
                    booking_id = int(booking_id)
                except (TypeError, ValueError):
                    return self._json_response(
                        {"success": False, "message": "booking_id must be an integer"}, 400
                    )
                booking, promoted = service.cancel(
                    booking_id=booking_id,
                    source=source_label,
                )
                if source == "member_app" and (not member or booking.member_profile_id.id != member.id):
                    return self._json_response(
                        {
                            "success": False,
                            "message": "Booking not found or access denied",
                            "reason": "booking_not_owned_by_member",
                        },
                        403,
                    )
            elif session_id:
                try:
                    session_id = int(session_id)
                except (TypeError, ValueError):
                    return self._json_response(
                        {"success": False, "message": "session_id must be an integer"}, 400
                    )
                booking, promoted = service.cancel(
                    session_id=session_id,
                    member_profile_id=member.id,
                    source=source_label,
                )
            else:
                return self._json_response(
                    {
                        "success": False,
                        "message": "Provide booking_id or session_id (session_id requires member auth)",
                    },
                    400,
                )
        except ValidationError as e:
            return self._json_response(
                {"success": False, "message": str(e)}, 400
            )
        except AccessError as e:
            return self._json_response(
                {"success": False, "message": str(e)}, 403
            )
        except Exception as e:
            _logger.exception("Cancel API error: %s", e)
            return self._json_response(
                {"success": False, "message": str(e)}, 500
            )
        return self._json_response({
            "success": True,
            "message": "Booking cancelled",
            "booking": {
                "id": booking.id,
                "session_id": booking.session_id.id,
                "member_profile_id": booking.member_profile_id.id,
                "status": "cancelled",
                "canceled_at": str(booking.canceled_at) if booking.canceled_at else None,
            },
            "promoted": {
                "id": promoted.id,
                "member_profile_id": promoted.member_profile_id.id,
            } if promoted else None
        })
