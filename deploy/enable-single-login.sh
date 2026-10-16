#!/bin/sh
# Only after smoke and owner access verification. Never remove the personal gate.
set -eu
release=/opt/zarya-releases/20260928-pilot-admin
test "$(readlink -f /opt/zarya-releases/current)" = "$release"
test "$(docker inspect --format '{{.Config.Image}} {{.State.Health.Status}}' zarya-app-1)" = 'zarya-release:20260928-pilot-admin healthy'
docker exec zarya-app-1 python -c 'import os; from pathlib import Path; assert os.environ["ZARYA_PILOT_ENABLED"] == "1"; assert Path("/app/.require-personal-auth").is_file()'
test -s "$release/backup/Caddyfile.before"
# Copy into the existing bind-mounted inode. Do not recreate the Caddy container.
cp "$release/deploy/Caddyfile" /opt/Zarya/deploy/Caddyfile
if ! docker exec zarya-caddy-1 caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile \
  || ! docker exec zarya-caddy-1 caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile; then
  cp "$release/backup/Caddyfile.before" /opt/Zarya/deploy/Caddyfile
  docker exec zarya-caddy-1 caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
  exit 1
fi
docker exec zarya-caddy-1 sha256sum /etc/caddy/Caddyfile
