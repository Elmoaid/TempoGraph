#!/bin/bash
# Daily benchmark runner — maximizes free GitHub Models tokens
# Rate limits (free tier):
#   Low models (gpt-4o-mini, DeepSeek-V3, Llama, Mistral): 150 req/day → 75 examples
#   High models (gpt-4o): 50 req/day → 25 examples
#   Grok-3-Mini: ~30-50 req/day → 15 examples
#   Grok-3: ~15-30 req/day → 8 examples
#
# Crontab: runs 2x daily to catch rolling rate limit resets
#   0 12 * * * /Users/elmoaidali/Desktop/tempograph/bench/run_daily.sh
#   0 0  * * * /Users/elmoaidali/Desktop/tempograph/bench/run_daily.sh

set -euo pipefail
cd /Users/elmoaidali/Desktop/tempograph
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
source .venv/bin/activate

LOG="bench/results/changelocal/daily_$(date +%Y%m%d_%H%M%S).log"

echo "=== Benchmark run $(date) ===" | tee -a "$LOG"

# Model config: "model_id|daily_budget|max_examples"
# daily_budget / 2 conditions = max_examples
MODELS=(
  "openai/gpt-4o-mini|150|75"
  "deepseek/DeepSeek-V3-0324|150|75"
  "meta/Meta-Llama-3.1-70B-Instruct|150|75"
  "openai/gpt-4o|50|25"
  "xai/grok-3-mini|50|15"
  "xai/grok-3|30|8"
  "mistralai/Mistral-Large-2|150|75"
  "ai21/AI21-Jamba-1.5-Large|150|75"
  "cohere/Cohere-command-r-plus-08-2024|150|75"
)

for entry in "${MODELS[@]}"; do
  IFS='|' read -r model budget max_examples <<< "$entry"
  slug=$(echo "$model" | tr '/' '_')

  # Count existing results across all files for this model
  existing=$(cat bench/results/changelocal/github_models_${slug}_*.jsonl 2>/dev/null | wc -l || echo 0)
  existing=$(echo "$existing" | tr -d ' ')

  echo "  $model: $existing results so far (budget: $budget req/day, $max_examples examples/run)" | tee -a "$LOG"

  # Keep accumulating until 500 results per model (enough for statistical power)
  if [ "$existing" -lt 500 ]; then
    echo "  -> Running $model (subset=$max_examples, resume=on)..." | tee -a "$LOG"
    python3 -m bench.changelocal.run_github_models \
      --model "$model" \
      --subset "$max_examples" \
      --resume \
      >> "$LOG" 2>&1 || echo "  -> $model failed or rate-limited (expected)" | tee -a "$LOG"
    echo "  -> Done with $model" | tee -a "$LOG"
  else
    echo "  -> Skipping $model (has $existing results)" | tee -a "$LOG"
  fi
done

echo "=== Finished $(date) ===" | tee -a "$LOG"

# Quick summary
echo "" | tee -a "$LOG"
echo "=== Results summary ===" | tee -a "$LOG"
for f in bench/results/changelocal/github_models_*.jsonl; do
  [ -f "$f" ] || continue
  slug=$(basename "$f" | sed 's/github_models_//;s/_[0-9].*//')
  lines=$(wc -l < "$f")
  echo "  $slug: $lines" | tee -a "$LOG"
done
