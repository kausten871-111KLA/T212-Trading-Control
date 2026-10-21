# Trading Brain → DeepSeek research-context integration (STAGED)

**Status:** Research-only implementation in GitHub feature branch. The production Open WebUI model and original three US OPEN/MIDDAY/CLOSE automation objects are unchanged.

## Purpose

One bounded, deterministic `trading_brain_research` function accepts actual timestamped market-data JSON from the existing Alpaca/market-data gateway and returns:
- original observed market facts, source attribution and immutable SHA-256 evidence fingerprint
- optional bid/ask spread and quantity scenario (NOT trade-size limits or executable quotes)
- price momentum from supplied historical bars, VWAP **typical-price proxy** and RVOL only with a comparable-volume baseline
- advisory evidence-quality flags, including original model action preserved unchanged
- optional **prior, point-in-time** short/medium/long FinMem research decisions and separately known outcomes (only if an approved DB is mounted)
- explicit missing evidence and primary-source catalyst requests.

This is not a second broker, scheduled job, deep learning model or order router. No authenticated HTTP, model inference, external key, LIVE setting or T212 order API is reachable from the tool code. The tool itself does not fetch data; the model must use existing authorized market tools and provide their truthful responses.

## Files

`components/research_context.py` — pure evidence envelope/quote/volume/memory formatter;
`components/trading_brain_research_tool.py` — staged Open WebUI Tools class;
`components/test_research_context.py` + `test_trading_brain_webui_tool.py` — isolated tests;
`Dockerfile.webui-stage` — pinned *candidate* image built from deployed v0.12.3-lineage image. Build does NOT install/register the tool in the live WebUI database.

The helper imports `quote_economics.py`, `momentum_features.py`, `finmem_research.py`, and `evidence_review.py` from existing, tested source.

## Offline repeatable testing

```bash
ROOT=/home/katie/t212-brain-benchmark-stage-20261020/deploy/trading_brain
docker run --rm --network none --read-only \
  --tmpfs /tmp:rw,size=100m --security-opt no-new-privileges --cap-drop ALL \
  -e PYTHONDONTWRITEBYTECODE=1 -e HOME=/tmp \
  -v "$ROOT/components:/workspace:ro" -v "$ROOT/benchmark:/benchmark:ro" \
  -w /workspace local/tradingagents-brain:0.7.0-e8f5503 \
  python -m unittest -q test_trading_brain_components test_offline_replay \
       test_research_context test_trading_brain_webui_tool
```

This runs **73** tests including 30 new research-context / tool tests, without model/API calls. Before production integration also validate the new tool schema against isolated upstream v0.12.3 and audit input/outputs.

## Candidate build (no production switch)

```bash
docker build --pull=false \
 -f /home/katie/t212-brain-benchmark-stage-20261020/deploy/trading_brain/Dockerfile.webui-stage \
 -t local/open-webui-tradingbrain-candidate:20261021 \
 /home/katie/t212-brain-benchmark-stage-20261020/deploy/trading_brain
```

Build copies research modules into `/app/backend/trading_brain_components/`, adds their directory to Python import path, but **does not update the existing Open WebUI container, tool registry, model binding, or chat prompts**.

## Planned controlled model integration (NOT YET PERFORMED)

1. Inspect the candidate built image and run a real isolated v0.12.3 tool-schema and research-input smoke test with network disabled and a disposable database.
2. Back up WebUI database and existing tool/model bindings. Stage and register the single `trading_brain_research` tool with the existing Trading Operations model *only after user requests this change*.
3. Pass the existing Alpaca JSON snapshot and optional dated bars/real average-volume reference; inspect data quality and model reasoning in one non-executing research test.
4. Confirm all original model T212 gateway bindings, OPEN/MIDDAY/CLOSE automation IDs, DeepSeek phase receipts and LIVE-disabled flag persist.
5. Only then allow the existing single DeepSeek controller to consume the advisory context in a measured DEMO evaluation; no additional hard gates, no duplicate schedules, no unapproved inference spending.

## Limitations

- The original 20-symbol fixture is an EOD research record, **not** fresh/executable quotes.
- No independent raw vendor receipts, exchange verification or corroborated catalysts are added to that fixture.
- The example quantity=100 is only a cost demonstration, not a max order or position cap.
- The typical-price volume-weighted output is a proxy, not transaction-level VWAP.
- Historical average daily volume is not automatically a time-of-day comparable RVOL baseline: use only genuinely comparable references and label source/time window.
- Model-provided JSON may be incomplete or misleading; never label it provider-verified without the original gateway provenance.
- The FinMem database is absent by default, so the tool returns an empty history rather than pretending that simulated outcomes exist.
