## auto-research

Isolated, end-to-end **priority-function → NoRA1.1 CSV → EdgeTransformer train → eval → multi-round records**
pipeline (no ProgramsDatabase, no FunSearch evolution loop).

### Install

This repo already contains the dependencies needed for ET training + clingo.
Recommended (from repo root):

```bash
uv sync --extra gpu
```

### What you edit each round

- `auto-research/priority_fns/round_<k>.py`
  - Must define `priority(cand_fact, definite_rules_program, entailed_facts, facts_program) -> float`

### Run (single round primitives)

From repo root:

```bash
python auto-research/scripts/generate_csv.py --priority_fn auto-research/priority_fns/round_0.py --out auto-research/out/base_train.csv --num_stories 100
python auto-research/scripts/train_et.py --train_csv auto-research/out/base_train.csv --out_model auto-research/out/model.pth
python auto-research/scripts/evaluate_et.py --model_path auto-research/out/model.pth --test_csvs auto-research/out/base_train.csv
```

### Run (multi-round)

The multi-round runner mirrors the existing `post_round_processing.py` artifact names:
each round directory contains `best_priority_fn.py`, `eval.csv`, `base_train.csv`,
`final_train.csv`, `model.pth`, `eval_summary.csv`, plus Lightning logs.

```bash
python auto-research/scripts/run_multiround.py \
  --run_dir auto-research/out/run_001 \
  --rounds 3 \
  --priority_fns_dir auto-research/priority_fns \
  --alt_training_sources_init Funsearch/Evaluator/train_no_ambig.csv
```

