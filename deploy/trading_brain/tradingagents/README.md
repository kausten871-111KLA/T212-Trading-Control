# TradingAgents integration — Sprint 1

Source: `TauricResearch/TradingAgents` v0.7.0, Apache-2.0.
Pinned upstream commit: `e8f5503e9b86d5c2710b0c76b1f686703968c9df`.

Isolated local image: `local/tradingagents-brain:0.7.0-e8f5503`. This does not replace Open WebUI or the existing T212 DEMO gateway. LIVE remains disabled.

## Build

After verifying `git -C /home/katie/trading-brain-lab/sources/TradingAgents rev-parse HEAD` matches the upstream SHA:

```bash
docker build -f /home/katie/t212-controller-ledger-stage-20261020/deploy/trading_brain/tradingagents/Dockerfile -t local/tradingagents-brain:0.7.0-e8f5503 /home/katie/trading-brain-lab/sources/TradingAgents
```

## Test

```bash
docker run --rm --network none --security-opt no-new-privileges --cap-drop ALL --cpus 2 --memory 3g -e HOME=/home/isolated local/tradingagents-brain:0.7.0-e8f5503
```

Verified on 20 Oct 2026: **1,361 passed, 1 optional skipped, 1 integration excluded, 100 additional subtests passed**. No API keys mounted, inference used or orders placed.

## Provider compatibility

```bash
docker run --rm --network none --read-only --tmpfs /tmp:rw,size=64m --security-opt no-new-privileges -e HOME=/tmp -e OPENROUTER_API_KEY=offline-test-placeholder -v /home/katie/t212-controller-ledger-stage-20261020/deploy/trading_brain/tradingagents/provider_smoke.py:/tmp/provider_smoke.py:ro local/tradingagents-brain:0.7.0-e8f5503 python /tmp/provider_smoke.py
```

Constructs the OpenRouter/DeepSeek model client and verifies its endpoint **without a network request**. The tested runtime resolves `NormalizedChatOpenAI` and `https://openrouter.ai/api/v1`.

## Next sprint

Prepare a bounded, timestamped 20-stock data snapshot and structured `TradingAgents -> DeepSeek decision` JSON for comparison with the existing methodology. Keep the research lab separate from production and prevent unauthorised broker calls. Obtain explicit approval before paid model-inference tests. Pin resolved package dependencies before promotion, rather than relying only on the upstream minimum versions.
