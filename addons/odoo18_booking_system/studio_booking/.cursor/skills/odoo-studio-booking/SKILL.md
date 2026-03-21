---
name: odoo-studio-booking
description: Implementation guide for studio_booking Odoo 18 module. Use when building booking flows, session management, waitlist, recurring generation, tenant logic, controllers, or model changes in studio_booking.
---

# Studio Booking: Odoo Implementation Guide

## 1. Project Understanding

- **Module:** `studio_booking` (Odoo 18)
- **Structure:** `models/`, `views/`, `controllers/`, `security/`, `data/`, `tests/`, `utils/`, `static/src/scss/`
- **Domain:** Multi-tenant yoga studio booking with sessions, bookings, waitlist, check-in, recurring generation

---

## 2. Domain Glossary (Actual Model Names)

| Model | Purpose |
|-------|---------|
| `studio.tenant` | Top-level tenant isolation |
| `studio.branch` | Physical location within tenant |
| `studio.room` | Space within branch; has capacity |
| `studio.instructor` | Teacher; belongs to tenant |
| `studio.class_template` | Class type (e.g. Yoga Flow); duration_minutes |
| `studio.session_template` | Recurring source; day_of_week, start_time, end_time |
| `studio.class_session` | Generated operational session; session_start, session_end |
| `studio.booking` | Member reservation; booking_status, attendance_status, waitlist_sequence |
| `studio.member_profile` | Member; links to res.users; active_subscription_id |
| `studio.membership_plan` | Plan; branch_ids restriction |
| `studio.membership_subscription` | Member's subscription; date_start, date_end, state |
| `studio.session_booking_detail` | Transient pop-up: Who is Booking / Who is Waitlist |
| `res.users` | Extended with studio_tenant_ids, is_studio_manager(), ensure_studio_tenant_allowed() |

---

## 3. Multi-Tenant Strategy

- `res.users.studio_tenant_ids`: tenants this user can access
- **Admin Tenant** (`group_studio_booking_user`): exactly one tenant; `_get_forced_tenant_for_user()` forces it
- **Admin SaaS** (`group_studio_booking_manager`): all tenants; no forced tenant
- **Record rules:** Manager gets `[(1,'=',1)]`; User gets `[('tenant_id','in',user.studio_tenant_ids.ids)]`
- **Model hooks:** Call `self.env.user.ensure_studio_tenant_allowed(tenant)` before create/write on tenant-scoped records

---

## 4. Booking / Session Architecture

**Recurring flow:**
- `studio.session_template` (day_of_week, start_time, end_time) → cron `_cron_generate_upcoming_sessions`
- Generates `studio.class_session` with `session_template_id`, `generated_by_cron=True`
- SQL constraint: `unique(session_template_id, session_start)` for idempotency

**Booking flow:**
- `studio.booking` links `session_id` + `member_profile_id`
- Status resolved in create/write: `_resolve_booking_status_for_save()` → booked or waitlisted
- Never trust `booking_status` from input; use `_prepare_booking_vals_for_save()`
- Waitlist: `waitlist_sequence` for FIFO; `_try_promote_from_waitlist()` on cancel

---

## 5. Clean Model Patterns

### studio.booking — Helper Decomposition

```python
# GOOD: Private helpers for validation and preparation
def _validate_eligibility_for_save(self, member_profile_id, session_id, at_dt=None):
    """Raises ValidationError if invalid."""
    ...

def _prepare_booking_vals_for_save(self, vals, session):
    """Returns vals with resolved status and audit. Do not trust input."""
    resolved_status = self._resolve_booking_status_for_save(session)
    audit = self._get_booking_audit_vals()
    out = dict(vals)
    out["booking_status"] = resolved_status
    out["booked_by_user_id"] = audit["booked_by_user_id"]
    out["booking_source"] = audit["booking_source"]
    return out

# create/write: call helpers, keep logic small
def create(self, vals_list):
    for vals in vals_list:
        self.env.user.ensure_studio_tenant_allowed(session.tenant_id)
        self._validate_create_write_booking(vals, exclude_booking_id=None)
        prepared = self._prepare_booking_vals_for_save(vals, session)
        vals.update(prepared)
    return super().create(vals_list)
```

### studio.class_session — Conflict Validation

```python
# GOOD: Domain helper + focused conflict checks
def _get_conflicting_sessions_domain(self):
    self.ensure_one()
    return [
        ("id", "!=", self.id),
        ("tenant_id", "=", self.tenant_id.id),
        ("state", "!=", "cancelled"),
        ("session_start", "<", self.session_end),
        ("session_end", ">", self.session_start),
    ]

def _check_room_conflict(self):
    conflict = self.search(
        rec._get_conflicting_sessions_domain() + [("room_id", "=", rec.room_id.id)],
        limit=1,
    )
    if conflict:
        raise ValidationError(...)

def _check_session_conflicts(self):
    rec._check_room_conflict()
    rec._check_instructor_conflict()
```

### studio.session_template — Recurring Generation

```python
# GOOD: Decomposed helpers
def _get_target_dates_for_horizon(self, horizon_days=7, from_date=None): ...
def _get_candidate_session_datetimes(self, horizon_days=7, from_date=None): ...
def _build_session_start_end(self, target_date): ...
def _session_exists(self, target_start): ...
def _has_room_conflict(self, session_start, session_end): ...
def _generate_session_for_date(self, target_date):  # returns (session, created)
def _generate_upcoming_sessions(self, horizon_days=7): ...
```

### Tenant-Safe Create/Write

```python
# GOOD: Check tenant before super()
def create(self, vals_list):
    for vals in vals_list:
        tenant = Tenant.browse(vals.get("tenant_id"))
        self.env.user.ensure_studio_tenant_allowed(tenant)
    records = super().create(vals_list)
    records._ensure_session_name()
    return records
```

---

## 6. Thin Controller Pattern

```python
# GOOD: Parse → auth → call model → format response
@http.route("/studio/api/v1/sessions/<int:session_id>/book", type="json", auth="user")
def session_book(self, session_id, member_profile_id):
    session = request.env["studio.class_session"].browse(session_id)
    if not session.exists():
        return {"success": False, "error": "Session not found"}
    try:
        booking = session.action_book(member_profile_id)
        return {"success": True, "booking_id": booking.id}
    except UserError as e:
        return {"success": False, "error": str(e)}
```

---

## 7. Do / Don't

**Onchange vs constraint:**
```python
# BAD: Sole enforcement in onchange (user can bypass)
@api.onchange("member_profile_id")
def _onchange_member(self):
    if not self._is_eligible(...):
        self.member_profile_id = False  # User can still save invalid

# GOOD: Constraint is source of truth
@api.constrains("member_profile_id", "session_id")
def _check_eligibility(self):
    self._validate_eligibility_for_save(...)
```

**Controller vs model:**
```python
# BAD: Business logic in controller
def session_book(self, session_id, member_profile_id):
    session = ...
    if session.booked_count >= session.capacity:
        return {"error": "Full"}
    # ... duplicate eligibility check ...

# GOOD: Model owns logic
def session_book(self, session_id, member_profile_id):
    session = request.env["studio.class_session"].browse(session_id)
    booking = session.action_book(member_profile_id)  # Model does all checks
    return {"success": True, "booking_id": booking.id}
```

---

## 8. Adding Tests Safely

- Use `SavepointCase`; set `group_studio_booking_manager` for manager tests
- Create tenant, branch, room, instructor, class_template via `create()`
- Use `_session_template_vals()` / `_make_manual_session()` helpers
- Preserve `class_template_id` alias in template vals for backward compatibility
- Add tests for new invariants; do not remove existing assertions

---

## 9. Member Profile Onboarding Flow

- Member auth: `MemberAuthController` at `/api/member/auth/login`, `/api/member/profile`, `/api/member/auth/me`
- JWT: `jwt_helper.encode_token` / `decode_token`; secret from `studio_booking.jwt_secret`
- Member serialization: `member._serialize_for_api()`, `member._serialize_profile_for_api()` on `studio.member_profile`
- Mail template: `data/mail_template_member_welcome.xml` for member welcome

---

## 10. Extending Tests for Booking Invariants

```python
def test_duplicate_booking_same_session_blocked(self):
    session = self._make_manual_session()
    member = self.env["studio.member_profile"].create({...})
    self.env["studio.booking"].create({
        "session_id": session.id,
        "member_profile_id": member.id,
        "booking_status": "booked",
        "attendance_status": "pending",
    })
    with self.assertRaises(ValidationError):
        self.env["studio.booking"].create({
            "session_id": session.id,
            "member_profile_id": member.id,
            "booking_status": "booked",
            "attendance_status": "pending",
        })
```

---

## 11. Prompt Recipes

- "Add eligibility check for X in studio.booking following existing _validate_eligibility_for_save pattern"
- "Implement TODO in controllers/main.py session_book by calling session.action_book"
- "Add constraint for Y in studio.class_session using _get_conflicting_sessions_domain"
- "Extend studio.session_template recurring for monthly range using _month_occurrence_from_start"
