# Open WebUI v0.12.4 — supervised security upgrade (25–26 October 2026)

## State: STAGED, NOT INSTALLED

Production remains local/open-webui-toolbinding-v0123-stage:20261020,
image sha256:7d8d04ead2b7c38d99b12b80a777b6030f3c694c491ca93e6bb010b5c3e82483.
Upstream v0.12.4 is pinned at
sha256:a5b9e403d19154796850679c8c5d1295301cee954be8b84ddd62af92426558f7.
The customised staged image is local/open-webui-toolbinding-v0124-stage:20261025,
image sha256:9642e4c6bd781369b1647664cb8d85f254c5e22b5e2bf5538b9d0cb9ea487cf9.

## Verified direct Contabo receipts

- Full Oct 25 data-volume backup: /home/katie/backups/webui-v0124-security-20261025/
  with saved Compose, 238 files, 1.62 GB non-DB data, 86,290,432-byte SQLite
  database with 48 tables. Backup original is untouched.
- V0124_IMAGE_IMPORT_PASS python 3.12.15 custom_files 3 offline True.
- The first isolated copier tried sqlite3.backup() on an already completed
  read-only backup and failed. The corrected network-disabled Docker helper
  reads the root-owned, mode-0600 archived DB from a read-only mount, validates
  internal symlinks and SHA256, and writes only to fresh staging.
- V0124_BACKUP_COPY_PASS tables 48 db_bytes 86290432 backup_preserved True.
- All five active existing jobs have corrected Monday 26 Oct UTC next-runs:
  Morning Research 12:00, US CONTROLLER 13:00, US OPEN 13:35, US MIDDAY 16:30,
  US CLOSE 19:35. No new automations were created.
- Genuine v0.12.4 get_tools resolved all five model-bound tool IDs and 30
  function descriptors. V0124_ISOLATED_DB_PASS automations 5 bound_tools 5
  resolved_functions 30 python 3.12.15 provider_calls 0 broker_orders 0.
- PRODUCTION_UNCHANGED staged_data_only; test exit code 0.
- Exact v0.12.4 restore helper tested against a disposable DB with an injected
  extra table: V0124_ROLLBACK_DRILL_PASS restored_tables 48
  snapshot_unchanged True; PRODUCTION_UNCHANGED rollback_drill_only.
- Official v0.12.4 custom image used as helper to back up the actual live
  volume read-only: ISOLATED_VOLUME_COPY_PASS files 238
  other_file_bytes 1617120758 db_bytes 86290432 tables 48 elapsed_seconds 9.0.
  Original WebUI remained healthy.
- Supervised upgrade script --check passed: V0124_PREFLIGHT_PASS and
  V0124_CHECK_ONLY production_unchanged. Existing services and bridge-token
  presence checked, with no secrets printed.

These receipts do NOT prove production v0.12.4 health, actual scheduled model
inference, broker fills or that the security upgrade is installed. No broker
orders or paid provider calls were made by the staging tests.

## Operator-only supervised deployment

DO NOT RUN --deploy UNATTENDED. The overnight engineering sprint is explicitly
forbidden to switch production. When the user returns and authorises the
supervised change, ensure these three files from the SAME pinned PR head are
installed in /home/katie/webui-v0124-stage-20261025/:

- upgrade_supervised.sh
- v0124_acceptance.py
- v0124_restore_db.py

First run:
  bash /home/katie/webui-v0124-stage-20261025/upgrade_supervised.sh --check

After a successful preflight, operator may explicitly run:
  bash /home/katie/webui-v0124-stage-20261025/upgrade_supervised.sh --deploy

The script takes a fresh online full-volume backup to a new private
/home/katie/backups/webui-v0124-cutover-... directory, saves Compose, swaps
only the image line, recreates the one existing WebUI container, waits for
localhost health, checks five existing jobs and tool bindings and 30+
function descriptors, and verifies the two Contabo user services and bridge
token. A failure after the image switch triggers automatic Compose/SQLite
rollback and recreates original v0.12.3. On success the script prints
V0124_UPGRADE_PASS, BACKUP_DIR and the exact ROLLBACK_CMD.

Rollback restores SQLite only, not other user files in the data volume;
the full-volume backup remains available for manual recovery. The original
WebUI must be stopped before any SQLite restore. Never run the older v0.12.3
cutover script for this version. Keep T212 DEMO strategy autonomy and the
original five automations unchanged; LIVE remains disabled.

## Open checks

- CI at current PR head: initial 25 Oct failure was from four stale unit tests
  that called removed host-side copier functions. The suite was updated to
  exercise the exact in-container COPY_SNAPSHOT source with temporary fixtures.
- After supervised cutover, check the signed-in UI, five scheduled jobs,
  DeepSeek tool bindings, localhost health and existing bridge services.
  Offline function-descriptor resolution is not a broker-execution test.
