#!/usr/bin/env bash

set -e

usage() {
  echo "Usage: $0 <model-name> <prompt> [--temp <float>] [--max-tokens <int>] [--port <int>] [--host <hostname>]"
  echo ""
  echo "Example:"
  echo "  $0 qwen3-next \"Explain quantum computing simply.\""
  echo "  $0 qwen3-next \"Hello\" --host nid011187 --port 8000"
  echo ""
  exit 1
}

if [ "$#" -lt 2 ]; then
  usage
fi

MODEL_NAME="$1"
PROMPT="$2"
shift 2

TEMPERATURE=0.7
MAX_TOKENS=200
PORT=8000
HOST="localhost"

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --temp)       TEMPERATURE="$2"; shift 2;;
    --max-tokens) MAX_TOKENS="$2";  shift 2;;
    --port)       PORT="$2";        shift 2;;
    --host)       HOST="$2";        shift 2;;
    *) echo "Unknown option: $1"; usage;;
  esac
done

curl http://${HOST}:${PORT}/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d "{
    \"model\": \"${MODEL_NAME}\",
    \"messages\": [
      {\"role\": \"user\", \"content\": \"${PROMPT}\"}
    ],
    \"temperature\": ${TEMPERATURE},
    \"max_tokens\": ${MAX_TOKENS}
  }"
