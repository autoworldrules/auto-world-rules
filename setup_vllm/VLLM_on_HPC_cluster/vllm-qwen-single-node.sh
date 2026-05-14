#!/bin/bash
#SBATCH --job-name=vllm-serve
#SBATCH --nodes=1
#SBATCH --cpus-per-task=72
#SBATCH --gpus=4
#SBATCH --time=1:45:00
#SBATCH --exclusive
#SBATCH --output=sbatch_server_ini_logs/%x.%j.out

# Resolve repo root. Under SLURM, BASH_SOURCE points to a copy under
# /var/spool/slurmd, so we use SLURM_SUBMIT_DIR (set automatically by sbatch)
# when it contains this package; fall back to BASH_SOURCE for direct shell
# invocations; honour an explicit REPO_ROOT override if set.
if [ -n "${REPO_ROOT:-}" ]; then
    :
elif [ -n "${SLURM_SUBMIT_DIR:-}" ] && [ -f "${SLURM_SUBMIT_DIR}/VLLM_on_HPC_cluster/vllm-qwen-single-node.sh" ]; then
    REPO_ROOT="${SLURM_SUBMIT_DIR}"
elif [ -n "${SLURM_SUBMIT_DIR:-}" ] && [ -f "${SLURM_SUBMIT_DIR}/setup_vllm/VLLM_on_HPC_cluster/vllm-qwen-single-node.sh" ]; then
    REPO_ROOT="${SLURM_SUBMIT_DIR}/setup_vllm"
else
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
fi
cd "${REPO_ROOT}"

if [ ! -f .venv/bin/activate ]; then
    echo "ERROR: .venv/bin/activate not found at ${REPO_ROOT}" >&2
    echo "Create the venv inside setup_vllm/ (see VLLM_on_HPC_cluster/install-commands.sh)," >&2
    echo "or sbatch from the setup_vllm/ directory, or export REPO_ROOT." >&2
    exit 1
fi
source .venv/bin/activate

# Hugging Face cache (override by exporting HF_HOME before sbatch)
export HF_HOME="${HF_HOME:-$HOME/HF_models}"

# Path to a locally downloaded snapshot of the model.
# Override MODEL_PATH if your snapshot hash differs.
export MODEL_PATH="${MODEL_PATH:-$HF_HOME/hub/models--Qwen--Qwen3-Coder-Next/snapshots/a7fbcb5c0e12d62a448eaa0e260346bf5dcc0feb}"
export MODEL_NAME="${MODEL_NAME:-qwen3-next}"
export TENSOR_PARALLELISM_SIZE="${TENSOR_PARALLELISM_SIZE:-4}"

export SERVER_ADDRESS=$(dig +short ${HOSTNAME}-hsn0)
echo "SERVING ON $HOSTNAME with TENSOR_PARALLELISM_SIZE=$TENSOR_PARALLELISM_SIZE"
echo "MODEL_PATH=$MODEL_PATH"
echo "SERVER_ADDRESS=$SERVER_ADDRESS"

# Site-specific NCCL module. Default is empty (no module load); export
# NCCL_MODULE=<your-cluster-nccl-module> before sbatch to load one.
NCCL_MODULE="${NCCL_MODULE:-}"
if [ -n "$NCCL_MODULE" ]; then
    module load "$NCCL_MODULE"
fi
module list

export CC=gcc
export CXX=g++

srun \
    --nodes=$SLURM_NNODES \
    --gpus=$SLURM_GPUS \
    --cpus-per-task 72 \
    --ntasks-per-node 1 \
    vllm serve $MODEL_PATH \
    --served-model-name $MODEL_NAME \
    --max-model-len 16384 \
    --tensor-parallel-size=$TENSOR_PARALLELISM_SIZE \
    --enable-prefix-caching \
    --gpu-memory-utilization=0.9
