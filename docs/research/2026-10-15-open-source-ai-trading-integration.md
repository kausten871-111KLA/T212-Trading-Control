# Open-source trading research integration ? 15 October 2026

Tracked in GitHub Issue #18.

## TradingAgents inspected
- Repository: https://github.com/TauricResearch/TradingAgents
- Upstream HEAD observed: 1394a3f72aa4393e1a98f51b382434c4b4c2d972
- Python entry point checked from source: TradingAgentsGraph(selected_analysts, config);
  graph.propagate(symbol, date) returns the final agent state and a decision.
- Upstream license: Apache 2.0; third-party data rights and dependencies need review.
- Reports: market, sentiment, news, fundamentals, trader thesis and final proposal.
- Upstream LLM provider/model calls can incur costs. Research result does not place orders.

## Implemented prototype
- openwebui/tools/tradingagents_advisory_bridge.py
- Normalizes TradingAgents reports into a stable evidence JSON for DeepSeek.
- Lazy graph import prevents any model calls until explicitly run.
- Does not access Trading 212, its keys or the live controller.
- Network/API-free tests with mock graph: 5 PASS.
- No operational performance improvement claim before comparison.

## Other verified candidates
- Microsoft RD-Agent: https://github.com/microsoft/RD-Agent
- Microsoft Qlib: https://github.com/microsoft/qlib
- FinRL-X: https://github.com/AI4Finance-Foundation/FinRL-Trading
- FinGPT: https://github.com/AI4Finance-Foundation/FinGPT
- AI Hedge Fund: https://github.com/virattt/ai-hedge-fund
- FinRobot: https://github.com/AI4Finance-Foundation/FinRobot

## Next acceptance
1. Evaluate model/backtest dates without future-information leakage.
2. Run the same historical company/date scenarios with and without TradingAgents.
3. Compare catalyst recall, false positives, prediction calibration, broker-confirmed
   outcomes when available, and missed top movers.
4. Record tokens, wall-time, data fees and model provider costs.
5. Let DeepSeek own trading choices; keep the existing single T212 DEMO gateway.
6. Do not change the three US automations or start another broker client.
7. Select additional research sources based on measurable improvement, not hype.

Status: research verified; optional advisory adapter tested; not installed in WebUI;
no paid inference performed or broker orders placed.
