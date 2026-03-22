# Git layout (one repo in Cursor — booking files visible)

## What changed

Booking addons **used to be a nested Git repo** inside `addons/odoo18_booking_system/`. The **compose** repo **ignored** that folder, so **Source Control never listed** `booking_system_penalties` (or any file there).

Now **`addons/odoo18_booking_system/` is part of this repo** (`jupiterzhuo/odoo-18-docker-compose`). Edits under `studio_booking/`, `studio_booking_api/`, `booking_system_penalties/`, etc. show up in **Changes** like any other file.

## Remotes

| Name (local) | GitHub repo | Contents |
|--------------|-------------|----------|
| **`compose`** | [odoo-18-docker-compose](https://github.com/jupiterzhuo/odoo-18-docker-compose) | Full project: Docker stack **and** `addons/odoo18_booking_system/` |
| **`origin`** | [odoo18-booking-system](https://github.com/jupiterzhuo/odoo18-booking-system) | **Mirror** of the addons folder only (via subtree push) |

**Daily push/pull** (branches track `compose/*`): `git push` / `git pull` → **compose** (docker-compose repo).

### Push addons to `odoo18-booking-system` (after you committed)

From this repo root:

```bash
git subtree split --prefix=addons/odoo18_booking_system -b split-booking-export
git push origin split-booking-export:main --force
git branch -D split-booking-export
```

`--force` rewrites `main` on the booking repo so it matches the current subtree (old booking-only history is replaced). Use **only** if you accept that.

If **`origin`** is missing:

```bash
git remote add origin https://github.com/jupiterzhuo/odoo18-booking-system.git
```

If **`compose`** is missing:

```bash
git remote add compose https://github.com/jupiterzhuo/odoo-18-docker-compose.git
```

## Cursor

You can open the folder **or** `odoo-docker.code-workspace`. **Source Control** should list `addons/odoo18_booking_system/...` after refresh.
