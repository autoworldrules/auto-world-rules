#!/bin/bash
#SBATCH --job-name=vllm-serve
#SBATCH --nodes=1
#SBATCH --cpus-per-task=72
#SBATCH --gpus=4
#SBATCH --time=23:55:00
#SBATCH --exclusive
#SBATCH --output=sbatch_server_ini_logs/%x.%j.out

# Resolve repo root from this script's location so the script is portable.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

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

# Site-specific NCCL module. Override NCCL_MODULE for your HPC cluster,
# or leave empty (NCCL_MODULE="") to skip this module load.
NCCL_MODULE="${NCCL_MODULE:-site/nccl}"
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
