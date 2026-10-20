#!/usr/bin/env bash
# First-time setup on Amazon Linux 2023 (run as root via sudo)
set -euo pipefail

APP_DIR=/opt/yarlagadda-feeds
mkdir -p "$APP_DIR"
chown -R ec2-user:ec2-user "$APP_DIR"

dnf update -y
dnf install -y python3.13 python3.13-pip python3.13-devel gcc git rsync || \
  dnf install -y python3 python3-pip python3-devel gcc git rsync

# Prefer python3.13 if present
if command -v python3.13 >/dev/null 2>&1; then
  PY=python3.13
else
  PY=python3
fi

sudo -u ec2-user bash -lc "
  cd $APP_DIR
  $PY -m venv .venv
  .venv/bin/pip install --upgrade pip
  .venv/bin/pip install -r requirements.txt
"

if [[ ! -f $APP_DIR/.env ]]; then
  JWT=$(openssl rand -hex 32)
  cat > "$APP_DIR/.env" <<EOF
ENVIRONMENT=production
DATABASE_URL=sqlite:////opt/yarlagadda-feeds/data/yarlagadda_feeds.db
JWT_SECRET_KEY=$JWT
CORS_ORIGINS=*
ADMIN_USERNAME=admin
ADMIN_PASSWORD=admin123
EOF
  mkdir -p "$APP_DIR/data"
  chown -R ec2-user:ec2-user "$APP_DIR"
fi

cp "$APP_DIR/deploy/yarlagadda-feeds.service" /etc/systemd/system/yarlagadda-feeds.service
systemctl daemon-reload
systemctl enable yarlagadda-feeds
systemctl restart yarlagadda-feeds
systemctl --no-pager status yarlagadda-feeds || true
