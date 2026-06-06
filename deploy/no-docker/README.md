# No-Docker Deploy

This is the fastest production-ish path for `tg-swarm` on a typical Ubuntu or Debian server.

Assumptions:

- the server uses `systemd`
- the reverse proxy is `nginx`
- the app will run as a normal Python process
- webhook mode is preferred over `--poll`

## Layout

Recommended server paths:

- app checkout: `/opt/tg-swarm/current`
- virtualenv: `/opt/tg-swarm/.venv`
- env file: `/etc/tg-swarm.env`
- runtime state: `/var/lib/tg-swarm/state`
- runtime data: `/var/lib/tg-swarm/data`

Why separate state/data from the repo checkout:

- the runtime writes sessions, approvals, monitoring, and campaign data to disk
- deploys become safer because app code and runtime data are not mixed together
- systemd hardening stays simple

## 1. Install OS packages

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nginx
```

If you plan to use Telethon-backed MTProto features, make sure the server can keep durable files under `/var/lib/tg-swarm/data`.

## 2. Create directories and user

```bash
sudo useradd --system --create-home --shell /usr/sbin/nologin tg-swarm
sudo mkdir -p /opt/tg-swarm /var/lib/tg-swarm/state /var/lib/tg-swarm/data
sudo chown -R tg-swarm:tg-swarm /opt/tg-swarm /var/lib/tg-swarm
sudo chmod 700 /var/lib/tg-swarm /var/lib/tg-swarm/state /var/lib/tg-swarm/data
```

## 3. Copy the repo and install Python deps

```bash
sudo -u tg-swarm git clone <YOUR_REPO_URL> /opt/tg-swarm/current
sudo -u tg-swarm python3 -m venv /opt/tg-swarm/.venv
sudo -u tg-swarm /opt/tg-swarm/.venv/bin/pip install --upgrade pip
sudo -u tg-swarm /opt/tg-swarm/.venv/bin/pip install -r /opt/tg-swarm/current/requirements.txt
```

## 4. Create `/etc/tg-swarm.env`

Start from `.env.example`, but keep production secrets outside the repo.

Example:

```env
ANTHROPIC_API_KEY=replace_me
DEFAULT_MODEL=anthropic/claude-sonnet-4-6
TELEGRAM_BOT_TOKEN=replace_me

# Leave unset for the simplest first deploy.
# Set to telethon only when you are ready to run managed-account features.
# TELEGRAM_CAPABILITY_BACKEND=telethon
# TELEGRAM_API_ID=
# TELEGRAM_API_HASH=

HOST=127.0.0.1
PORT=8080

TELEGRAM_RUNTIME_STATE_DIR=/var/lib/tg-swarm/state
TG_SWARM_DATA_DIR=/var/lib/tg-swarm/data

# Strongly recommended if you will expose monitoring endpoints.
TG_SWARM_MONITORING_API_KEY=replace_with_random_secret
```

Notes:

- `HOST=127.0.0.1` keeps the Python app off the public interface and lets Nginx handle public traffic.
- Rotate any previously used local bot or API credentials before first public deploy.
- If you later enable Telethon, protect `/var/lib/tg-swarm/data/sessions` carefully because those session files are authenticated Telegram credentials.

## 5. Install the systemd app service

Copy [tg-swarm.service](./tg-swarm.service) to `/etc/systemd/system/tg-swarm.service` and adjust paths only if you choose a different server layout.

Then enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now tg-swarm
sudo systemctl status tg-swarm
```

Logs:

```bash
journalctl -u tg-swarm -f
```

## 6. Install Nginx

Copy [nginx-tg-swarm.conf](./nginx-tg-swarm.conf) to `/etc/nginx/sites-available/tg-swarm.conf`, edit `server_name`, then enable it:

```bash
sudo ln -s /etc/nginx/sites-available/tg-swarm.conf /etc/nginx/sites-enabled/tg-swarm.conf
sudo nginx -t
sudo systemctl reload nginx
```

Use your normal TLS flow after that. `certbot` is the common path on Ubuntu.

## 7. Set the Telegram webhook

Once the public domain and TLS are working:

```bash
curl -X POST http://127.0.0.1:8080/telegram/webhook/set \
  -H "Content-Type: application/json" \
  -d '{"webhook_url":"https://YOUR_DOMAIN/telegram/webhook"}'
```

Check it:

```bash
curl http://127.0.0.1:8080/telegram/webhook/info
```

## 8. Verify the live app

Basic checks:

```bash
curl http://127.0.0.1:8080/healthz
curl https://YOUR_DOMAIN/healthz
```

If monitoring auth is enabled:

```bash
curl http://127.0.0.1:8080/ops/monitoring/status \
  -H "x-monitoring-key: YOUR_MONITORING_KEY"
```

Then message the bot in Telegram and watch:

```bash
journalctl -u tg-swarm -f
```

## Optional scheduler worker

If you start relying on recurring campaign work, also install [tg-swarm-scheduler.service](./tg-swarm-scheduler.service).

Enable it:

```bash
sudo systemctl enable --now tg-swarm-scheduler
sudo systemctl status tg-swarm-scheduler
```

For a first deploy focused on the operator chat loop, you can start with only the main `tg-swarm` app service and add the scheduler later.
