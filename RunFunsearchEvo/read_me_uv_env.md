a CPU-only base, and
# ENVIRONMENT SETUP NOTES

## PROCEDURE ON HPC-CLUSTER (Cray + CUDA toolkit modules)

```bash
cd auto-world-rules

# Switch to a compute node in interactive mode
srun --gpus=1 --pty /bin/bash --login

# Make sure there are no preexisting lock file and venv.
rm -rf .venv uv.lock

# Set all environment variables
export CC="/usr/bin/gcc-12"
export CXX="/usr/bin/g++-12"
export CFLAGS="-march=native -O3"
export CXXFLAGS="-march=native -O3"

# Import additional modules
module load cray-python
module load cudatoolkit

uv sync
uv sync --extra gpu --extra llm

# Activate it
source .venv/bin/activate

# Reinstall torch with gpu support
uv pip install --force-reinstall torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128

# Install torch-scatter from source
git clone https://github.com/rusty1s/pytorch_scatter.git
cd pytorch_scatter

uv pip install setuptools
uv pip install --no-build-isolation .
cd ..

# Test
python - <<EOF
import torch
import torch_scatter
from torch_scatter import scatter_min
print("torch:", torch.version)
print("cuda:", torch.version.cuda)
print("cuda available:", torch.cuda.is_available())
print("scatter_min OK")
print("torch-scatter cuda support:", torch_scatter.cuda_version)
EOF
```

---



## PROCEDURE (local --steps)

This project uses a two-step environment setup with uv.

### Step 1: Create a clean CPU-only environment

From the repository root:

Remove any existing environment and lock file:

```bash
rm -rf .venv uv.lock
```

Create the base environment:

```bash
uv sync
```

Activate it:

```bash
source .venv/bin/activate
```

At this point:

- PyTorch is NOT installed
- No CUDA / NVIDIA packages are installed
- This environment works on any machine

### Step 2: Install GPU dependencies (optional)

Deactivate first (recommended):

```bash
deactivate
```

Install the GPU extra:

```bash
uv sync --extra gpu --extra llm
```

Reactivate:

```bash
source .venv/bin/activate
```

This installs:

- torch (CUDA-enabled)
- CUDA runtime libraries
- lightning / pytorch-lightning
- accelerate, bitsandbytes

### Step 3: Install torch-scatter (required)

Install the correct prebuilt PyG wheel:

```bash
uv pip install torch-scatter -f https://data.pyg.org/whl/torch-2.3.0+cu121.html
```

### Step 4: Verify

Test imports:

```bash
python - <<EOF
import torch
from torch_scatter import scatter_min
print("torch:", torch.version)
print("cuda:", torch.version.cuda)
print("cuda available:", torch.cuda.is_available())
print("scatter_min OK")
EOF
```

Run the evaluator:

```bash
python Funsearch/Evaluator/evaluator.py
```

CUDA warnings about NVML or device count may appear on unsupported hardware and are safe to ignore if execution proceeds.



## EXPLANATION (WHY THESE STEPS)

### Why a two-step environment setup is required

GPU dependencies (PyTorch + CUDA) are:

- platform-specific
- hardware-dependent
- fragile during dependency resolution

If GPU packages are installed by default:

- `uv sync` fails on machines without CUDA
- CI and CPU-only systems break
- dependency resolution becomes unreliable

Separating the environment into:

- a CPU-only base, and
- an opt-in GPU extension

keeps the project usable and reproducible across machines.

### Why .uv.toml was needed

CUDA-enabled PyTorch and PyTorch Geometric wheels do NOT live on PyPI.

They are hosted on:

- https://download.pytorch.org
- https://data.pyg.org

.uv.toml explicitly tells uv:

- where to find CUDA-enabled PyTorch wheels
- where to find PyG wheels (torch-scatter)

Without .uv.toml:

- uv cannot resolve CUDA builds
- installs either fail or silently fall back to CPU-only builds

### Why torch-scatter is installed separately

torch-scatter provides compiled C++/CUDA extensions.

Problem:

- torch-scatter does NOT declare torch as a build dependency
- If included in dependencies, it gets built from source during `uv sync`
- The build silently falls back to a CPU extension
- The resulting shared library is ABI-incompatible with PyTorch

This causes runtime errors such as:

- undefined C++ symbols
- failures when importing torch_scatter

Solution:

- Exclude torch-scatter from project dependencies
- Install the prebuilt PyG wheel separately that exactly matches:

	- PyTorch version
	- CUDA version
	- Python version

This guarantees ABI compatibility.

### Why this approach works best

Reasons:

- PyG wheels are hosted outside PyPI
- ABI compatibility is not encoded in metadata
- uv (like pip/poetry) cannot infer the correct wheel automatically
- Source builds default to CPU and break at runtime
- Excluding torch-scatter from dependencies prevents installation conflicts

This is a known limitation across Python package managers.

This approach:

- is explicit
- is robust
- avoids the uninstall/reinstall cycle
- follows PyTorch Geometric’s recommended installation method
- is widely used in real-world PyTorch projects

## Summary

- Base environment: clean, CPU-only, portable
- GPU support: explicit and opt-in
- torch-scatter: installed via correct prebuilt wheel
- Result: stable, reproducible, production-grade setup


