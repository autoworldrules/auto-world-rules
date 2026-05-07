# Install vllm for an HPC cluster GPU node (run from the setup_vllm/ root).

# Load pre-installed CUDA modules
module load cudatoolkit

# Uncomment to install uv if it is not already available
# curl -LsSf https://astral.sh/uv/install.sh | sh

# Create a Python 3.12 virtual environment
uv venv --seed --python=3.12

# Switch to a compute node, activate the environment and install vllm + ray.
# Other vllm versions may be required for the latest models.
srun --gpus=1 --pty bash -c "
    source .venv/bin/activate
    uv pip install -U vllm[flashinfer]==0.15.1 ray[default] \
        --torch-backend=auto \
        --extra-index-url https://wheels.vllm.ai/0.15.1/vllm
    uv pip install openai
"
