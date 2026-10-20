#!/usr/bin/env bash
# Called on EC2 after files are synced (as ec2-user)
set -euo pipefail
APP_DIR=/opt/yarlagadda-feeds
cd "$APP_DIR"
.venv/bin/pip install -r requirements.txt
mkdir -p data
sudo systemctl restart yarlagadda-feeds
sudo systemctl --no-pager is-active yarlagadda-feeds
curl -sf http://127.0.0.1:8000/health
echo
