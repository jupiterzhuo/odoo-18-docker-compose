# Installing Odoo 18.0 with one command (Supports multiple Odoo instances on one server).

## Quick installation

Install [Docker](https://docs.docker.com/get-docker/) and [Compose](https://docs.docker.com/compose/install/) yourself.

This project is **not** tied to any third-party upstream. Use **your own** Git repository for this compose tree.

**Git / Cursor:** Booking addons live in **`addons/odoo18_booking_system/`** inside this same repo — they show in **Source Control** with the rest of the project. Details: **[REPOS.md](REPOS.md)**. Optional: open **`odoo-docker.code-workspace`** for two folder roots in the sidebar.

If Git or Cursor shows **“Repository not found”**, the GitHub repo for `origin` does not exist yet or your account cannot access it — see **[docs/GIT_REMOTE_SETUP.md](docs/GIT_REMOTE_SETUP.md)**.

### Option A — you already have this folder

```bash
docker compose up -d
```

Then open `http://localhost:10018` (adjust the port in `docker-compose.yml` if needed). Set the master password in `etc/odoo.conf` (`admin_passwd`).

### Option B — `run.sh` into a new directory

`run.sh` clones from a URL you choose (your GitHub repo containing this project):

```bash
export ODOO_COMPOSE_GIT_URL=https://github.com/YOU/your-odoo-docker-compose.git
chmod +x run.sh
./run.sh odoo-one 10018 20018
```

`run.sh` arguments:

* First (**odoo-one**): target deploy folder name
* Second (**10018**): Odoo HTTP port
* Third (**20018**): live chat port

If `curl` is not found, install it:

``` bash
$ sudo apt-get install curl
# or
$ sudo yum install curl
```

<p>
<img src="screenshots/odoo-18-docker-compose.gif" width="100%">
</p>

## Usage

Start the container:
``` sh
docker-compose up
```
Then open `localhost:10018` to access Odoo 18.

- **If you get any permission issues**, change the folder permission to make sure that the container is able to access the directory:

``` sh
$ sudo chmod -R 777 addons
$ sudo chmod -R 777 etc
$ sudo chmod -R 777 postgresql
```

- If you want to start the server with a different port, change **10018** to another value in **docker-compose.yml** inside the parent dir:

```
ports:
 - "10018:8069"
```

- To run Odoo container in detached mode (be able to close terminal without stopping Odoo):

```
docker-compose up -d
```

- To Use a restart policy, i.e. configure the restart policy for a container, change the value related to **restart** key in **docker-compose.yml** file to one of the following:
   - `no` =	Do not automatically restart the container. (the default)
   - `on-failure[:max-retries]` =	Restart the container if it exits due to an error, which manifests as a non-zero exit code. Optionally, limit the number of times the Docker daemon attempts to restart the container using the :max-retries option.
  - `always` =	Always restart the container if it stops. If it is manually stopped, it is restarted only when Docker daemon restarts or the container itself is manually restarted. (See the second bullet listed in restart policy details)
  - `unless-stopped`	= Similar to always, except that when the container is stopped (manually or otherwise), it is not restarted even after Docker daemon restarts.
```
 restart: always             # run as a service
```

- To increase maximum number of files watching from 8192 (default) to **524288**. In order to avoid error when we run multiple Odoo instances. This is an *optional step*. These commands are for Ubuntu user:

```
$ if grep -qF "fs.inotify.max_user_watches" /etc/sysctl.conf; then echo $(grep -F "fs.inotify.max_user_watches" /etc/sysctl.conf); else echo "fs.inotify.max_user_watches = 524288" | sudo tee -a /etc/sysctl.conf; fi
$ sudo sysctl -p    # apply new config immediately
``` 

## Custom addons

The **addons/** folder contains custom addons. Studio Booking code lives under **addons/odoo18_booking_system/** (`studio_booking` + `studio_booking_api`). See **addons/ADDONS.md** and **addons/odoo18_booking_system/README.md** for layout and `etc/odoo.conf` `addons_path`.

## Odoo configuration & log

* To change Odoo configuration, edit file: **etc/odoo.conf**.
* Log file: **etc/odoo-server.log**
* Master / database manager password (**admin_passwd**): set in `etc/odoo.conf` (search for `admin_passwd`) and change it for production.

## Odoo container management

**Run Odoo**:

``` bash
docker-compose up -d
```

**Restart Odoo**:

``` bash
docker-compose restart
```

**Stop Odoo**:

``` bash
docker-compose down
```

## Live chat

In [docker-compose.yml#L21](docker-compose.yml#L21), we exposed port **20018** for live-chat on host.

Configuring **nginx** to activate live chat feature (in production):

``` conf
#...
server {
    #...
    location /longpolling/ {
        proxy_pass http://0.0.0.0:20018/longpolling/;
    }
    #...
}
#...
```

## docker-compose.yml

* odoo:18
* postgres:17

## Odoo 18.0 screenshots after successful installation.

<p align="center">
<img src="screenshots/odoo-18-welcome-screenshot.png" width="50%">
</p>

<p>
<img src="screenshots/odoo-18-apps-screenshot.png" width="100%">
</p>

<p>
<img src="screenshots/odoo-18-sales-screen.png" width="100%">
</p>

<p>
<img src="screenshots/odoo-18-product-form.png" width="100%">
</p>

## Credits

This stack started from a public Odoo 18 Docker Compose template; this fork is maintained in **[jupiterzhuo/odoo-18-docker-compose](https://github.com/jupiterzhuo/odoo-18-docker-compose)** with custom `etc/`, addons layout, and Studio Booking integration.
