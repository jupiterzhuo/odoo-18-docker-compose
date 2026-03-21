# Odoo 18 — Studio Booking (`odoo18_booking_system`)

Odoo **18** custom modules for multi-tenant studio / class booking.

## Layout (flat — no extra nesting)

| Path | Odoo technical name | Role |
|------|---------------------|------|
| `studio_booking/` | `studio_booking` | Core: models, security, views, mail, cron |
| `studio_booking_api/` | `studio_booking_api` | HTTP/JSON API (`auto_install` with core) |
| `booking_system_penalties/` | `booking_system_penalties` | Bootstrap: penalties (`studio.booking_penalty`), optional install |

Addon folders live **directly** in this directory (underscore names — required by Python/Odoo).

## Docker (compose repo)

`docker-compose.yml` mounts `./addons` → `/mnt/extra-addons`.

`etc/odoo.conf` should include **one** custom entry on `addons_path` (after core Odoo addons):

```text
/mnt/extra-addons/odoo18_booking_system
```

Odoo loads every subdirectory here that contains `__manifest__.py`.

Restart Odoo after path changes. **Upgrading** modules (`-u` / Apps → Upgrade) does not remove business data; DB module names stay e.g. `studio_booking`, `studio_booking_api`, `booking_system_penalties`.

## Git / Cursor

These addons are tracked in the **compose repository** (project root). Commit and push from the repo root so **Source Control** shows `addons/odoo18_booking_system/...` (including `booking_system_penalties`).

```bash
cd /path/to/odoo-18-docker-compose   # repo root, not this folder only
git add addons/odoo18_booking_system
git commit -m "Your message"
git push origin master
```

See root **`REPOS.md`** and **`../ADDONS.md`**.
