# Trading Brain recovered component sprint — 21 October 2026

## Publication and provenance

The eight overnight scheduled tasks reported private ZIP artifacts named:

- `trading_brain_quote_economics_sprint_20261021_0212.zip`
- `trading_brain_momentum_sprint_20261021_0232.zip`
- `trading_brain_finmem_retrieval_sprint_20261021_0611.zip`
- `trading_brain_role_completion_sprint_20261021_0712.zip`

Those task-workspace ZIPs were NOT automatically shared to the Contabo server or committed to GitHub. They could not be found in the current user file library or under the Contabo research worktrees on 21 Oct. **This directory is new, independently reimplemented research code, not a byte-for-byte recovered copy of those unverified packages.** The overnight 159-test claim therefore remains unverified; do not add it to the new test count.

## Files and functions

- `quote_economics.py` — read-only bid/ask and explicitly hypothetical quantity/fee/slippage scenarios, not executable quotes; never a categorical penny-stock rule
- `momentum_features.py` — timestamp-validated close-to-close return, bar-typical-price volume-weighted proxy, and RVOL only if a real comparable-volume baseline is supplied; rejects future or unordered bars
- `finmem_research.py` — independent SQLite short/medium/long memory tiers, immutable original decisions, separately dated outcomes and reflections with point-in-time retrieval excluding all information not yet known
- `evidence_review.py` — annotates the previously recorded BRZE/MYGN/PRSO TradingAgents output; no amendments to model decisions and no automated trade veto
- `offline_replay.py` + `replay_cli.py` — combines the frozen 20-stock snapshot, original DeepSeek baseline, genuine nine-call TradingAgents trial and all four modules into an **offline research-only three-symbol replay**, re-verifying original evidence SHA-256 rather than trusting model-supplied values
- `test_trading_brain_components.py` + `test_offline_replay.py` — **43 independent regression tests PASS** in disconnected Docker on 21 Oct

Original frozen dataset and model outputs remain in the existing sibling `../benchmark/` folder, commit `85db2e8` and earlier. Existing frozen-baseline + trial evidence tests (**16 PASS**) were separately rerun that morning, also disconnected. The two counts are distinct: 43 new; 16 existing; not the overnight claimed 159.

## Test command, on Contabo

```bash
ROOT=/home/katie/t212-brain-benchmark-stage-20261020/deploy/trading_brain
docker run --rm --network none --read-only --tmpfs /tmp:rw,size=100m \
  --security-opt no-new-privileges --cap-drop ALL --cpus 2 --memory 2g \
  -e PYTHONDONTWRITEBYTECODE=1 -e HOME=/tmp \
  -v "$ROOT/components:/workspace:ro" -v "$ROOT/benchmark:/benchmark:ro" \
  -w /workspace local/tradingagents-brain:0.7.0-e8f5503 \
  python -m unittest -q test_trading_brain_components test_offline_replay
```

`43 tests OK`; no provider keys mounted or network access.

## Model findings (not new predictions)

Frozen three-stock trial remains:
- BRZE: existing DeepSeek WAIT vs native TradingAgents HOLD
- MYGN: WAIT vs **BUY**, despite historical reported bid 4.77/ask 6.37 (28.73% spread at midpoint); for 100 shares a hypothetical immediate buy-ask/sell-bid round trip loses 160 units of quote currency **before** added fees/slippage. This is neither a fill nor a forecast
- PRSO: WAIT vs HOLD with historic quoted spread ~27.09%

FinMem's research journal stores these reasoning decisions but has **zero invented broker fills/outcomes**. It does not touch `~/.local/state/deepseek-runtime/trading_state.db` or production model decisions.

## Implementation boundary

**STAGED IN GITHUB ONLY.** This module set does not alter WebUI v0.12.3, existing OPEN/MIDDAY/CLOSE schedules, Contabo broker gateway, autonomous DEMO strategy, or LIVE-disabled settings. It is not FinMem upstream code, not FinRL-X model training and not a second trading agent. No unapproved API spending or demo broker orders.

**Next tested dependency:** Obtain timestamped intraday bars, a verified historical volume reference and primary catalyst references for prospective US session evaluations, then compare them against later outcomes. Only after a prospective cohort and reliable performance metrics should any learning component be proposed for the single existing DeepSeek decision path.
