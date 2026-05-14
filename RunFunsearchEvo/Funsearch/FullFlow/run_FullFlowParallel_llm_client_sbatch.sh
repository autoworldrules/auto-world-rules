#!/bin/bash
#SBATCH --job-name=fullflow-eval
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=72
#SBATCH --mem=60G
#SBATCH --gpus=1
#SBATCH --time=23:55:00
#SBATCH --chdir=.
#SBATCH --output=Funsearch/Logs/RoundRuns/%x.%j.out
#SBATCH --error=Funsearch/Logs/RoundRuns/%x.%j.err
#
# NOTE: SBATCH log paths are resolved relative to the directory you run
# `sbatch` from (SLURM_SUBMIT_DIR). Submit this script from inside the
# RunFunsearchEvo/ directory so logs land under
# RunFunsearchEvo/Funsearch/Logs/RoundRuns/.

set -euo pipefail

# Resolve repository root. Under SLURM, BASH_SOURCE points to a copy under
# /var/spool/slurmd, so we cannot rely on it. Strategy:
#   1. Honour an explicit REPO_ROOT override.
#   2. Otherwise walk up from SLURM_SUBMIT_DIR looking for the package marker
#      (Funsearch/FullFlow/FullFlowParallel_llm_client.py).
#   3. Fall back to BASH_SOURCE for direct shell invocations (no SLURM).
REPO_MARKER="Funsearch/FullFlow/FullFlowParallel_llm_client.py"
find_repo_root() {
    local d="$1"
    while [ -n "$d" ] && [ "$d" != "/" ]; do
        if [ -f "$d/$REPO_MARKER" ]; then
            echo "$d"
            return 0
        fi
        d="$(dirname "$d")"
    done
    return 1
}
if [ -n "${REPO_ROOT:-}" ]; then
    :
elif [ -n "${SLURM_SUBMIT_DIR:-}" ] && REPO_ROOT="$(find_repo_root "$SLURM_SUBMIT_DIR")"; then
    :
elif [ -n "${SLURM_SUBMIT_DIR:-}" ] && [ -f "${SLURM_SUBMIT_DIR}/RunFunsearchEvo/$REPO_MARKER" ]; then
    REPO_ROOT="${SLURM_SUBMIT_DIR}/RunFunsearchEvo"
else
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
fi
cd "$REPO_ROOT"
if [ ! -f .venv/bin/activate ]; then
    echo "ERROR: .venv/bin/activate not found at $REPO_ROOT" >&2
    echo "Create or symlink .venv inside RunFunsearchEvo/, or export REPO_ROOT." >&2
    exit 1
fi
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
