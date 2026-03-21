# Git layout (one repo in Cursor — booking files visible)

## What changed

Booking addons **used to be a nested Git repo** inside `addons/odoo18_booking_system/`. The **compose** repo **ignored** that folder, so **Source Control never listed** `booking_system_penalties` (or any file there).

Now **`addons/odoo18_booking_system/` is part of this repo** (`jupiterzhuo/odoo-18-docker-compose`). Edits under `studio_booking/`, `studio_booking_api/`, `booking_system_penalties/`, etc. show up in **Changes** like any other file.

## Old nested repo backup

The previous `.git` folder for `odoo18-booking-system` was moved to:

**`_odoo18_booking_system_git_backup/`** (ignored by Git — do not delete until you are sure you don’t need it).

To **restore** the old two-repo setup (not recommended for IDE simplicity):

```bash
rm -rf addons/odoo18_booking_system/.git 2>/dev/null
mv _odoo18_booking_system_git_backup addons/odoo18_booking_system/.git
# Then add again to parent .gitignore: addons/odoo18_booking_system/
```

## Remotes

| GitHub repo | Contents |
|-------------|----------|
| [jupiterzhuo/odoo-18-docker-compose](https://github.com/jupiterzhuo/odoo-18-docker-compose) | Compose **and** all addons under `addons/odoo18_booking_system/` |

Optional: keep [odoo18-booking-system](https://github.com/jupiterzhuo/odoo18-booking-system) as a **mirror** (push with `git subtree split` or manual copy) if you still want a booking-only repo.

## Cursor

You can open the folder **or** `odoo-docker.code-workspace`. **Source Control → `master`** should list `addons/odoo18_booking_system/...` after refresh.
