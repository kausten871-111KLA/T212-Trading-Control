"""Construct TradingAgents OpenRouter/DeepSeek provider; no network or inference."""
import os
from tradingagents.llm_clients.factory import create_llm_client
os.environ.setdefault("OPENROUTER_API_KEY", "offline-test-placeholder")
client = create_llm_client("openrouter", "deepseek/deepseek-chat", max_retries=0)
model = client.get_llm()
base = str(getattr(model, "openai_api_base", ""))
assert base.rstrip("/") == "https://openrouter.ai/api/v1"
assert getattr(model, "model_name", None) == "deepseek/deepseek-chat"
print("OPENROUTER_DEEPSEEK_PROVIDER_SMOKE_PASS", type(model).__name__, "no_api_calls")
