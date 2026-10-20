#!/usr/bin/env bash
# Supervised, version-pinned v0.12.3 WebUI switch.
# Production change only when invoked with --deploy; --check is non-mutating.
# Rolls back Compose and SQLite if acceptance fails.
set -Eeuo pipefail
umask 077
ROOT=/home/katie/webui-v0123-stage-20261020
COMPOSE=/home/katie/open-webui/docker-compose.yml
OLD=local/open-webui-toolbinding-stage:20261020
NEW=local/open-webui-toolbinding-v0123-stage:20261020
OLD_ID=sha256:0477e56acd1174ee042f24f21401877a68a5fa6793caa0261c0fb9a025e18f84
NEW_ID=sha256:7d8d04ead2b7c38d99b12b80a777b6030f3c694c491ca93e6bb010b5c3e82483
DATA_VOL=open-webui_open-webui-data
OP="${1:---check}"
BACKUP=""
SWITCHED=0
FINISHED=0
exec 9>"$ROOT/upgrade.lock"
flock -n 9 || { echo "An upgrade already owns this lock"; exit 2; }

check_health() {
  curl -fsS --connect-timeout 3 --max-time 7 http://127.0.0.1:3000/health >/dev/null
}
check_ready() {
  for i in $(seq 1 75); do
    if check_health; then return 0; fi
    sleep 2
  done
  return 1
}
do_rollback() {
  local dir="$1"
  echo "ROLLBACK_START backup=$dir"
  test -d "$dir/data" && test -f "$dir/docker-compose.yml" || {
    echo "Missing backup; manual intervention required"; return 1;
  }
  # Stop upgraded application before replacing SQLite.
  docker compose -f "$COMPOSE" stop open-webui || true
  cp -p "$dir/docker-compose.yml" "$COMPOSE"
  docker run --rm --network none --security-opt no-new-privileges \
    -v "$dir/data:/source:ro" \
    -v "$DATA_VOL:/target" \
    -v "$ROOT/v0123_restore_db.py:/restore.py:ro" \
    "$NEW" python /restore.py
  docker compose -f "$COMPOSE" up -d --no-deps --force-recreate --pull never open-webui
  check_ready
  echo "ROLLBACK_PASS restored_original_image_and_database"
}
on_error() {
  local code=$?
  trap - ERR
  if [[ "$SWITCHED" -eq 1 && "$FINISHED" -ne 1 ]]; then
    echo "UPGRADE_ACCEPTANCE_FAILED - initiating automatic rollback"
    do_rollback "$BACKUP" || echo "ROLLBACK_ERROR - inspect backup path $BACKUP"
  fi
  exit "$code"
}

if [[ "$OP" == "--rollback" ]]; then
  BACKUP="${2:-}"
  [[ "$BACKUP" == /home/katie/backups/webui-v0123-cutover-* ]] || {
    echo "Pass explicit /home/katie/backups/webui-v0123-cutover-... directory"; exit 2;
  }
  do_rollback "$BACKUP"
  exit 0
fi

[[ "$OP" == "--check" || "$OP" == "--deploy" ]] || {
  echo "Usage: bash upgrade_supervised.sh --check | --deploy | --rollback BACKUP_DIR"
  exit 2
}
test -f "$ROOT/stage_webui_data_links.py"
test -f "$ROOT/v0123_restore_db.py"
test -f "$ROOT/v0123_acceptance.py"
test -f "$COMPOSE"
test "$(docker inspect -f '{{.Image}}' open-webui)" = "$OLD_ID"
test "$(docker image inspect -f '{{.Id}}' "$NEW")" = "$NEW_ID"
test "$(docker image inspect -f '{{.Id}}' "$OLD")" = "$OLD_ID"
grep -Fqx "    image: $OLD" "$COMPOSE"
systemctl --user is-active --quiet deepseek-phase.service
systemctl --user is-active --quiet deepseek-command-bridge.service
docker exec open-webui test -r /run/contabo-bridge/bridge.token
check_health
echo "PREFLIGHT_PASS old_image_pinned new_image_pinned health_OK bridge_token_available both_services_running"
if [[ "$OP" == "--check" ]]; then exit 0; fi

# Never reuse a backup path. Snapshot the whole original volume with a consistent
# online SQLite backup while the current production container remains healthy.
BACKUP=/home/katie/backups/webui-v0123-cutover-$(date -u +%Y%m%dT%H%M%SZ)
mkdir -m 700 "$BACKUP"
mkdir -m 700 "$BACKUP/data"
cp -p "$COMPOSE" "$BACKUP/docker-compose.yml"
docker run --rm --network none --security-opt no-new-privileges \
  --cpus 2 --memory 2g \
  -v "$DATA_VOL:/source:ro" \
  -v "$BACKUP/data:/dest" \
  -v "$ROOT/stage_webui_data_links.py:/copy.py:ro" \
  "$NEW" python /copy.py
printf '%s\n' "$BACKUP" > "$ROOT/last_cutover_backup_path"
echo "FULL_BACKUP_PASS $BACKUP"

# Exact one-line image swap; no other Compose keys or .env values changed.
python3 - "$COMPOSE" "$OLD" "$NEW" <<'PY'
from pathlib import Path
import sys,os
p=Path(sys.argv[1])
old="    image: "+sys.argv[2]
new="    image: "+sys.argv[3]
s=p.read_text()
assert s.count(old)==1 and new not in s,"Compose drift"
tmp=p.with_name(".docker-compose.v0123-tmp.yml")
assert not tmp.exists()
tmp.write_text(s.replace(old,new,1))
os.chmod(tmp,p.stat().st_mode & 0o777)
os.replace(tmp,p)
print("COMPOSE_IMAGE_REF_UPDATED_ONLY")
PY
SWITCHED=1
trap on_error ERR
docker compose -f "$COMPOSE" up -d --no-deps --force-recreate --pull never open-webui
check_ready
docker cp "$ROOT/v0123_acceptance.py" open-webui:/tmp/v0123_acceptance.py
docker exec open-webui env PYTHONPATH=/app/backend python /tmp/v0123_acceptance.py \
  >"$BACKUP/acceptance.log" 2>&1
grep -q V0123_ACCEPTANCE_PASS "$BACKUP/acceptance.log"
systemctl --user is-active --quiet deepseek-phase.service
systemctl --user is-active --quiet deepseek-command-bridge.service
docker exec open-webui test -r /run/contabo-bridge/bridge.token
test "$(docker inspect -f '{{.Image}}' open-webui)" = "$NEW_ID"
FINISHED=1
trap - ERR
echo "UPGRADE_PASS v0.12.3 health_OK all_28_tools_resolved three_schedules_intact"
echo "BACKUP_DIR=$BACKUP"
echo "ROLLBACK_CMD=bash $ROOT/upgrade_supervised.sh --rollback $BACKUP"
