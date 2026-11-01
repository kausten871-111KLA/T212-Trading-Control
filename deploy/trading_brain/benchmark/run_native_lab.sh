#!/usr/bin/env bash
# Three-symbol bounded TradingAgents/DeepSeek research experiment.
# --check uses deterministic mocks/no network; --go permits up to 9 provider calls.
set -Eeuo pipefail
umask 077
MODE="$1"
ROOT="/home/katie/t212-brain-benchmark-stage-20261020/deploy/trading_brain/benchmark"
KEY="$HOME/.config/deepseek-runtime/tradingagents-openrouter.key"
IMAGE="local/tradingagents-brain:0.7.0-e8f5503"
EXPECTED_IMAGE="sha256:5bd6450799e67f3f9ef6c20a867b40b45ac86989f85724f12521fe5bffceba52"
test "$(docker image inspect "$IMAGE" --format '{{.Id}}')" = "$EXPECTED_IMAGE"
test -r "$ROOT/native_tradingagents_bounded.py"
test -r "$ROOT/alpaca_eod_20261020_20.json"
test -d "$ROOT/results"
if [[ "$MODE" == "--check" ]]; then
  echo "NATIVE_DEMO_PREFLIGHT: 3 symbols, mocked LLM, no provider spend"
  docker run --rm --network none --read-only --tmpfs /tmp:rw,nosuid,size=64m \
    --security-opt no-new-privileges --cap-drop ALL --cpus 2 --memory 2g \
    --user "$(id -u):$(id -g)" -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 \
    -v "$ROOT:/workspace" -w /workspace "$IMAGE" \
    python native_tradingagents_bounded.py alpaca_eod_20261020_20.json \
      --tickers BRZE MYGN PRSO \
      --output results/tradingagents_native_mock_3symbols.json
  exit 0
fi
if [[ "$MODE" != "--go" ]]; then
  echo "Usage: bash run_native_lab.sh --check | --go" >&2
  exit 2
fi
test -f "$KEY" || { echo "PRIVATE_OPENROUTER_KEY_MISSING: $KEY" >&2; exit 3; }
test "$(stat -c %a "$KEY")" = "600" || {
  echo "OPENROUTER_KEY_FILE_PERMISSIONS_MUST_BE_600" >&2; exit 3;
}
test "$(wc -l < "$KEY")" = "1" || {
  echo "OPENROUTER_KEY_FILE_MUST_BE_ONE_LINE" >&2; exit 3;
}
echo "AUTHORISED RESEARCH: up to 9 DeepSeek/OpenRouter calls; max 550 output tokens/call."
echo "No broker keys or broker network calls are provided to the research container."
docker run --rm --network bridge --read-only --tmpfs /tmp:rw,nosuid,size=64m \
  --security-opt no-new-privileges --cap-drop ALL --cpus 2 --memory 2g \
  --user "$(id -u):$(id -g)" -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 \
  -v "$ROOT:/workspace" \
  --mount "type=bind,src=$KEY,dst=/run/secrets/openrouter,readonly" \
  -w /workspace "$IMAGE" \
  python native_tradingagents_bounded.py alpaca_eod_20261020_20.json \
    --tickers BRZE MYGN PRSO --allow-model-calls \
    --output results/tradingagents_native_real_3symbols.json
echo "NATIVE_REAL_RESEARCH_OUTPUT=$ROOT/results/tradingagents_native_real_3symbols.json"
