# setup_vllm — Local vLLM model server for the FunSearch pipeline

This directory contains the minimum files required to launch an
OpenAI-compatible **vLLM** server on an Isambard-AI Phase 2 GPU node so the
`RunFunsearchEvo` FullFlow client can send queries to it.

## Layout

```
setup_vllm/
├── README.md                          (this file)
├── requirements.txt                   pinned vllm + ray + openai
├── test_model_call_with_curl.sh       sanity check via curl
├── test_model_call_with_python.py     sanity check via openai client
├── sbatch_server_ini_logs/            SLURM stdout/stderr land here
└── VLLM_on_Isambard/
    ├── install-commands.sh            one-shot environment bootstrap
    └── vllm-qwen-single-node.sh       SBATCH entrypoint (4 GPUs, 1 node)
```

## 1. Prerequisites

- Isambard-AI Phase 2 GPU node (4 × NVIDIA Grace-Hopper).
- `module` system providing `cudatoolkit` and `brics/nccl`.
- [`uv`](https://docs.astral.sh/uv/) for environment management.
- A Hugging Face cache containing the target model snapshot. The default
  script expects `Qwen/Qwen3-Coder-Next` under `~/HF_models/hub/`.

If you do not yet have a Hugging Face cache, set `HF_HOME` to a writable
location and pre-download the model on a login or compute node, e.g.:

```bash
export HF_HOME=$HOME/HF_models
huggingface-cli download Qwen/Qwen3-Coder-Next
```

## 2. Create the virtual environment

From inside `setup_vllm/`:

```bash
module load cudatoolkit
# Optional, only if uv is not installed:
# curl -LsSf https://astral.sh/uv/install.sh | sh

uv venv --seed --python=3.12

srun --gpus=1 --pty bash -c "
    source .venv/bin/activate
    uv pip install -U vllm[flashinfer]==0.15.1 ray[default] \
        --torch-backend=auto \
        --extra-index-url https://wheels.vllm.ai/0.15.1/vllm
    uv pip install openai
"
```

The bootstrap above is also packaged as
[VLLM_on_Isambard/install-commands.sh](VLLM_on_Isambard/install-commands.sh)
and pinned in [requirements.txt](requirements.txt).

A different vLLM version may be needed for newer models — adjust the version
pin and the `--extra-index-url` accordingly.

## 3. Launch the server

From inside `setup_vllm/`:

```bash
sbatch VLLM_on_Isambard/vllm-qwen-single-node.sh
```

What the script does:

- Requests 1 node, 4 GPUs, exclusive, 23h55m.
- Activates `./.venv` (paths are derived from the script location, so the
  script is portable as long as it is run from the `setup_vllm/` tree).
- Loads `brics/nccl`.
- Reads `HF_HOME`, `MODEL_PATH`, `MODEL_NAME`, `TENSOR_PARALLELISM_SIZE`
  from the environment (with sensible defaults) so you can override without
  editing the script:

  ```bash
  HF_HOME=$HOME/HF_models \
  MODEL_PATH=$HOME/HF_models/hub/models--Qwen--Qwen3-Coder-Next/snapshots/<HASH> \
  MODEL_NAME=qwen3-next \
  TENSOR_PARALLELISM_SIZE=4 \
      sbatch VLLM_on_Isambard/vllm-qwen-single-node.sh
  ```

- Runs `vllm serve` with `--max-model-len 16384`, `--enable-prefix-caching`,
  and `--gpu-memory-utilization 0.9`.

SBATCH stdout is written to `sbatch_server_ini_logs/<jobname>.<jobid>.out`.

Loading the weights takes a few minutes (~5 min for Qwen3-Coder-Next 80B).
Wait for vLLM to print `Uvicorn running on ...` before sending requests.

## 4. Find the serving node and port

The server listens on port `8000` of the allocated compute node. To find
the node name:

```bash
squeue --me
# JOBID  ...  NODELIST
# 12345  ...  nid011187
```

Then the OpenAI-compatible base URL is:

```
http://<NODE_ID>:8000/v1     # e.g. http://nid011187:8000/v1
```

This is the value to plug into the FullFlow config field `llm.base_url`
in the companion `RunFunsearchEvo` release.

## 5. Verify the endpoint

From any compute node that can reach the serving node (e.g. start one with
`srun --gpus=1 --pty /bin/bash --login`):

### curl

```bash
bash test_model_call_with_curl.sh qwen3-next "Hello" --host nid011187 --port 8000
```

### Python (openai client)

```bash
source .venv/bin/activate
BASE_URL="http://nid011187:8000/v1" MODEL_NAME=qwen3-next \
    python test_model_call_with_python.py
```

A successful run prints a model-generated answer.

## 6. Notes

- The `--exclusive` flag in the SBATCH header reserves the whole node;
  remove it if your scheduler policy disallows exclusive jobs.
- For multi-node serving, increase `--nodes` and adjust
  `TENSOR_PARALLELISM_SIZE` / Ray launch flags accordingly. This release
  ships only the single-node script.
- `module load brics/nccl` is Isambard-specific; on other clusters replace
  it with the equivalent NCCL/CUDA module stack.
