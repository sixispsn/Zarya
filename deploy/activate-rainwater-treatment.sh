#!/bin/sh
# Application-only update. Preserve personal login, data and Caddy.
set -eu
release=/opt/zarya-releases/20261001-rainwater-treatment
previous=/opt/zarya-releases/20260930-rainwater-pump
test "$(readlink -f /opt/zarya-releases/current)" = "$previous"
test ! -e "$release/backup"
test -s "$release/.env"
test -f "$release/smoke-passed"
test "$(docker inspect --format '{{.Config.Image}}' zarya-app-1)" = zarya-release:20260930-rainwater-pump
test "$(docker inspect --format '{{.State.Running}}' zarya-caddy-1)" = true
install -d -m 700 "$release/backup"
paused=0
unpause() { if test "$paused" = 1; then docker unpause zarya-app-1 >/dev/null || true; fi; }
trap unpause EXIT HUP INT TERM
docker pause zarya-app-1 >/dev/null
paused=1
docker run --rm --network none --user 0 --entrypoint tar \
  -v zarya_zarya_projects:/data:ro -v "$release/backup:/backup" \
  zarya-release:20260930-rainwater-pump -czf /backup/projects.tar.gz -C /data .
chmod 600 "$release/backup/projects.tar.gz"
docker unpause zarya-app-1 >/dev/null
paused=0
trap - EXIT HUP INT TERM
checksum=$(sha256sum "$release/backup/projects.tar.gz" | cut -d ' ' -f 1)
python3 "$release/scripts/verify_backup_restore.py" \
  "$release/backup/projects.tar.gz" "$release/restored-pre-treatment" --sha256 "$checksum"
if ! docker compose --env-file "$release/.env" -p zarya \
  -f "$release/compose.yaml" -f "$release/base.override.yaml" -f "$release/release.override.yaml" \
  up -d --no-deps --no-build --wait --wait-timeout 90 app; then
  docker compose --env-file "$previous/.env" -p zarya \
    -f "$previous/compose.yaml" -f "$previous/base.override.yaml" -f "$previous/release.override.yaml" \
    up -d --no-deps --no-build --wait --wait-timeout 90 app
  exit 1
fi
ln -sfn "$release" /opt/zarya-releases/current
docker inspect --format '{{.Config.Image}} {{.State.Health.Status}}' zarya-app-1
