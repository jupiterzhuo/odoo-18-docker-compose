# Copyright 2025
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl.html).

import json
import logging
from datetime import datetime, timedelta

from odoo import http

from odoo.addons.studio_booking.utils import timezone as tz_utils
from odoo.addons.studio_booking.utils import jwt_helper
from odoo.addons.studio_booking.services.booking_service import BookingService
from odoo.exceptions import AccessDenied
from odoo.http import Response, request

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Auth: session cookie + JWT (Bearer)
#
# Login accepts email + password. Tenant is supplied by the app (not the member):
#   - Body: tenant_code or tenant_id
#   - Header: X-Tenant-Code or X-Tenant-Id (for app-configured tenant, member never types it)
# Returns JWT (access_token) when studio_booking.jwt_secret is set.
# JWT includes member_profile_id and tenant_id for multi-tenant members.
# Clients use "Authorization: Bearer <token>" for /api/member/profile and /me.
# ---------------------------------------------------------------------------


class MemberAuthController(http.Controller):
    """JSON REST endpoints consumed by the external member (mobile) app."""

    @staticmethod
    def _json_response(data, status=200):
        return Response(
            json.dumps(data, default=str),
            content_type="application/json",
            status=status,
        )

    # ----- GET /api/tenant ------------------------------------------------
    # Tenant detail for login page binding (no auth required).

    @http.route(
        "/api/tenant",
        type="http",
        auth="none",
        methods=["GET", "OPTIONS"],
        csrf=False,
        cors="*",
    )
    def tenant_detail(self, **kw):
        tenant_code = (
            request.httprequest.headers.get("X-Tenant-Code")
            or request.params.get("tenant_code")
        )
        tenant_code = (tenant_code or "").strip()
        tenant_id = request.httprequest.headers.get("X-Tenant-Id")
        if tenant_id is None:
            tenant_id = request.params.get("tenant_id")
        if tenant_id is not None:
            try:
                tenant_id = int(tenant_id)
            except (TypeError, ValueError):
                tenant_id = None
        if not tenant_code:
            return self._json_response(
                {"success": False, "message": "tenant_code is required (header X-Tenant-Code or query tenant_code)"}, 400
            )
        Tenant = request.env["studio.tenant"].sudo()
        tenant = Tenant._resolve_from_code_or_id(
            code=tenant_code, tenant_id=tenant_id
        )
        if not tenant:
            return self._json_response(
                {"success": False, "message": "Tenant not found"}, 404
            )
        base_url = (
            request.env.company.get_base_url()
            if request.env.company
            else request.env["ir.config_parameter"].sudo().get_param("web.base.url") or ""
        )
        base_url = (base_url or "").rstrip("/")
        logo_url = f"{base_url}/web/image/studio.tenant/{tenant.id}/logo" if base_url and tenant.logo else None
        return self._json_response({
            "success": True,
            "tenant": {
                "id": tenant.id,
                "name": tenant.name or "",
                "code": tenant.code or "",
                "logo_url": logo_url,
                "login_url": tenant.login_url or "",
                "website_url": tenant.website_url or "",
                "email": tenant.email or "",
                "phone": tenant.phone or "",
            },
        })

    # ----- POST /api/member/auth/login ------------------------------------

    @http.route(
        "/api/member/auth/login",
        type="http",
        auth="none",
        methods=["POST", "OPTIONS"],
        csrf=False,
        cors="*",
    )
    def member_login(self, **kw):
        try:
            payload = json.loads(request.httprequest.data or b"{}")
        except (ValueError, TypeError):
            return self._json_response(
                {"success": False, "message": "Invalid request body"}, 400
            )

        email = (payload.get("email") or "").strip()
        password = payload.get("password") or ""
        tenant_code = payload.get("tenant_code") or request.httprequest.headers.get("X-Tenant-Code")
        tenant_id = payload.get("tenant_id")
        if tenant_id is None:
            header_tenant_id = request.httprequest.headers.get("X-Tenant-Id")
            if header_tenant_id is not None:
                try:
                    tenant_id = int(header_tenant_id)
                except (TypeError, ValueError):
                    tenant_id = None

        if not email or not password:
            return self._json_response(
                {"success": False, "message": "Email and password are required"}, 400
            )
        if not tenant_code and not tenant_id:
            return self._json_response(
                {"success": False, "message": "Tenant identifier is required"}, 400
            )

        db = request.db
        if not db:
            return self._json_response(
                {"success": False, "message": "Service unavailable"}, 503
            )

        Tenant = request.env["studio.tenant"].sudo()
        tenant = Tenant._resolve_from_code_or_id(
            code=tenant_code, tenant_id=tenant_id
        )
        if not tenant:
            _logger.info("Member login: tenant not found for identifier %s", tenant_code or tenant_id)
            return self._json_response(
                {"success": False, "message": "Invalid credentials"}, 401
            )

        MemberProfile = request.env["studio.member_profile"].sudo()
        member = MemberProfile._get_member_by_tenant_and_email(tenant, email)
        if not member or not member.user_id:
            _logger.info("Member login: no active member/user for %s in tenant %s", email, tenant.id)
            return self._json_response(
                {"success": False, "message": "Invalid credentials"}, 401
            )

        login = member._get_internal_member_login()
        try:
            credential = {"login": login, "password": password, "type": "password"}
            request.session.authenticate(db, credential)
            uid = request.session.uid
        except AccessDenied:
            uid = None

        if not uid:
            return self._json_response(
                {"success": False, "message": "Invalid credentials"}, 401
            )

        response_data = {
            "success": True,
            "message": "Login successful",
            "member": member._serialize_for_api(),
            "tenant": {
                "id": tenant.id,
                "name": tenant.name,
                "website_url": tenant.website_url or "",
                "login_url": tenant.login_url or "",
            },
            "session": {
                "uid": uid,
            },
        }
        # Issue JWT when secret is configured (for mobile / stateless clients)
        access_token, expires_in = jwt_helper.encode_token(
            request.env, uid, member.id, tenant.id
        )
        if access_token:
            response_data["access_token"] = access_token
            response_data["expires_in"] = expires_in
            response_data["token_type"] = "Bearer"

        # Refresh token for "remember me" - long-lived, used to get new access tokens
        remember_me = payload.get("remember_me") in (True, "true", "1", 1)
        if remember_me:
            refresh_token, refresh_expires_in = jwt_helper.encode_refresh_token(
                request.env, uid, member.id, tenant.id
            )
            if refresh_token:
                response_data["refresh_token"] = refresh_token
                response_data["refresh_expires_in"] = refresh_expires_in

        return self._json_response(response_data)

    # ----- POST /api/member/auth/forgot_password --------------------------
    # User enters email; system sends temporary password. Tenant from app (header/body).

    @http.route(
        ["/api/member/auth/forgot_password", "/api/member/auth/forgot-password"],
        type="http",
        auth="none",
        methods=["POST", "OPTIONS"],
        csrf=False,
        cors="*",
    )
    def member_forgot_password(self, **kw):
        try:
            payload = json.loads(request.httprequest.data or b"{}")
        except (ValueError, TypeError):
            return self._json_response(
                {"success": False, "message": "Invalid request body"}, 400
            )
        email = (payload.get("email") or "").strip()
        tenant_code = payload.get("tenant_code") or request.httprequest.headers.get("X-Tenant-Code")
        tenant_id = payload.get("tenant_id")
        if tenant_id is None:
            header_tenant_id = request.httprequest.headers.get("X-Tenant-Id")
            if header_tenant_id is not None:
                try:
                    tenant_id = int(header_tenant_id)
                except (TypeError, ValueError):
                    tenant_id = None

        if not email:
            return self._json_response(
                {"success": False, "message": "Email is required"}, 400
            )
        if not tenant_code and not tenant_id:
            return self._json_response(
                {"success": False, "message": "Tenant identifier is required"}, 400
            )

        db = request.db
        if not db:
            return self._json_response(
                {"success": False, "message": "Service unavailable"}, 503
            )

        Tenant = request.env["studio.tenant"].sudo()
        tenant = Tenant._resolve_from_code_or_id(
            code=tenant_code, tenant_id=tenant_id
        )
        if not tenant:
            return self._json_response(
                {"success": False, "message": "Invalid tenant"}, 400
            )

        MemberProfile = request.env["studio.member_profile"].sudo()
        member = MemberProfile._get_member_by_tenant_and_email(tenant, email)
        if member and member.user_id:
            try:
                member.sudo().action_reset_password_email()
            except Exception as e:
                _logger.warning(
                    "Forgot password failed for %s in tenant %s: %s",
                    email,
                    tenant.id,
                    e,
                )

        return self._json_response({
            "success": True,
            "message": "If that email is registered, a temporary password has been sent. Please check your inbox and log in to change your password.",
        })

    # ----- POST /api/member/auth/refresh ----------------------------------
    # Exchange refresh_token for new access_token (remember me flow).

    @http.route(
        "/api/member/auth/refresh",
        type="http",
        auth="none",
        methods=["POST", "OPTIONS"],
        csrf=False,
        cors="*",
    )
    def member_refresh(self, **kw):
        try:
            body = json.loads(request.httprequest.data or b"{}")
        except (ValueError, TypeError):
            return self._json_response(
                {"success": False, "message": "Invalid request body"}, 400
            )
        refresh_token = (body.get("refresh_token") or "").strip()
        if not refresh_token:
            return self._json_response(
                {"success": False, "message": "refresh_token is required"}, 400
            )
        payload = jwt_helper.decode_token(
            request.env, refresh_token, expected_type=jwt_helper.TOKEN_TYPE_REFRESH
        )
        if not payload or "uid" not in payload:
            return self._json_response(
                {"success": False, "message": "Invalid or expired refresh token"}, 401
            )
        uid = payload["uid"]
        member_profile_id = payload.get("member_profile_id")
        tenant_id = payload.get("tenant_id")
        if not member_profile_id or not tenant_id:
            return self._json_response(
                {"success": False, "message": "Invalid refresh token"}, 401
            )
        MemberProfile = request.env["studio.member_profile"].sudo()
        member = MemberProfile.browse(member_profile_id)
        if not member.exists() or member.user_id.id != uid or not member.active_subscription_id:
            return self._json_response(
                {"success": False, "message": "Member no longer valid"}, 401
            )
        access_token, expires_in = jwt_helper.encode_token(
            request.env, uid, member.id, tenant_id
        )
        if not access_token:
            return self._json_response(
                {"success": False, "message": "Token issuance failed"}, 500
            )
        return self._json_response({
            "success": True,
            "access_token": access_token,
            "expires_in": expires_in,
            "token_type": "Bearer",
        })

    # ----- POST /api/member/auth/change-password ---------------------------
    # Change password. Requires Bearer token + current_password + new_password.

    @http.route(
        "/api/member/auth/change-password",
        type="http",
        auth="none",
        methods=["POST", "OPTIONS"],
        csrf=False,
        cors="*",
    )
    def member_change_password(self, **kw):
        member_profile_id, uid, _tenant_id = self._get_auth_from_request()
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
        current_password = payload.get("current_password") or ""
        new_password = payload.get("new_password") or ""
        if not current_password:
            return self._json_response(
                {"success": False, "message": "current_password is required"}, 400
            )
        if not new_password:
            return self._json_response(
                {"success": False, "message": "new_password is required"}, 400
            )
        MemberProfile = request.env["studio.member_profile"].sudo()
        valid, error_msg = MemberProfile._validate_password_rules(new_password)
        if not valid:
            return self._json_response(
                {"success": False, "message": error_msg}, 400
            )
        if member_profile_id:
            member = MemberProfile.browse(member_profile_id)
            if not member.exists() or member.user_id.id != uid or not member.active_subscription_id:
                return self._json_response(
                    {"success": False, "message": "Member profile not found"}, 404
                )
        else:
            member = MemberProfile.search(
                [("user_id", "=", uid), ("active_subscription_id", "!=", False)],
                limit=1,
            )
            if not member:
                return self._json_response(
                    {"success": False, "message": "Member profile not found"}, 404
                )
        login = member._get_internal_member_login()
        try:
            credential = {"login": login, "password": current_password, "type": "password"}
            request.session.authenticate(request.db, credential)
        except AccessDenied:
            return self._json_response(
                {"success": False, "message": "Current password is incorrect"}, 401
            )
        if request.session.uid != uid:
            return self._json_response(
                {"success": False, "message": "Current password is incorrect"}, 401
            )
        member.write({"app_password": new_password})
        try:
            member.sudo().action_send_password_changed_email()
        except Exception as e:
            _logger.warning(
                "Send password changed email failed for member %s (%s): %s",
                member.id,
                member.email,
                e,
            )
        return self._json_response({
            "success": True,
            "message": "Password changed successfully",
        })

    # ----- GET /api/member/profile -----------------------------------------
    # View full member profile (after login). Accepts Bearer JWT or session.

    @http.route(
        "/api/member/profile",
        type="http",
        auth="none",
        methods=["GET", "OPTIONS"],
        csrf=False,
        cors="*",
    )
    def member_profile(self, **kw):
        member_profile_id, uid, _tenant_id = self._get_auth_from_request()
        if not uid:
            return self._json_response(
                {"success": False, "message": "Authentication required"}, 401
            )
        MemberProfile = request.env["studio.member_profile"].sudo()
        if member_profile_id:
            member = MemberProfile.browse(member_profile_id)
            if not member.exists() or member.user_id.id != uid or not member.active_subscription_id:
                return self._json_response(
                    {"success": False, "message": "Member profile not found"}, 404
                )
        else:
            member = MemberProfile.search(
                [("user_id", "=", uid), ("active_subscription_id", "!=", False)],
                limit=1,
            )
            if not member:
                return self._json_response(
                    {"success": False, "message": "Member profile not found"}, 404
                )
        return self._json_response({
            "success": True,
            "profile": member._serialize_profile_for_api(),
        })

    # ----- POST /api/member/push-subscribe ----------------------------------
    # Store Web Push subscription for waitlist promotion notifications.

    @http.route(
        "/api/member/push-subscribe",
        type="http",
        auth="none",
        methods=["POST", "OPTIONS"],
        csrf=False,
        cors="*",
    )
    def member_push_subscribe(self, **kw):
        member_profile_id, uid, _tenant_id = self._get_auth_from_request()
        if not uid:
            return self._json_response(
                {"success": False, "message": "Authentication required"}, 401
            )
        member = self._resolve_member(uid, member_profile_id)
        if not member:
            return self._json_response(
                {"success": False, "message": "Member profile not found"}, 404
            )
        try:
            payload = json.loads(request.httprequest.data or b"{}")
        except (ValueError, TypeError):
            return self._json_response(
                {"success": False, "message": "Invalid request body"}, 400
            )
        subscription = payload.get("subscription")
        if not subscription or not isinstance(subscription, dict):
            return self._json_response(
                {"success": False, "message": "subscription object is required"}, 400
            )
        keys = subscription.get("keys") or {}
        if not all([
            subscription.get("endpoint"),
            keys.get("p256dh"),
            keys.get("auth"),
        ]):
            return self._json_response(
                {"success": False, "message": "subscription must have endpoint and keys.p256dh, keys.auth"}, 400
            )
        PushSub = request.env["studio.push_subscription"].sudo()
        PushSub.upsert_from_payload(member.id, subscription)
        return self._json_response({
            "success": True,
            "message": "Push notifications enabled",
        })

    # ----- GET /api/member/eligible-branches -------------------------------
    # Branches the member can attend based on active subscription and plan.
    # Prerequisite: member must have active subscription; plan must be active.

    @http.route(
        "/api/member/eligible-branches",
        type="http",
        auth="none",
        methods=["GET", "OPTIONS"],
        csrf=False,
        cors="*",
    )
    def member_eligible_branches(self, **kw):
        member_profile_id, uid, _tenant_id = self._get_auth_from_request()
        if not uid:
            return self._json_response(
                {"success": False, "message": "Authentication required"}, 401
            )
        MemberProfile = request.env["studio.member_profile"].sudo()
        if member_profile_id:
            member = MemberProfile.browse(member_profile_id)
            if not member.exists():
                return self._json_response(
                    {
                        "success": False,
                        "message": "Member profile not found",
                        "reason": "member_not_found",
                    },
                    404,
                )
            if member.user_id.id != uid:
                return self._json_response(
                    {
                        "success": False,
                        "message": "Member profile not found",
                        "reason": "user_mismatch",
                    },
                    404,
                )
            if not member.active_subscription_id:
                return self._json_response(
                    {
                        "success": False,
                        "message": "Active subscription required",
                        "reason": "no_active_subscription",
                    },
                    404,
                )
        else:
            member = MemberProfile.search(
                [("user_id", "=", uid), ("active_subscription_id", "!=", False)],
                limit=1,
            )
            if not member:
                return self._json_response(
                    {
                        "success": False,
                        "message": "Member profile not found",
                        "reason": "no_member_with_active_subscription",
                    },
                    404,
                )
        branches = member._get_eligible_branches()
        return self._json_response({
            "success": True,
            "branches": [b._serialize_for_api() for b in branches],
        })

    # ----- GET /api/member/sessions/upcoming -------------------------------
    # All upcoming sessions in allowed branches (no branch/date filter).
    # For Frontend Homepage.

    @http.route(
        "/api/member/sessions/upcoming",
        type="http",
        auth="none",
        methods=["GET", "OPTIONS"],
        csrf=False,
        cors="*",
    )
    def member_sessions_upcoming(self, **kw):
        member_profile_id, uid, _tenant_id = self._get_auth_from_request()
        if not uid:
            return self._json_response(
                {"success": False, "message": "Authentication required"}, 401
            )
        member = self._resolve_member(uid, member_profile_id)
        if not member:
            return self._json_response(
                {"success": False, "message": "Member profile not found"}, 404
            )
        eligible_branches = member._get_eligible_branches()
        if not eligible_branches:
            return self._json_response({
                "success": True,
                "sessions": [],
                "count": 0,
                "limit": 3,
                "offset": 0,
            })
        limit_param = request.params.get("limit")
        offset_param = request.params.get("offset")
        limit = 3
        offset = 0
        if limit_param is not None:
            try:
                limit = int(limit_param)
                if limit < 1:
                    limit = 3
                elif limit > 50:
                    limit = 50
            except (TypeError, ValueError):
                pass
        if offset_param is not None:
            try:
                offset = int(offset_param)
                if offset < 0:
                    offset = 0
            except (TypeError, ValueError):
                pass
        now = tz_utils.utc_now()
        today = tz_utils.studio_today()
        end_date = today + timedelta(days=6)
        end_utc, _ = tz_utils.date_to_utc_range(end_date + timedelta(days=1))
        domain = [
            ("tenant_id", "=", member.tenant_id.id),
            ("branch_id", "in", eligible_branches.ids),
            ("state", "=", "scheduled"),
            ("session_start", ">=", now),
            ("session_start", "<", end_utc),
        ]
        Session = request.env["studio.class_session"].sudo()
        sessions = Session.search(
            domain,
            order="session_start asc",
        )
        service = BookingService(request.env)
        showable = [
            s for s in sessions
            if service.is_session_bookable_or_member_booked(s, member.id)
        ]
        total = len(showable)
        page = showable[offset : offset + limit]
        return self._json_response({
            "success": True,
            "sessions": [
                s._serialize_for_api(member_profile_id=member.id) for s in page
            ],
            "count": total,
            "limit": limit,
            "offset": offset,
        })

    # ----- GET /api/member/sessions/<id> ----------------------------------
    # Session detail for class/session detail screen.

    @http.route(
        "/api/member/sessions/<int:session_id>",
        type="http",
        auth="none",
        methods=["GET", "OPTIONS"],
        csrf=False,
        cors="*",
    )
    def member_session_detail(self, session_id, **kw):
        member_profile_id, uid, _tenant_id = self._get_auth_from_request()
        if not uid:
            return self._json_response(
                {"success": False, "message": "Authentication required"}, 401
            )
        member = self._resolve_member(uid, member_profile_id)
        if not member:
            return self._json_response(
                {"success": False, "message": "Member profile not found"}, 404
            )
        Session = request.env["studio.class_session"].sudo()
        session = Session.browse(session_id)
        if not session.exists():
            return self._json_response(
                {"success": False, "message": "Session not found"}, 404
            )
        if session.tenant_id != member.tenant_id:
            return self._json_response(
                {"success": False, "message": "Session not found"}, 404
            )
        if session.state == "cancelled":
            return self._json_response(
                {"success": False, "message": "Session is cancelled"}, 404
            )
        return self._json_response({
            "success": True,
            "session": session._serialize_detail_for_api(
                member_profile_id=member.id
            ),
        })

    # ----- GET /api/member/sessions ----------------------------------------
    # List class sessions by branch and date (Classes screen).

    @http.route(
        "/api/member/sessions",
        type="http",
        auth="none",
        methods=["GET", "OPTIONS"],
        csrf=False,
        cors="*",
    )
    def member_sessions_list(self, **kw):
        member_profile_id, uid, _tenant_id = self._get_auth_from_request()
        if not uid:
            return self._json_response(
                {"success": False, "message": "Authentication required"}, 401
            )
        member = self._resolve_member(uid, member_profile_id)
        if not member:
            return self._json_response(
                {"success": False, "message": "Member profile not found"}, 404
            )
        branch_id = request.params.get("branch_id")
        date_str = request.params.get("date")
        if not branch_id:
            return self._json_response(
                {"success": False, "message": "branch_id is required"}, 400
            )
        if not date_str:
            return self._json_response(
                {"success": False, "message": "date is required (YYYY-MM-DD)"}, 400
            )
        try:
            branch_id = int(branch_id)
        except (TypeError, ValueError):
            return self._json_response(
                {"success": False, "message": "branch_id must be an integer"}, 400
            )
        try:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return self._json_response(
                {"success": False, "message": "date must be YYYY-MM-DD"}, 400
            )
        Session = request.env["studio.class_session"].sudo()
        # Date is in GMT+7; convert to UTC range for DB query
        day_start_utc, day_end_utc = tz_utils.date_to_utc_range(target_date)
        domain = [
            ("tenant_id", "=", member.tenant_id.id),
            ("branch_id", "=", branch_id),
            ("state", "=", "scheduled"),
            ("session_start", ">=", day_start_utc),
            ("session_start", "<", day_end_utc),
        ]
        sessions = Session.search(domain, order="session_start asc")
        service = BookingService(request.env)
        showable = [
            s for s in sessions
            if service.is_session_bookable_or_member_booked(s, member.id)
        ]
        return self._json_response({
            "success": True,
            "sessions": [
                s._serialize_for_api(member_profile_id=member.id) for s in showable
            ],
            "count": len(showable),
        })

    # ----- GET /api/member/bookings/count ----------------------------------
    # Count of future bookings for badge (My Bookings).

    @http.route(
        "/api/member/bookings/count",
        type="http",
        auth="none",
        methods=["GET", "OPTIONS"],
        csrf=False,
        cors="*",
    )
    def member_bookings_count(self, **kw):
        member_profile_id, uid, _tenant_id = self._get_auth_from_request()
        if not uid:
            return self._json_response(
                {"success": False, "message": "Authentication required"}, 401
            )
        member = self._resolve_member(uid, member_profile_id)
        if not member:
            return self._json_response(
                {"success": False, "message": "Member profile not found"}, 404
            )
        now = tz_utils.utc_now()
        domain = [
            ("member_profile_id", "=", member.id),
            ("booking_status", "in", ("booked", "promoted", "waitlisted")),
            ("session_id.session_start", ">=", now),
            ("session_id.state", "=", "scheduled"),
        ]
        count = request.env["studio.booking"].sudo().search_count(domain)
        return self._json_response({"success": True, "count": count})

    # ----- GET /api/member/bookings ----------------------------------------
    # List future bookings for My Bookings page.

    @http.route(
        "/api/member/bookings",
        type="http",
        auth="none",
        methods=["GET", "OPTIONS"],
        csrf=False,
        cors="*",
    )
    def member_bookings_list(self, **kw):
        member_profile_id, uid, _tenant_id = self._get_auth_from_request()
        if not uid:
            return self._json_response(
                {"success": False, "message": "Authentication required"}, 401
            )
        member = self._resolve_member(uid, member_profile_id)
        if not member:
            return self._json_response(
                {"success": False, "message": "Member profile not found"}, 404
            )
        future_only = request.params.get("future_only", "true")
        future_only = str(future_only).lower() not in ("false", "0", "no")
        limit_param = request.params.get("limit")
        offset_param = request.params.get("offset")
        limit = None
        offset = 0
        if limit_param is not None:
            try:
                limit = int(limit_param)
                if limit < 1:
                    limit = None
            except (TypeError, ValueError):
                pass
        if offset_param is not None:
            try:
                offset = int(offset_param)
                if offset < 0:
                    offset = 0
            except (TypeError, ValueError):
                pass
        now = tz_utils.utc_now()
        domain = [
            ("member_profile_id", "=", member.id),
            ("booking_status", "in", ("booked", "promoted", "waitlisted")),
            ("session_id.state", "=", "scheduled"),
        ]
        if future_only:
            domain.append(("session_id.session_start", ">=", now))
        Booking = request.env["studio.booking"].sudo()
        bookings = Booking.search(
            domain,
            order="session_id asc",
            limit=limit,
            offset=offset,
        )
        count = Booking.search_count(domain)
        result = []
        for b in bookings:
            session_data = b.session_id._serialize_for_api(
                member_profile_id=member.id
            ) if b.session_id else {}
            result.append({
                "id": b.id,
                "session_id": b.session_id.id if b.session_id else None,
                "booking_status": b.booking_status,
                "session": session_data,
            })
        return self._json_response({
            "success": True,
            "bookings": result,
            "count": count,
        })

    @staticmethod
    def _resolve_member(uid, member_profile_id):
        """Resolve member from uid and optional member_profile_id."""
        MemberProfile = request.env["studio.member_profile"].sudo()
        if member_profile_id:
            member = MemberProfile.browse(member_profile_id)
            if not member.exists() or member.user_id.id != uid:
                return None
            if not member.active_subscription_id:
                return None
            return member
        member = MemberProfile.search(
            [("user_id", "=", uid), ("active_subscription_id", "!=", False)],
            limit=1,
        )
        return member if member else None

    # ----- GET/POST /api/member/auth/me -----------------------------------
    # Accepts session cookie or "Authorization: Bearer <access_token>"

    @http.route(
        "/api/member/auth/me",
        type="http",
        auth="none",
        methods=["GET", "POST", "OPTIONS"],
        csrf=False,
        cors="*",
    )
    def member_me(self, **kw):
        member_profile_id, uid, _tenant_id = self._get_auth_from_request()
        if not uid:
            return self._json_response(
                {"success": False, "message": "Authentication required"}, 401
            )
        MemberProfile = request.env["studio.member_profile"].sudo()
        if member_profile_id:
            member = MemberProfile.browse(member_profile_id)
            if not member.exists() or member.user_id.id != uid or not member.active_subscription_id:
                return self._json_response(
                    {"success": False, "message": "Member profile not found"}, 404
                )
        else:
            member = MemberProfile.search(
                [("user_id", "=", uid), ("active_subscription_id", "!=", False)],
                limit=1,
            )
            if not member:
                return self._json_response(
                    {"success": False, "message": "Member profile not found"}, 404
                )

        tenant = member.tenant_id
        return self._json_response({
            "success": True,
            "member": member._serialize_for_api(),
            "tenant": {
                "id": tenant.id,
                "name": tenant.name,
                "website_url": tenant.website_url or "",
                "login_url": tenant.login_url or "",
            },
        })

    @staticmethod
    def _get_uid_from_request():
        """Resolve request user: Bearer JWT first, then session. Returns uid or None."""
        _, uid, _ = MemberAuthController._get_auth_from_request()
        return uid

    @staticmethod
    def _get_auth_from_request():
        """
        Resolve auth from request: Bearer JWT first, then session.
        Returns (member_profile_id, uid, tenant_id).
        member_profile_id and tenant_id may be None when using session cookie.
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
