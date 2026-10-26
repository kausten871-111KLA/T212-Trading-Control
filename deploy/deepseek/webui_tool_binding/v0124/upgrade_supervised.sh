#!/usr/bin/env bash
# SUPERVISED v0.12.4 security upgrade. --check does not switch production.
# --deploy requires explicit operator invocation; never run unattended.
set -Eeuo pipefail
umask 077
ROOT=/home/katie/webui-v0124-stage-20261025
COMPOSE=/home/katie/open-webui/docker-compose.yml
OLD=local/open-webui-toolbinding-v0123-stage:20261020
NEW=local/open-webui-toolbinding-v0124-stage:20261025
OLD_ID=sha256:7d8d04ead2b7c38d99b12b80a777b6030f3c694c491ca93e6bb010b5c3e82483
NEW_ID=sha256:9642e4c6bd781369b1647664cb8d85f254c5e22b5e2bf5538b9d0cb9ea487cf9
DATA_VOL=open-webui_open-webui-data
COPIER=/home/katie/webui-v0123-stage-20261020/stage_webui_data_links.py
RESTORE="$ROOT/v0124_restore_db.py"
ACCEPT="$ROOT/v0124_acceptance.py"
OP="$(echo "$*" | awk '{print $1}')"
BACKUP=""
SWITCHED=0
FINISHED=0
test -d "$ROOT"
exec 9>"$ROOT/upgrade-v0124.lock"
flock -n 9 || { echo "V0124_LOCKED"; exit 2; }

health() { curl -fsS --connect-timeout 3 --max-time 7 http://127.0.0.1:3000/health >/dev/null; }
ready() {
  for i in $(seq 1 75); do
    if health; then return 0; fi
    sleep 2
  done
  return 1
}
rollback() {
  local directory="$1"
  echo "V0124_ROLLBACK_START $directory"
  [[ "$directory" == /home/katie/backups/webui-v0124-cutover-* ]] || return 1
  # on_error invokes rollback() under ||, disabling errexit in Bash.
  # Reject incomplete/untrusted snapshots BEFORE stopping the live writer.
  { test -d "$directory" && test ! -L "$directory" &&
    test -d "$directory/data" && test ! -L "$directory/data" &&
    test -f "$directory/data/webui.db" && test ! -L "$directory/data/webui.db" &&
    test -f "$directory/docker-compose.yml" && test ! -L "$directory/docker-compose.yml" &&
    test -f "$RESTORE" && test -f "$COMPOSE" &&
    test "$(docker image inspect -f '{{.Id}}' "$OLD")" = "$OLD_ID" &&
    grep -Fqx "    image: $OLD" "$directory/docker-compose.yml"; } || {
      echo "V0124_ROLLBACK_BLOCKED invalid_backup_or_image"
      return 1
    }
  # Validate the archived SQLite BEFORE stopping the live writer. The
  # snapshot is root-owned (0600); an isolated no-network Docker helper can
  # inspect it without changing ownership, opening WAL, or touching production.
  # A missing/corrupt/foreign-schema backup must not cause avoidable downtime.
  if ! docker run --rm --network none --read-only --cap-drop ALL \
    --security-opt no-new-privileges --memory 512m \
    -e PYTHONDONTWRITEBYTECODE=1 \
    -v "$directory/data:/source:ro" \
    --entrypoint python "$OLD" -c '
import sqlite3,sys
try:
    db=sqlite3.connect("file:/source/webui.db?mode=ro&immutable=1",uri=True,timeout=10)
    try:
        ok=db.execute("PRAGMA integrity_check").fetchone()[0]=="ok"
        count=db.execute("select count(*) from sqlite_master where type=\x27table\x27").fetchone()[0]
    finally:
        db.close()
    sys.exit(0 if ok and count>=48 else 1)
except (sqlite3.Error, OSError):
    sys.exit(1)
'; then
    echo "V0124_ROLLBACK_BLOCKED invalid_snapshot_sqlite"
    return 1
  fi
  # IMPORTANT: rollback() is invoked under `||` from on_error(), so Bash
  # ignores errexit inside the function. Guard every destructive step
  # explicitly. NEVER restore SQLite if the live writer could still run.
  if ! docker compose -f "$COMPOSE" stop open-webui; then
    echo "V0124_ROLLBACK_BLOCKED could_not_stop_webui"
    return 1
  fi
  if [[ "$(docker inspect -f '{{.State.Running}}' open-webui)" != "false" ]]; then
    echo "V0124_ROLLBACK_BLOCKED webui_still_running"
    return 1
  fi
  cp -p "$directory/docker-compose.yml" "$COMPOSE" || return 1
  docker run --rm --network none --security-opt no-new-privileges \
    --cpus 2 --memory 2g \
    -v "$directory/data:/source:ro" \
    -v "$DATA_VOL:/target" \
    -v "$RESTORE:/restore.py:ro" \
    "$NEW" python /restore.py || return 1
  docker compose -f "$COMPOSE" up -d --no-deps --force-recreate --pull never open-webui || return 1
  ready || return 1
  test "$(docker inspect -f '{{.Image}}' open-webui)" = "$OLD_ID" || return 1
  systemctl --user is-active --quiet deepseek-phase.service || return 1
  systemctl --user is-active --quiet deepseek-command-bridge.service || return 1
  echo "V0124_ROLLBACK_PASS original_image_and_preupgrade_sqlite_restored"
}
on_error() {
  local rc=$?
  trap - ERR
  if [[ "$SWITCHED" == 1 && "$FINISHED" != 1 ]]; then
    echo "V0124_ACCEPTANCE_FAILED; automatic rollback starting"
    rollback "$BACKUP" || echo "V0124_ROLLBACK_ERROR manual intervention required backup=$BACKUP"
  fi
  exit "$rc"
}

if [[ "$OP" == "--rollback" ]]; then
  [[ $# -eq 2 ]] || { echo "Usage: --rollback BACKUP_DIR"; exit 2; }
  # A repeated/manual rollback must never restore a stale snapshot over an
  # already-running original installation. Only a partial/new-image cutover
  # is eligible for recovery. Automatic rollback uses rollback() directly.
  running_id="$(docker inspect -f '{{.Image}}' open-webui)"
  if [[ "$running_id" == "$OLD_ID" ]] &&
     grep -Fqx "    image: $OLD" "$COMPOSE"; then
    echo "V0124_ALREADY_ORIGINAL no_restore_performed"
    exit 0
  fi
  # Do not apply a stale v0.12.4 snapshot to an unrelated later upgrade.
  # Only the original/candidate image pair is eligible for manual recovery.
  if [[ "$running_id" != "$OLD_ID" && "$running_id" != "$NEW_ID" ]] ||
     { ! grep -Fqx "    image: $OLD" "$COMPOSE" &&
       ! grep -Fqx "    image: $NEW" "$COMPOSE"; }; then
    echo "V0124_MANUAL_ROLLBACK_BLOCKED unexpected_image_or_compose"
    exit 2
  fi
  rollback "$2"
  exit 0
fi
[[ "$OP" == "--check" || "$OP" == "--deploy" ]] && [[ $# -eq 1 ]] || {
  echo "Usage: --check | --deploy | --rollback BACKUP_DIR"; exit 2;
}
test -f "$COMPOSE" && test -f "$COPIER" && test -f "$RESTORE" && test -f "$ACCEPT"
test "$(docker inspect -f '{{.Image}}' open-webui)" = "$OLD_ID"
test "$(docker image inspect -f '{{.Id}}' "$OLD")" = "$OLD_ID"
test "$(docker image inspect -f '{{.Id}}' "$NEW")" = "$NEW_ID"
grep -Fqx "    image: $OLD" "$COMPOSE"
test "$(grep -Fc "    image: $OLD" "$COMPOSE")" = 1
test "$(cd /home/katie/open-webui && docker compose config --images)" = "$OLD"
systemctl --user is-active --quiet deepseek-phase.service
systemctl --user is-active --quiet deepseek-command-bridge.service
docker exec open-webui test -r /run/contabo-bridge/bridge.token
health
free_kb=$(df -Pk /home/katie/backups | awk 'NR==2 {print $4}')
[[ "$free_kb" =~ ^[0-9]+$ ]] && (( free_kb > 3*1024*1024 ))
echo "V0124_PREFLIGHT_PASS old_image_healthy candidate_pinned services_active bridge_token_available"
if [[ "$OP" == "--check" ]]; then
  echo "V0124_CHECK_ONLY production_unchanged"
  exit 0
fi

# Production change below. Explicit supervised invocation only.
BACKUP="/home/katie/backups/webui-v0124-cutover-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -m 700 "$BACKUP"
mkdir -m 700 "$BACKUP/data"
cp -p "$COMPOSE" "$BACKUP/docker-compose.yml"
docker run --rm --network none --security-opt no-new-privileges \
  --cpus 2 --memory 2g \
  -v "$DATA_VOL:/source:ro" \
  -v "$BACKUP/data:/dest" \
  -v "$COPIER:/copy.py:ro" \
  "$NEW" python /copy.py >"$BACKUP/snapshot.log" 2>&1
grep -q ISOLATED_VOLUME_COPY_PASS "$BACKUP/snapshot.log"
echo "V0124_FRESH_BACKUP_PASS $BACKUP"
python3 - "$COMPOSE" "$OLD" "$NEW" <<'PY'
from pathlib import Path
import os,sys
p=Path(sys.argv[1])
old="    image: "+sys.argv[2]
new="    image: "+sys.argv[3]
s=p.read_text()
assert s.count(old)==1 and new not in s, "Unexpected Compose drift"
temp=p.with_name(".docker-compose.v0124-tmp.yml")
assert not temp.exists(), "Stale Compose temporary file"
temp.write_text(s.replace(old,new,1))
os.chmod(temp,p.stat().st_mode & 0o777)
os.replace(temp,p)
print("V0124_COMPOSE_IMAGE_ONLY_UPDATED",flush=True)
PY
SWITCHED=1
trap on_error ERR
docker compose -f "$COMPOSE" up -d --no-deps --force-recreate --pull never open-webui
ready
docker cp "$ACCEPT" open-webui:/tmp/v0124_acceptance.py
docker exec open-webui env PYTHONPATH=/app/backend python /tmp/v0124_acceptance.py \
  >"$BACKUP/acceptance.log" 2>&1
grep -q V0124_PRODUCTION_ACCEPTANCE_PASS "$BACKUP/acceptance.log"
systemctl --user is-active --quiet deepseek-phase.service
systemctl --user is-active --quiet deepseek-command-bridge.service
docker exec open-webui test -r /run/contabo-bridge/bridge.token
test "$(docker inspect -f '{{.Image}}' open-webui)" = "$NEW_ID"
FINISHED=1
trap - ERR
echo "V0124_UPGRADE_PASS health_OK five_automations five_tools thirty_functions"
echo "BACKUP_DIR=$BACKUP"
echo "ROLLBACK_CMD=bash $ROOT/upgrade_supervised.sh --rollback $BACKUP"
