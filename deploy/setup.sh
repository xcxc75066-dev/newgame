#!/usr/bin/env bash
# =============================================================================
# Amani Market - one-time VPS setup (Ubuntu 22.04 / 24.04), run as root:
#
#   curl -fsSL https://raw.githubusercontent.com/xcxc75066-dev/newgame/main/deploy/setup.sh | bash
#
# What it does (safe to run again):
#   1. Installs git, python3, sqlite3, Caddy (web server with free HTTPS)
#   2. Downloads the shop code from GitHub into /opt/amani/app
#   3. Runs the shop as a service that restarts by itself if it crashes
#   4. Connects the domain with HTTPS through Caddy
#   5. Checks GitHub every minute and installs new versions of the code
#   6. Backs up the orders database every night (keeps 14 days)
#   7. Turns on the firewall (only SSH, HTTP, HTTPS are open)
# =============================================================================
set -euo pipefail

DOMAIN="${AMANI_DOMAIN:-boutiqueamani-maroc.com}"
REPO_URL="${AMANI_REPO_URL:-https://github.com/xcxc75066-dev/newgame.git}"
BRANCH="${AMANI_BRANCH:-main}"
BASE=/opt/amani
APP="$BASE/app"
APP_USER=amani

say() { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }

if [ "$(id -u)" -ne 0 ]; then
    echo "Please run this as root." >&2
    exit 1
fi

say "1/7 Installing packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q git python3 sqlite3 curl ufw ca-certificates gnupg ffmpeg
if ! apt-get install -y -q caddy; then
    # Older Ubuntu: use Caddy's official package repository.
    curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key \
        | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt \
        > /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -q
    apt-get install -y -q caddy
fi

say "2/7 Downloading the shop code"
id "$APP_USER" >/dev/null 2>&1 || useradd --system --home "$BASE" --shell /usr/sbin/nologin "$APP_USER"
mkdir -p "$BASE" "$BASE/backups"
if [ -d "$APP/.git" ]; then
    git -C "$APP" fetch -q origin "$BRANCH"
    git -C "$APP" reset -q --hard "origin/$BRANCH"
else
    git clone -q --branch "$BRANCH" "$REPO_URL" "$APP"
fi
mkdir -p "$APP/data"
if [ ! -f "$APP/.env" ]; then
    cp "$APP/.env.example" "$APP/.env"
    # A random admin token so the admin API is protected from day one.
    sed -i "s|^AMANI_ADMIN_TOKEN=.*|AMANI_ADMIN_TOKEN=$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')|" "$APP/.env"
    sed -i "s|^AMANI_ALLOWED_ORIGINS=.*|AMANI_ALLOWED_ORIGINS=https://$DOMAIN,https://www.$DOMAIN|" "$APP/.env"
fi
# The CMS lives on admin.<domain> (the old /mycmseditor address closes)
if ! grep -q '^AMANI_ADMIN_HOST=' "$APP/.env"; then
    [ -z "$(tail -c1 "$APP/.env")" ] || echo >> "$APP/.env"
    echo "AMANI_ADMIN_HOST=admin.$DOMAIN" >> "$APP/.env"
fi
chown -R "$APP_USER:$APP_USER" "$BASE"
chmod 600 "$APP/.env"

say "3/7 Running the shop as a service"
cat > /etc/systemd/system/amani.service <<EOF
[Unit]
Description=Amani Market shop
After=network-online.target
Wants=network-online.target

[Service]
User=$APP_USER
WorkingDirectory=$APP
ExecStart=/usr/bin/python3 $APP/app.py --host 127.0.0.1 --port 5000
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true

[Install]
WantedBy=multi-user.target
EOF

say "4/7 Connecting $DOMAIN with HTTPS"
cat > /etc/caddy/Caddyfile <<EOF
www.$DOMAIN {
    redir https://$DOMAIN{uri} permanent
}

$DOMAIN {
    encode gzip
    reverse_proxy 127.0.0.1:5000
}

# The CMS has its own address
admin.$DOMAIN {
    encode gzip
    reverse_proxy 127.0.0.1:5000
}
EOF

say "5/7 Automatic updates from GitHub (every minute)"
cat > /usr/local/bin/amani-update <<EOF
#!/usr/bin/env bash
# Installs the newest code from GitHub if it changed, then restarts the shop.
set -euo pipefail
cd $APP
runuser -u $APP_USER -- git fetch -q origin $BRANCH
if [ "\$(git rev-parse HEAD)" != "\$(git rev-parse origin/$BRANCH)" ]; then
    runuser -u $APP_USER -- git reset -q --hard origin/$BRANCH
    systemctl restart amani
    echo "Updated to \$(git log -1 --format='%h %s')"
fi
EOF
chmod 755 /usr/local/bin/amani-update
cat > /etc/systemd/system/amani-update.service <<EOF
[Unit]
Description=Install new Amani Market code from GitHub

[Service]
Type=oneshot
ExecStart=/usr/local/bin/amani-update
EOF
cat > /etc/systemd/system/amani-update.timer <<EOF
[Unit]
Description=Check GitHub for new Amani Market code every minute

[Timer]
OnBootSec=1min
OnUnitActiveSec=1min

[Install]
WantedBy=timers.target
EOF
git config --system --add safe.directory "$APP"

say "6/7 Nightly backup of orders, products and photos"
cat > /usr/local/bin/amani-backup <<EOF
#!/usr/bin/env bash
set -euo pipefail
DB=$APP/data/amani_orders.sqlite3
[ -f "\$DB" ] || exit 0
sqlite3 "\$DB" ".backup '$BASE/backups/orders-\$(date +%F).sqlite3'"
# Products, photos and history edited in the CMS live in data/ (not in git).
tar -czf "$BASE/backups/cms-\$(date +%F).tar.gz" -C $APP/data content content-history uploads 2>/dev/null || true
find $BASE/backups -mindepth 1 -maxdepth 1 -mtime +14 -exec rm -rf {} +
EOF
chmod 755 /usr/local/bin/amani-backup
cat > /etc/systemd/system/amani-backup.service <<EOF
[Unit]
Description=Back up Amani Market orders

[Service]
Type=oneshot
ExecStart=/usr/local/bin/amani-backup
EOF
cat > /etc/systemd/system/amani-backup.timer <<EOF
[Unit]
Description=Nightly Amani Market backup

[Timer]
OnCalendar=*-*-* 03:30:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

say "7/7 Firewall and start"
ufw allow OpenSSH >/dev/null
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null
systemctl daemon-reload
systemctl enable --now amani.service amani-update.timer amani-backup.timer
systemctl restart amani.service
systemctl enable caddy >/dev/null
systemctl reload-or-restart caddy

sleep 2
if curl -fsS http://127.0.0.1:5000/api/health >/dev/null; then
    say "DONE. The shop is running."
else
    echo "The shop did not start. Show this to Claude:" >&2
    journalctl -u amani -n 30 --no-pager >&2
    exit 1
fi
cat <<EOF

  Website:  https://$DOMAIN   (HTTPS can take 1-2 minutes the first time)
  CMS:      https://admin.$DOMAIN

  Last step: put your NEW Telegram token in the settings file:
      nano $APP/.env
  then save (Ctrl+O, Enter, Ctrl+X) and run:
      systemctl restart amani

EOF
