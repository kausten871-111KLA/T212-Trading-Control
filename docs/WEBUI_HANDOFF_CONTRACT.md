# WebUI durable handoff contract

Every agent/worker writes a compact handoff after meaningful work.

Required fields:
- Workspace
- UTC timestamp
- Completed actions
- Evidence / test result / output path
- Current blockers
- Next actions, ordered
- Human approval required: yes/no

Rules:
1. Never use chat history as the sole system state.
2. Preserve the previous handoff; append/version rather than overwrite history.
3. A failed or partial action is recorded as failed/partial, never complete.
4. Engineering changes reference branch/commit and rollback.
5. Trading handoffs always state DEMO/LIVE status. LIVE must remain disabled until explicitly redesigned and authorised.
6. Content/book handoffs identify source material and current version so parallel agents do not overwrite drafts.
