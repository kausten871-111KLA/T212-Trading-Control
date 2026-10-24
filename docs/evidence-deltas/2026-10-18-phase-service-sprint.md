# 18 October 2026 — bounded phase service integration sprint

Problem: PR21 modules had no installable supervised process and unresolved
execution events had no reconciliation consumer. Host automation ingress was
an unbound seam.

Corrections published on existing PR21:
- 6e22c1e187592025c7ff1d23c83f5e949368259b: phase service, systemd unit,
  migration online backup, process lock, UNKNOWN receipt reconciliation,
  partial-fill quantity propagation and runtime CI path coverage.
- f45a33a5964b48ad7bd0d76d827392a71410a376: stored-owner/model ingress,
  original-occurrence dedupe, idle-service churn avoidance and rollout guide.
- Follow-up in this evidence commit binds the inspected WebUI get_by_id,
  Users/Config/permission APIs and honours paused existing automations.

Verification:
- Full clean-venv suite at f45a33a: 350 tests passed (stdout alongside).
  Initial ambient environment lacked pinned dependencies and failed; repeated
  in isolated venv with requirements-ci.txt resolved those environment failures.
- GitHub Actions 39170797549 completed SUCCESS for f45a33a.
- Final ingress-specific suite: 6 passed, including paused automation rejection.
- Actual Contabo Python process tests: 4 service + 4 reconciliation passed;
  final f45a33a host verification: 4 service + 5 ingress passed. Overlapping
  counts are NOT additive to full suite. Synthetic temporary DBs, no orders.

Host deployment evidence (engineering component only):
- Detached checkout /home/katie/t212-runtime-service at f45a33a.
- Unit /home/katie/.config/systemd/user/deepseek-phase.service installed.
- DB /home/katie/.local/state/deepseek-runtime/trading_state.db migrated.
- Started: MainPID 1542124, active/running.
- SIGKILL: systemd auto-restarted as PID 1542204, NRestarts=1, active/running.
- Stop/rollback rehearsal: inactive/dead, disabled (not enabled at boot).
- Online DB migration backup integrity passed; backup:
  trading_state.db.pre-migrate-1792361258902151169 in same directory.
- WebUI container remained healthy; no production WebUI files/DB/settings,
  schedules, strategy settings, gateway configuration or broker orders changed.
- loginctl Linger=no: full logout/boot persistence not enabled.
- Server logs use a different displayed timezone; do not interpret their wall
  clock as UK time without conversion.

NOT COMPLETE / remaining critical path:
1. Install ingress into actual WebUI automation invocation with a durable
   original-occurrence ID/timestamp and shared DB access. The adapter is tested
   source; the live automation code has NOT been patched.
2. Implement the actual PHASE_EVENT consumer and completion/outcome retention
   using the existing DeepSeek model/tool pipeline, with no duplicate model or
   broker execution. Streaming task acceptance is not model completion.
3. Inject existing Alpaca Tools and DEMO gateway/journal into supervised workers,
   wire IntentReconciler, retain position/fill/outcome feedback, test full restart
   and end-to-end broker acceptance. Current recovery tests use mocks.
4. Review/activate complete service under a persistent host identity only after
   shared-volume and full integration checks. No new trading schedules.

No autonomous trading completion claim. No paid-model calls. DeepSeek keeps
methodology ownership; LIVE remains disabled. PR17 unchanged.
