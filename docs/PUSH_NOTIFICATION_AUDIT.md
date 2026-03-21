# Push Notification Audit – Waitlist Promotion

**Date:** 2025-03-19  
**Module:** `studio_booking`  
**Scope:** Odoo backend only

---

## Summary

| # | Item | Status | Notes |
|---|------|--------|-------|
| 1 | VAPID private key in Studio Booking settings | **Implemented** | Field exists, get/set via ICP |
| 2 | POST /api/member/push-subscribe | **Implemented** | JWT auth, validates payload, upserts subscription |
| 3 | _try_promote_from_waitlist triggers push | **Implemented** | Calls send_promotion_push after promotion |
| 4 | pywebpush installed and used | **Implemented** | entrypoint.sh + push_helper.py |

**Overall:** All four items are implemented. No gaps found.

---

## 1. VAPID Private Key Setting

| Field | Value |
|-------|-------|
| **Status** | Implemented |
| **File** | `addons/odoo18_booking_system/studio_booking/models/res_config_settings.py` |
| **View** | `addons/odoo18_booking_system/studio_booking/views/res_config_settings_views.xml` |
| **Method** | `get_values()`, `set_values()` |
| **Param** | `studio_booking.vapid_private_key` (from `push_helper.VAPID_PRIVATE_KEY_PARAM`) |

**Evidence:**
- `vapid_private_key` Char field with password=True
- Stored in `ir.config_parameter` via ICP
- UI: Settings → Studio Booking → Member App API → VAPID Private Key
- Help text: "Generate with: npx web-push generate-vapid-keys"

---

## 2. POST /api/member/push-subscribe

| Field | Value |
|-------|-------|
| **Status** | Implemented |
| **File** | `addons/odoo18_booking_system/studio_booking_api/controllers/member_auth.py` |
| **Route** | `POST /api/member/push-subscribe` |
| **Method** | `member_push_subscribe()` |

**Evidence:**
- JWT auth via `_get_auth_from_request()`
- Validates `subscription` object: `endpoint`, `keys.p256dh`, `keys.auth`
- Calls `PushSub.upsert_from_payload(member.id, subscription)`
- Returns `{"success": true, "message": "Push notifications enabled"}`

**Example API payload:**
```json
{
  "subscription": {
    "endpoint": "https://fcm.googleapis.com/fcm/send/...",
    "keys": {
      "p256dh": "BEl62iUYgUivxIkv69yViEui...",
      "auth": "CG6f8...="
    },
    "expirationTime": null
  }
}
```

**Headers:** `Authorization: Bearer <access_token>`

---

## 3. _try_promote_from_waitlist Triggers Push

| Field | Value |
|-------|-------|
| **Status** | Implemented |
| **File** | `addons/odoo18_booking_system/studio_booking/models/studio_class_session.py` |
| **Method** | `_try_promote_from_waitlist()` (lines 468–512) |

**Evidence:**
- After `booking.write({...})` (promotion), calls:
  ```python
  from ..utils.push_helper import send_promotion_push
  send_promotion_push(
      self.env,
      booking.member_profile_id.id,
      self,
      class_name=self.template_id.name if self.template_id else None,
  )
  ```
- Wrapped in try/except; logs warning on failure, does not block promotion

**Callers of _try_promote_from_waitlist:**
- `studio_booking.py`: on cancel (lines 443, 614)

---

## 4. pywebpush Installed and Used

| Field | Value |
|-------|-------|
| **Status** | Implemented |
| **Install** | `entrypoint.sh` line 16 |
| **Usage** | `addons/odoo18_booking_system/studio_booking/utils/push_helper.py` |

**Evidence:**
- **Install:** `pip3 install "pywebpush>=1.14.0" --ignore-installed cryptography || true`
- **entrypoint** mounted in `docker-compose.yml` (line 32)
- **push_helper.py:** `from pywebpush import webpush, WebPushException`
- **__manifest__.py:** `"external_dependencies": {"python": ["jwt", "pytz", "pywebpush"]}`

**push_helper behavior:**
- `send_promotion_push(env, member_profile_id, session, class_name=None, date_str=None)`
- Skips if pywebpush not installed (logs warning)
- Skips if VAPID key not configured (debug log)
- Sends to all active subscriptions for member
- Unlinks subscriptions that fail (e.g. expired)
- Payload: `{ title, body, url, tag }` (JSON)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│  Frontend (Next.js)                                              │
│  - User clicks "Enable notifications"                            │
│  - POST /api/member/push-subscribe { subscription }              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  member_auth.py: member_push_subscribe()                         │
│  - JWT auth                                                      │
│  - Validate subscription                                         │
│  - PushSub.upsert_from_payload(member.id, subscription)        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  studio.push_subscription (model)                                │
│  - member_profile_id, endpoint, p256dh, auth                     │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  Cancel booking → _try_promote_from_waitlist()                    │
│  - Promote first waitlisted member                               │
│  - send_promotion_push(env, member_id, session)                   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  push_helper.py: send_promotion_push()                           │
│  - Load subscriptions for member                                 │
│  - webpush(subscription_info, data, vapid_private_key)            │
│  - Unlink failed subscriptions                                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Changed Files (Audit Only – No Changes Made)

No code changes were required. All items are already implemented.

---

## Gaps Fixed

None. Implementation is complete.

---

## Verification Checklist

- [ ] VAPID private key set in Odoo Settings → Studio Booking
- [ ] `NEXT_PUBLIC_VAPID_PUBLIC_KEY` in FE `.env.local` matches (public half of same key pair)
- [ ] Member enables push via FE "Enable notifications"
- [ ] Member joins waitlist for a full session
- [ ] Another member cancels → promotion runs → push sent
- [ ] Check Odoo logs for "Sent promotion push" or "Push failed"
