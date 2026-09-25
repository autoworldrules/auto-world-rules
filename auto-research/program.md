## Experimental loop (agent-in-the-loop)

This folder implements an **outer-loop over rounds** where a coding agent iterates on a single `priority(...)` function per 
round, then retrains + evaluates an EdgeTransformer (ET) end-to-end.

## The goal and criteria

The goal is to write a priority function that leads to low accuracy scores of the ET on the eval set. The lower the better. All else being equal, simpler is better. A small improvement that adds ugly complexity is not worth it. Conversely, removing something and getting equal or better results is a great outcome — that's a simplification win. When evaluating whether to keep a change, weigh the complexity cost against the improvement magnitude. A 0.001 acc improvement that adds 20 lines of hacky code? Probably not worth it. A 0.001 improvement from deleting code? Definitely keep. An improvement of ~0 but much simpler code? Keep.

**The first run**: Your very first run should always be to establish the baseline, so you will run the training script as is.


### Key idea

- **One round = one priority function** (`priority_fns/round_N.py`)
- That same function is used to:
  - generate `eval.csv` (held-out-ish, via seed offset)
  - generate `base_train.csv` (training data)
  - train a new ET on `final_train.csv` (merged training set)
  - evaluate the new ET (and backfill-evaluate the previous ET on the new round’s `eval.csv`)

There is **no internal proposal loop** over multiple priority functions inside a round (FunSearch/ProgramDB evolution is intentionally removed).

---

## What the agent does each iteration

For round `N`:

1. **Read** previous round artifacts (metrics + data examples).
2. **Decide** a change to `priority(...)` (heuristic tweak, new signals, etc.).
3. **Write** the next priority file: `priority_fns/round_{N}.py`.
4. **Run** exactly one round of the pipeline.

---

## Where to look after each round (artifacts)

All outputs go under a run directory: `RUN_DIR/round_N/`

Each round directory contains:
- **`best_priority_fn.py`**: the exact priority function used for the round (copied from `priority_fns/round_N.py`)
- **`eval.csv`**: evaluation dataset for the round
- **`base_train.csv`**: training dataset generated from the priority function
- **`final_train.csv`**: merged dataset used to train the round’s ET
- **`model.pth`**: trained ET checkpoint for the round
- **`eval_summary.csv`**: evaluation summary table for:
  - `roundN_eval` (this round’s `eval.csv`)
  - `roundN-1_eval` (previous round’s `eval.csv`, if present)
  - `roundN_base_train` and `roundN_final_train`

Run-level tracking:
- **`RUN_DIR/records.pkl`**: list of dicts, one per ET (`et_id`) with metric fields like:
  - `acc_roundN_eval`, `acc_roundN-1_eval`, `acc_roundN_base_train`, `acc_roundN_final_train`
  - `acc_roundN+1_eval` (backfill: previous ET evaluated on the newly produced `eval.csv`)

---

## Commands (recommended “one round at a time” workflow)

### 0) Environment

```bash
source .venv/bin/activate
```

### 1) Create a round priority function

Example: start round 1 from the baseline:

```bash
cp auto-research/priority_fns/round_0.py auto-research/priority_fns/round_1.py
```

Then edit `auto-research/priority_fns/round_1.py`.

### 2) Run exactly one round end-to-end

Use the pretrained initial ET as `ET_0` (recommended):

```bash
python auto-research/scripts/run_multiround.py \
  --run_dir auto-research/out/run_001 \
  --rounds 1 \
  --priority_fns_dir auto-research/priority_fns \
  --init_model_path auto-research/initial_models/ET_0_no_ambig_input_v2.pth
```

This produces:
- `auto-research/out/run_001/round_0/model.pth` (copied ET_0)
- `auto-research/out/run_001/round_1/*` (round 1 artifacts)
- `auto-research/out/run_001/records.pkl`

### 3) Agent analysis step (what to read)

For round 1 analysis, read:
- `auto-research/out/run_001/round_1/eval_summary.csv`
- `auto-research/out/run_001/records.pkl`
- `auto-research/out/run_001/round_1/eval.csv`
- `auto-research/out/run_001/round_1/best_priority_fn.py`

### 4) Propose next priority function

Create the next file (round 2), informed by analysis:

```bash
cp auto-research/priority_fns/round_1.py auto-research/priority_fns/round_2.py
```

Edit `round_2.py`, then run one more round:

```bash
python auto-research/scripts/run_multiround.py \
  --run_dir auto-research/out/run_001 \
  --rounds 1 \
  --priority_fns_dir auto-research/priority_fns \
  --init_model_path auto-research/initial_models/ET_0_no_ambig_input_v2.pth
```

Note: this creates a **new** `round_1` directory again if you reuse `--run_dir` naively.
If you want strict incremental `round_1`, `round_2`, ... in the same `run_dir`, we should add
an explicit “resume/continue from existing run_dir” mode (not implemented yet).

---

## Parameters / defaults

`run_multiround.py` defaults are loaded from:

`/home/user/auto-world-rules/stuff/stuff/auto-world-rules/Funsearch/Collaterals/FullFlowconfigs/configAD_served_qwen3-next.json`

Specifically it uses:
- `multi_round.*` for multi-round training/eval knobs (story counts, ET hyperparams, merge cap, etc.)
- `evaluation.*` for base story generation knobs (entities range, base seed)


## Main idea

The idea is that you are a completely autonomous researcher trying things out. If they work, keep. If they don't, move on. If you feel like you're getting stuck in some way, you can rewind but you should probably do this very very sparingly (if ever).

**NEVER STOP**: Once the experiment loop has begun (after the initial setup), do NOT pause to ask the human if you should continue. Do NOT ask "should I keep going?" or "is this a good stopping point?". The human might be asleep, or gone from a computer and expects you to continue working until the number of rounds are complete or until you are manually stopped. You are autonomous. If you run out of ideas, think harder — read papers referenced in the code, re-read the in-scope files for new angles, try combining previous near-misses, try more radical architectural changes. The loop runs until the human interrupts you, period.