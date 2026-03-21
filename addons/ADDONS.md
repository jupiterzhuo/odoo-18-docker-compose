# Custom addons layout

Studio Booking addons live under **`odoo18_booking_system/`** in this compose repository (same Git remote as the project root — see root **`REPOS.md`**).

| Path | Odoo module name | Role |
|------|------------------|------|
| `odoo18_booking_system/studio_booking/` | `studio_booking` | Core (models, UI, services) |
| `odoo18_booking_system/studio_booking_api/` | `studio_booking_api` | HTTP / JSON API |
| `odoo18_booking_system/booking_system_penalties/` | `booking_system_penalties` | Bootstrap: booking penalties (`studio.booking_penalty`) |

Module folders use **underscores** (Python / Odoo requirement). There is **no extra nesting** — addons sit directly under `odoo18_booking_system/`.

`etc/odoo.conf` → `addons_path` includes **one** custom entry: `/mnt/extra-addons/odoo18_booking_system` (Odoo discovers all module folders there).

**Database:** `ir_module_module` stores each technical name (e.g. `studio_booking`, `studio_booking_api`, `booking_system_penalties`). Moving or renaming **disk** folders does **not** delete data if `addons_path` stays correct.

**GitHub:** Push from the **compose repo root**; `addons/odoo18_booking_system/` is tracked there. (An older separate `odoo18-booking-system` clone, if any, is optional to keep in sync manually.)

## Safe upgrade (keeps your data)

- **Upgrade** (`-u` / Apps → Upgrade) reapplies code and XML; it does **not** wipe business tables. PostgreSQL data lives in `./postgresql` — never delete that volume to “upgrade”.
- **Do not** use `--init` / `-i studio_booking` on a database that already has production data unless you know you are creating a **new** DB.
- After path changes: `docker compose restart odoo18` (or full `up -d`) → **Apps** → **Update Apps List** → **Upgrade** `Studio Booking` then `Studio Booking API` (or CLI: `odoo -u studio_booking,studio_booking_api -d YOUR_DB --stop-after-init`).
- **Uninstall** a module from Apps is what removes that module’s data — avoid uninstalling `studio_booking` if you want to keep bookings.
