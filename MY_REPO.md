# My repositories (this workspace)

| What | GitHub |
|------|--------|
| **Full project (Docker + addons)** — default **`git push`** | **[github.com/jupiterzhuo/odoo-18-docker-compose](https://github.com/jupiterzhuo/odoo-18-docker-compose)** → remote name **`compose`** |
| **Booking addons mirror** | **[github.com/jupiterzhuo/odoo18-booking-system](https://github.com/jupiterzhuo/odoo18-booking-system)** → remote name **`origin`** |

- Branches **`master`** and **`subcription-module`** track **`compose/...`** so Cursor’s Push/Pull update the **docker-compose** repo.
- To refresh **odoo18-booking-system**, use the **subtree** commands in **`REPOS.md`** (`git push origin split-booking-export:main`).

Open **`odoo-docker.code-workspace`** so the sidebar shows the repo layout clearly.
