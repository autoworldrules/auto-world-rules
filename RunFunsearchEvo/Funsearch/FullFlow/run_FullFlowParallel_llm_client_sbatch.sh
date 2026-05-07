#!/bin/bash
#SBATCH --job-name=fullflow-eval
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=72
#SBATCH --mem=60G
#SBATCH --gpus=1
#SBATCH --time=23:55:00
#SBATCH --output=Funsearch/Logs/RoundRuns/%x.%j.out
#SBATCH --error=Funsearch/Logs/RoundRuns/%x.%j.err

set -euo pipefail

# Resolve repository root (parent of Funsearch/) regardless of where sbatch is launched.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"
mkdir -p Funsearch/Logs/RoundRuns

echo "Repo root: $REPO_ROOT"
echo "Job ID: ${SLURM_JOB_ID:-N/A}"
echo "Node: $(hostname)"
echo "Started: $(date)"
echo "CPUs available: $(nproc)"
free -h

# Activate the project virtual environment created via uv (see ENVIRONMENT_SETUP.md).
source .venv/bin/activate

python Funsearch/FullFlow/FullFlowParallel_llm_client.py \
    --config Funsearch/Collaterals/FullFlowconfigs/configAD_served_qwen3-next.json

echo "Finished: $(date)"
