# RunFunsearchEvo — Public release for FunSearch evolutionary loop

This is a minimal public snapshot of the `auto-world-rules` codebase, sufficient
to run the multi-round, multi-worker FunSearch evolutionary loop end-to-end via:

```
sbatch Funsearch/FullFlow/run_FullFlowParallel_llm_client_sbatch.sh
```

The full research repository (with analysis tooling, post-database scripts,
plotting, and experiment logs) lives elsewhere; only the files transitively
required by the entry point above are included here.

---

## 1. Repository layout

```
RunFunsearchEvo/
├── pyproject.toml          # uv project definition
├── .uv.toml                # uv index config (PyTorch + PyG wheels)
├── .python-version         # Python 3.11
├── uv.lock                 # locked dependency versions
├── read_me_uv_env.md       # FULL environment setup notes (read this!)
├── ENVIRONMENT_SETUP.md    # Quick-start summary of the .venv setup
│
├── DeepMindCodeReference/  # Vendored DeepMind FunSearch primitives
│   └── implementation/     #   code_manipulation, programs_database, config, evaluator
│
├── WhenNoPathsLeadToRome/  # Clingo / ASP derivation utilities
│   └── utils/              #   clingo_utils, FindDerivationForPositiveProgram, ...
│
└── Funsearch/              # The project source tree
    ├── FullFlow/           #   ENTRYPOINT: FullFlowParallel_llm_client.py + sbatch script
    ├── Evaluator/          #   EdgeTransformer model, training, evaluator, ET checkpoint
    ├── Sampler/            #   vLLM-client sampler + LLM-output post-processor
    ├── Collaterals/        #   Story/query generators, ASP rules, skeleton, configs, train CSVs
    ├── utils/              #   Sharding, parallel workers, config loader, logging, etc.
    ├── MultiRoundEvalTrainer/  # Per-round ET retraining, rescoring, resume logic
    ├── ProgramsDB/         #   Discovery tracking & event consolidation
    ├── LLM/LlmModels/      #   OpenAI-compatible vLLM client wrapper
    └── Logs/RoundRuns/     #   (created at runtime) per-run output directory
```

---

## 2. Setting up the virtual environment

The Python environment is managed with [uv](https://docs.astral.sh/uv/).
**Read [`read_me_uv_env.md`](read_me_uv_env.md) for the authoritative,
step-by-step instructions** (covers a Cray-module HPC cluster and
generic local installs).

Quick summary:

```bash
cd RunFunsearchEvo

# 1. (On the HPC cluster) get an interactive GPU node and load modules
srun --gpus=1 --pty /bin/bash --login
module load cray-python
module load cudatoolkit
export CC="/usr/bin/gcc-12" CXX="/usr/bin/g++-12"
export CFLAGS="-march=native -O3" CXXFLAGS="-march=native -O3"

# 2. Wipe any existing env/lock and rebuild
rm -rf .venv
uv sync                          # CPU base
uv sync --extra gpu --extra llm  # add CUDA torch + lightning + accelerate + bnb

source .venv/bin/activate

# 3. Reinstall a CUDA-matched torch (cluster-matched wheels)
uv pip install --force-reinstall torch torchvision torchaudio \
    --index-url https://download.pytorch.org/whl/cu128

# 4. torch-scatter from source (must match installed torch ABI)
git clone https://github.com/rusty1s/pytorch_scatter.git /tmp/pytorch_scatter
cd /tmp/pytorch_scatter
uv pip install setuptools
uv pip install --no-build-isolation .
cd -

# 5. Sanity check
python - <<'EOF'
import torch, torch_scatter
from torch_scatter import scatter_min
print("torch:", torch.__version__, "cuda available:", torch.cuda.is_available())
print("torch-scatter cuda:", torch_scatter.__version__)
EOF
```

For machines without the Cray module stack, follow the **PROCEDURE (local --steps)**
section in [`read_me_uv_env.md`](read_me_uv_env.md) (uses prebuilt PyG wheels
for cu121 instead of building from source).

---

## 3. Running the pipeline

The entry point is a SLURM batch script:

```bash
sbatch Funsearch/FullFlow/run_FullFlowParallel_llm_client_sbatch.sh
```

This activates `.venv/` and launches:

```bash
python Funsearch/FullFlow/FullFlowParallel_llm_client.py \
    --config Funsearch/Collaterals/FullFlowconfigs/configAD_served_qwen3-next.json
```

Outputs are written under `Funsearch/Logs/RoundRuns/<YYYYMMDD_HHMMSS>/` with
per-round subdirectories containing the program database checkpoints, trained
EdgeTransformer (`model.pth`), best evolved priority function, and
training/evaluation CSVs. See the docstring at the top of
[FullFlowParallel_llm_client.py](Funsearch/FullFlow/FullFlowParallel_llm_client.py)
for the full directory schema.

### Required runtime services

Before launching, open
[`Funsearch/Collaterals/FullFlowconfigs/configAD_served_qwen3-next.json`](Funsearch/Collaterals/FullFlowconfigs/configAD_served_qwen3-next.json)
to review the run settings (number of rounds and cycles per round, sampler
worker count, EdgeTransformer training hyperparameters, prompt template, LLM
endpoint, etc.). The defaults reproduce the runs reported in the paper.

The config is set up for a **served** LLM (vLLM, OpenAI-compatible API). You
must edit `Funsearch/Collaterals/FullFlowconfigs/configAD_served_qwen3-next.json`
and set `llm.base_url` to your vLLM endpoint, e.g.:

```json
"llm": {
    "use_local_llm": false,
    "use_served_llm": true,
    "llm_model": "qwen3-next",
    "base_url": "http://<your-host>:8000/v1"
}
```

If you do not already have a vLLM server, the companion `setup_vllm/` package
(sibling directory in this repository) can spin one up on a sufficiently
powerful SLURM HPC node:

```bash
sbatch ../setup_vllm/VLLM_on_HPC_cluster/vllm-qwen-single-node.sh
```

See `../setup_vllm/README.md` for prerequisites and the resulting endpoint
URL format.

To run without an LLM (random/mock generation, useful for smoke-testing),
set both `use_local_llm` and `use_served_llm` to `false`.

### Resuming an interrupted run

Set `multi_round.resume_run_dir` in the config to the path of a previous
`Funsearch/Logs/RoundRuns/<timestamp>/` directory. The launcher detects the
last fully-completed round and restarts from the next one without retraining.

---


## 4. Citation / contact

This release builds on ideas and/or components associated with [Potassco / clingo](https://potassco.org/), [google-deepmind/funsearch](https://github.com/google-deepmind/funsearch), and the NoRA paper [When No Paths Lead to Rome: Benchmarking Systematic Neural Relational Reasoning](https://openreview.net/forum?id=HZJiIog5XH). These resources are compatible with non-commercial research use when proper attribution is maintained: clingo is distributed under the MIT License, the DeepMind FunSearch software is distributed under Apache 2.0, and the OpenReview paper page indicates a CC BY-NC 4.0 license.

See the conference submission for citation details.
