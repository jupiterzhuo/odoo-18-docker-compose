# Copyright 2025
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl.html).

import logging
import time

import jwt

_logger = logging.getLogger(__name__)

# Default expiry for access token (seconds). 7 days.
DEFAULT_EXPIRY_SECONDS = 7 * 24 * 3600

# Refresh token expiry (seconds). 30 days for "remember me".
REFRESH_TOKEN_EXPIRY_SECONDS = 30 * 24 * 3600

# Config parameter key for JWT secret (must be set for JWT to be issued).
JWT_SECRET_PARAM = "studio_booking.jwt_secret"

# Token type in payload (access vs refresh).
TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_REFRESH = "refresh"


def _get_secret(env):
    """Return JWT signing secret from system parameter. None if not set."""
    return (env["ir.config_parameter"].sudo().get_param(JWT_SECRET_PARAM) or "").strip() or None


def _encode_jwt(env, uid, member_profile_id, tenant_id, token_type, expires_in_seconds):
    """Internal: build JWT with given type. Returns (token_string, expires_in) or (None, 0)."""
    secret = _get_secret(env)
    if not secret:
        _logger.warning(
            "JWT secret not set (ir.config_parameter %s). Skipping JWT issuance.",
            JWT_SECRET_PARAM,
        )
        return None, 0
    now = int(time.time())
    payload = {
        "uid": int(uid),
        "member_profile_id": int(member_profile_id),
        "tenant_id": int(tenant_id),
        "type": token_type,
        "iat": now,
        "exp": now + expires_in_seconds,
    }
    token = jwt.encode(
        payload,
        secret,
        algorithm="HS256",
    )
    if isinstance(token, bytes):
        token = token.decode("utf-8")
    return token, expires_in_seconds


def encode_token(env, uid, member_profile_id, tenant_id, expires_in_seconds=None):
    """
    Build an access JWT for the given user/member/tenant.
    Returns (token_string, expires_in_seconds) or (None, 0) if secret not configured.
    """
    expires_in = expires_in_seconds or DEFAULT_EXPIRY_SECONDS
    return _encode_jwt(env, uid, member_profile_id, tenant_id, TOKEN_TYPE_ACCESS, expires_in)


def encode_refresh_token(env, uid, member_profile_id, tenant_id, expires_in_seconds=None):
    """
    Build a refresh JWT for "remember me". Long-lived, used to obtain new access tokens.
    Returns (token_string, expires_in_seconds) or (None, 0) if secret not configured.
    """
    expires_in = expires_in_seconds or REFRESH_TOKEN_EXPIRY_SECONDS
    return _encode_jwt(env, uid, member_profile_id, tenant_id, TOKEN_TYPE_REFRESH, expires_in)


def decode_token(env, token_string, expected_type=None):
    """
    Decode and verify a JWT. Returns payload dict or None if invalid/expired/secret missing.
    If expected_type is set (TOKEN_TYPE_ACCESS or TOKEN_TYPE_REFRESH), validates token type.
    """
    if not token_string or not isinstance(token_string, str):
        return None
    secret = _get_secret(env)
    if not secret:
        return None
    try:
        payload = jwt.decode(
            token_string,
            secret,
            algorithms=["HS256"],
        )
        if expected_type:
            token_type = payload.get("type")
            if expected_type == TOKEN_TYPE_REFRESH and token_type != TOKEN_TYPE_REFRESH:
                _logger.debug("JWT type mismatch: expected refresh, got %s", token_type)
                return None
            if expected_type == TOKEN_TYPE_ACCESS and token_type not in (None, TOKEN_TYPE_ACCESS):
                _logger.debug("JWT type mismatch: expected access, got %s", token_type)
                return None
        return payload
    except (jwt.ExpiredSignatureError, jwt.InvalidSignatureError, jwt.InvalidTokenError) as e:
        _logger.debug("JWT decode failed: %s", e)
        return None
