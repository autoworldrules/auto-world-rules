# Auto World Rules

Code and data accompanying the conference submission. The repository contains four parts, each with its own README:

| Folder | Contents |
|---|---|
| [`RunFunsearchEvo/`](RunFunsearchEvo/) | The FunSearch evolutionary loop: an LLM evolves priority functions that choose story facts, and the EdgeTransformer is retrained every round. See [`RunFunsearchEvo/README.md`](RunFunsearchEvo/README.md) for environment setup and how to run it. |
| [`auto-research/`](auto-research/) | The same round-based pipeline without FunSearch: a coding agent writes one priority function per round. Includes the priority functions and outputs of three experiments. See [`auto-research/README.md`](auto-research/README.md). |
| [`claude_samplers_and_worlds/`](claude_samplers_and_worlds/) | LLM-written graph samplers and ASP rule sets ("worlds") for generating reasoning benchmarks, with the full generating conversation. See [`claude_samplers_and_worlds/README.md`](claude_samplers_and_worlds/README.md). |
| [`setup_vllm/`](setup_vllm/) | Scripts to serve the LLM used by `RunFunsearchEvo` with vLLM on a SLURM cluster. See [`setup_vllm/README.md`](setup_vllm/README.md). |

`auto-research/` reuses the EdgeTransformer code and Python environment of `RunFunsearchEvo/`.

## Attribution and license

This code is released under the MIT License (see [`LICENSE`](LICENSE)).

It builds on [Potassco / clingo](https://potassco.org/) (MIT License), [google-deepmind/funsearch](https://github.com/google-deepmind/funsearch) (Apache 2.0), and the NoRA benchmark from [When No Paths Lead to Rome: Benchmarking Systematic Neural Relational Reasoning](https://openreview.net/forum?id=HZJiIog5XH) (CC BY-NC 4.0).

See the conference submission for citation details.
