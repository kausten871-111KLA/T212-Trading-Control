# Sprint 9 — Position identity guard (16 October 2026)

Status: **offline tested; source update blocked; NOT deployed**.

## Verified result
- Previous Sprint 8 bundle: 58 tests passed locally before this sprint.
- Four new position-identity regression tests added. Before correction: 3 failed, 1 passed.
- After correction: **62/62 tests passed** using `python -m unittest discover -s tests -v`.
- Python `compileall` passed.
- No Trading 212, model, Contabo or production calls; no broker orders.
- A new development branch was created: `feature/t212-monitor-payload-identity-20261016`.
- The attempt to update `openwebui/tools/position_monitor_core.py` through the GitHub connector was blocked by platform safety checks. **No source commit was made.**

## Fault and tested fix
PR #17's `monitor_once` selects the first position row for a ticker and assumes nested `instrument` is a dictionary. The prior Sprint 7 patch addressed malformed instrument types, but duplicate ticker rows could still select the wrong available quantity. The new patch detects duplicate ticker identities and rejects conflicting top-level/nested ticker claims. Ambiguous positions remain ACTIVE and produce `ambiguous_position_ticker` for broker reconciliation; valid unique positions still proceed according to DeepSeek's registered conditions. No trading strategy is added.

## Integration
Apply the combined Sprint 7 + Sprint 9 patch in the attached local sprint package against PR #17, add `test_monitor_payload_shapes.py` and `test_position_identity_guard.py`, run the 62-test suite, then review and deploy only after broker-adapter acceptance. The earlier Sprint 8 watchdog is a separate, locally tested component and remains undeployed.

## Audio P0
Speech playback and uninterrupted browser conversations remain unverified. The Sprint 6 standalone browser diagnostic is available, but a real browser/device acceptance run and Contabo server access are still required. Do not claim the audio issue resolved.

## Safety / rollback
Development branch only; production unchanged; LIVE remains disabled; no new schedules. Revert the monitor source file to PR #17 blob `96b24dc7fd2edc303e666b3933fa579a69092a27` if the patch fails acceptance.
