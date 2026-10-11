# Rollout guard repair — 11 October 2026

Isolated staging repair based on PR8 bf6ec10274652edf412bde355ea4e58791010a8a. No production or broker access.

Changes: require rollback lease to equal backup owner; reject changed id/name/meta/access_grants before rollback POST; reject metadata/grant edits between apply baseline and final pre-write GET; verify identity/metadata on readback.

Targeted command:
```sh
python3 -m unittest discover -s tests -p 'test_rollout_guard_regression.py' -v
```
Result: Ran 8 tests; OK. Same suite injected with original baseline: 12 subtest assertion failures, 0 errors. Network synthetic; private 0600 backup, valid apply/restore and lost response single-write behavior covered. Historical 195 tests not repeated.

Remaining: actual isolated WebUI router normalization/permission acceptance; no atomic server CAS between final GET and POST, exclusive owner lease remains required. Lease string equality is a local consistency check, not authentication or proof that a writer is active. Gateway risk enforcement is separate and still blocks production rollout.

Next owner: Engineering reviews/cherry-picks this commit into its staging lane, runs targeted suite plus existing isolated router acceptance, then fixes actual risk mutation boundary. No production apply authority from this receipt.
