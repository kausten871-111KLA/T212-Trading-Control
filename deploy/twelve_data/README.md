# Twelve Data Global Market Data — Trading Brain Staged Integration

21 October 2026. STAGED in existing GitHub PR #21; not activated in production.

## Purpose
Use the existing authenticated Contabo bridge as an additional market-data input to DeepSeek. No new broker, no second autonomous trading controller, no new schedule, no LIVE trading.

## Twelve Data endpoints and provider cost
- quote (/quote): 1 API credit per symbol.
- time_series (/time_series): 1 API credit per symbol; interval 1min, 5min, 15min, 30min, 1h, 1day or 1week.
- symbol_search (/symbol_search): 1 API credit per request, check exact exchange.
- api_usage (/api_usage): 1 API credit per request, provider plan and quota where available.
- Deliberately excluded market_movers/stocks (100 credits, Pro+), time_series/cross (5 credits, primarily synthetic cross data), and premium fundamentals.

Provider docs: https://twelvedata.com/docs
Credits: https://support.twelvedata.com/en/articles/5713553-control-over-api-usage
Pricing: https://twelvedata.com/pricing

Basic tier currently advertises 8 credits/minute and 800/day, with limited global trial data. UK/Europe/Asia coverage and latency vary with plan. Always report actual provider 403 errors as plan/entitlement limitations, never pretend coverage is available.

## Files
- runtime/deepseek/twelve_data_adapter.py: auth headers, 0600 local credential, cache and SQLite quota reservation, safe response processing.
- runtime/deepseek/host_command_bridge.py: extends existing fixed-name command set with twelve_data_quote, twelve_data_series, twelve_data_search, twelve_data_usage. No broker or shell commands.
- openwebui/tools/twelve_data_webui_tool.py: existing private Unix socket + bridge token, returns market research JSON.
- runtime/deepseek/configure_twelve_data_key.py: hidden prompt writes the key atomically while preserving Alpha Vantage.
- deploy/trading_brain/components/market_gateway_normalizer.py: maps Twelve Data quote and UTC-requested intraday bars to Trading Brain evidence fields; daily dates remain exchange-local.
- deploy/trading_brain/components/research_context.py: includes exchange MIC, source currency and exchange timezone.
- tests/test_twelve_data_adapter.py and tests/test_twelve_data_bridge.py: fake-provider offline security/functional checks.
- deploy/trading_brain/components/test_twelve_data_research_context.py: fake Twelve Data to Trading Brain checks.

## Credential status
The configured host data-api.env contains a TWELVEDATA_API_KEY entry with an EMPTY VALUE as last verified 21 Oct 2026. No real Twelve Data request has succeeded. The API key must never be pasted into chat.

After fetching this commit to Contabo, run in the existing Contabo terminal:
    python3 ~/t212-brain-benchmark-stage-20261020/runtime/deepseek/configure_twelve_data_key.py
The key is typed invisibly; existing Alpha Vantage key is preserved.

## Cost guard
The local client reserves at most 6 API credits per UTC minute and 600 per UTC day, leaving headroom under Basic advertised 8/min and 800/day. These are DATA SPENDING limits, not any restriction on autonomous DEMO positions or trading strategy. Quote cache 30 seconds, intraday/daily series 90 seconds, symbol search 24h; provider headers reported when available. No automatic retries.

## Data semantics
Global symbols require exchange and MIC verification plus currency. Preserve units such as GBX; do not assume GBP. Daily dates are exchange-local; never cast to UTC timestamps. Intraday requests specify UTC. Twelve Data quotes need not include executable bid/ask. Do not fabricate news, RVOL, current quote timestamps or trading fills. Trading 212 DEMO remains the sole broker.

## Safe staged deployment, after API key validated
1. Run both existing controller and Trading Brain test suites in an isolated container.
2. Validate a single provider request, quota remaining and actual plan entitlements.
3. Back up host bridge source and restart only deepseek-command-bridge.service after copying tested code; preserve original bridge token/socket and validate old operations.
4. Back up production WebUI SQLite/model config and register one additive Twelve Data research tool via administrator API; attach it as a fifth tool without removing four current tools, four automations, eight skills, knowledge or original prompt.
5. Upgrade existing Trading Brain normalizer separately with rollback; do not overwrite its currently registered source until tests pass.
6. Supervise one research-only DeepSeek invocation, and verify unchanged T212 DEMO execution settings and LIVE disabled.

NOT YET COMPLETED: live API authentication, host service deployment, WebUI tool registration/binding, or a real DeepSeek Twelve Data research call.
