# Server-Side Discovery Scheduler — First Cut

## Goal
Run market discovery every 5 minutes without invoking DeepSeek unless a candidate newly qualifies or crosses a movement tier.

## Preferred runtime
Contabo VPS, outside the LLM/WebUI automation layer.

## Initial US-only cadence
- Weekdays only
- Run every 5 minutes during the US session
- The scanner process itself is deterministic
- DeepSeek handoff occurs only from shortlist escalation events

## Process
1. Load T212 instrument cache.
2. Get candidate universe / market snapshot data.
3. Calculate 20-day average volume and derived scanner metrics.
4. Run deterministic gates and ranking.
5. Persist shortlist/rejections to opportunity ledger.
6. Update movement-tier state.
7. Emit only newly-qualified or newly-escalated names to a handoff queue.
8. DeepSeek consumes a bounded number of queued candidates for catalyst research.
9. Run missed-green audit after US close.

## Scheduling options
Preferred: systemd timer or cron on the Contabo host.
Avoid using an LLM automation as the 5-minute clock.

## Safety
- scanner cannot place orders
- queue consumer cannot place orders
- execution remains in the existing T212 DEMO gateway
- LIVE remains disabled
- no blind retry on broker POSTs

## Deployment gate
Do not deploy until:
- current live gateway source is backed up
- branch code is syntax-checked
- Open WebUI persistent volume paths are verified
- scanner inputs are validated against actual Alpaca response shapes
- T212 cache refresh is tested with one read-only call