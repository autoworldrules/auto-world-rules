"""
train_evaluator_for_next_round.py
=================================
End-to-end script that trains a fresh EdgeTransformer model for the next
FunSearch round.

Inputs
------
a. ``--outputs_dir`` *(required)* – root directory for run outputs.  A
   datetime-named sub-directory (``YYYYMMDD_HHMMSS/``) is created inside;
   all outputs are written there.
b. ``--database_path`` – path to a ProgramsDatabase pickle.  The best
   priority function is extracted automatically and used to generate the
   base training CSV.  *Optional* – when omitted the training data comes
   exclusively from ``--alt_training_sources``.
c. Story-generation parameters (``--num_stories``, ``--base_seed``,
   ``--min_entities``, ``--max_entities``, ``--num_cands``).
d. ``--alt_training_sources`` – zero or more additional CSVs.  Each is
   sampled to at most N_o rows (without replacement), where N_o equals the
   number of queries generated from the database source, or the size of the
   smallest alt source when no database is provided.
e. ``--epochs`` – number of training epochs (default: ``100``).
f. ``--base_csv_name`` – filename for the base (pre-merge) CSV inside the
   run dir (default: ``base_train.csv``).
f. ``--train_csv_path`` – filename for the final merged training CSV inside
   the run dir (default: ``final_train.csv``).
g. ``--model_output_path`` – filename for the saved ``.pth`` state-dict
   inside the run dir (default: ``model.pth``).
h. ``--unique_labels_path`` – path to ``unique_labels.pkl``
   (defaults to ``Funsearch/Evaluator/unique_labels.pkl``).

Sampling & merging
------------------
``final_train.csv`` is assembled as follows:

1. **Database source** (if ``--database_path`` is given): stories are
   generated with the best priority function and saved as ``base_train.csv``.
   The number of rows produced is recorded as N_o.
2. **Alt sources** (if ``--alt_training_sources`` is given): each CSV is
   sampled to ``min(len(source), N_o)`` rows without replacement.  When no
   database is provided, N_o is set to the row count of the smallest alt
   source.
3. All selected frames are concatenated.  ``story_index`` / ``story_id``
   are re-numbered per-source so that story groupings remain globally unique
   in the merged file.
4. If ``--max_final_training_size`` is given and the merged result exceeds
   it, it is randomly subsampled down to that size before saving.
5. The result is written to ``final_train.csv`` inside the run directory.

Usage examples
--------------
Train from a database + 2 extra CSVs::

    python -m Funsearch.MultiRoundEvalTrainer.train_evaluator_for_next_round \\
        --outputs_dir  /data/runs/ \\
        --database_path /data/round3_db.pkl \\
        --num_stories 200 \\
        --alt_training_sources /data/extra1.csv /data/extra2.csv

Train only from existing CSVs (no story generation)::

    python -m Funsearch.MultiRoundEvalTrainer.train_evaluator_for_next_round \\
        --outputs_dir /data/runs/ \\
        --alt_training_sources /data/extra1.csv /data/extra2.csv
from:~/projects/auto-world-rules
python -m Funsearch.MultiRoundEvalTrainer.train_evaluator_for_next_round \
    --outputs_dir Funsearch/MultiRoundEvalTrainer/Testing/ \
    --database_path Funsearch/Logs/programs_db_checkpoint.pkl  --num_stories 3 --num_cands 10 --epochs 80 > eval_log.txt 2>&1

python -m Funsearch.MultiRoundEvalTrainer.train_evaluator_for_next_round \
    --outputs_dir Funsearch/MultiRoundEvalTrainer/Testing/ \
    --database_path Funsearch/Logs/programs_db_checkpoint.pkl \
    --num_stories 80 --num_cands 20 --epochs 200 \
    --alt_training_sources Funsearch/Evaluator/train_no_ambig.csv > eval_log.txt 2>&1

"""

import argparse
import datetime
import logging
import os
import sys

import pandas as pd

# ---------------------------------------------------------------------------
# Ensure project root is on sys.path so package imports work when the script
# is invoked directly (e.g. ``python train_evaluator_for_next_round.py``).
# ---------------------------------------------------------------------------
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from Funsearch.MultiRoundEvalTrainer.helpers import (
    extract_best_priority_fn_str,
    generate_training_csv,
    merge_csvs,
    train_edge_transformer,
)


def _build_logger(log_file: str = None) -> logging.Logger:
    logger = logging.getLogger("MultiRoundEvalTrainer")
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(logging.INFO)
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    if log_file:
        fh = logging.FileHandler(log_file)
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        logger.addHandler(fh)

    return logger


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Train a fresh EdgeTransformer for the next FunSearch round."
    )
    # --- core paths ---
    p.add_argument(
        "--database_path",
        type=str,
        default=None,
        help="Path to ProgramsDatabase pickle. If omitted, no story generation "
        "is performed and training data comes only from --alt_training_sources.",
    )
    p.add_argument(
        "--outputs_dir",
        type=str,
        required=True,
        help="Root directory for run outputs. A datetime-named sub-directory is "
        "created inside; base CSV, final training CSV, and model are written there.",
    )
    p.add_argument(
        "--base_csv_name",
        type=str,
        default="base_train.csv",
        help="Filename for the base (pre-merge) training CSV inside the run dir.",
    )
    p.add_argument(
        "--train_csv_path",
        type=str,
        default="final_train.csv",
        help="Filename (basename) for the final merged training CSV inside the run dir.",
    )
    p.add_argument(
        "--model_output_path",
        type=str,
        default="model.pth",
        help="Filename (basename) for the saved model inside the run dir.",
    )
    p.add_argument(
        "--alt_training_sources",
        nargs="*",
        default=None,
        help="Optional list of CSV paths whose rows are merged into the "
        "training set.",
    )
    p.add_argument(
        "--unique_labels_path",
        type=str,
        default=None,
        help="Path to unique_labels.pkl (defaults to Evaluator/unique_labels.pkl).",
    )

    # --- story generation ---
    p.add_argument("--num_stories", type=int, default=100)
    p.add_argument("--base_seed", type=int, default=42)
    p.add_argument("--min_entities", type=int, default=5)
    p.add_argument("--max_entities", type=int, default=8)
    p.add_argument("--num_cands", type=int, default=25)
    p.add_argument("--rules_path", type=str, default=None)

    # --- training hyper-params ---
    p.add_argument("--epochs", type=int, default=100)
    p.add_argument("--batch_size", type=int, default=32)
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--dataset_type", type=str, default="no_ambiguity_v2")
    p.add_argument(
        "--max_final_training_size",
        type=int,
        default=None,
        help="If set, the final merged training CSV is randomly subsampled to at "
        "most this many rows before training (applied only if the CSV is larger).",
    )

    # --- logging ---
    p.add_argument("--log_file", type=str, default=None)

    return p


def train_evaluator_for_next_round(
    outputs_dir: str,
    database_path: str = None,
    train_csv_path: str = "final_train.csv",
    base_csv_name: str = "base_train.csv",
    model_output_path: str = "model.pth",
    alt_training_sources: list[str] = None,
    unique_labels_path: str = None,
    # story generation
    num_stories: int = 3,
    base_seed: int = 42,
    min_entities: int = 6,
    max_entities: int = 8,
    num_cands: int = 15,
    rules_path: str = None,
    # training
    epochs: int = 100,
    batch_size: int = 32,
    lr: float = 1e-3,
    seed: int = 42,
    dataset_type: str = "no_ambiguity_v2",
    max_final_training_size: int = None,
    logger: logging.Logger = None,
) -> str:
    """Programmatic entry-point (no CLI) – returns the model output path.

    A datetime-named sub-directory is created inside *outputs_dir*; all
    outputs (base CSV, final training CSV, model) are written there.
    *train_csv_path*, *base_csv_name*, and *model_output_path* are used
    as filenames (basenames) within that sub-directory.

    Parameters mirror the CLI flags; see module docstring for details.
    """
    if logger is None:
        logger = _build_logger()

    # ---- Validate that we have *some* data source -------------------------
    has_db = database_path is not None
    has_alt = alt_training_sources is not None and len(alt_training_sources) > 0

    if not has_db and not has_alt:
        raise ValueError(
            "At least one of --database_path or --alt_training_sources must "
            "be provided."
        )

    # ---- Resolve output paths --------------------------------------------
    run_name = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = os.path.join(outputs_dir, run_name)
    os.makedirs(run_dir, exist_ok=True)
    logger.info(f"Run output directory: {run_dir}")

    _base_csv = os.path.join(run_dir, os.path.basename(base_csv_name))
    _final_train_csv = os.path.join(run_dir, os.path.basename(train_csv_path))
    _model_path = os.path.join(run_dir, os.path.basename(model_output_path))

    csvs_to_merge: list[str] = []
    _sampled_csvs: list[str] = []   # intermediate files to clean up after merge

    # ---- Step 1: generate base CSV from priority function (optional) ------
    if has_db:
        logger.info("=" * 60)
        logger.info("STEP 1  Extracting priority fn from database")
        logger.info("=" * 60)
        priority_fn_str = extract_best_priority_fn_str(database_path, logger)
        generate_training_csv(
            priority_fn_str=priority_fn_str,
            output_csv_path=_base_csv,
            num_stories=num_stories,
            base_seed=base_seed,
            min_entities=min_entities,
            max_entities=max_entities,
            num_cands=num_cands,
            rules_path=rules_path,
            logger=logger,
        )
        n_o = len(pd.read_csv(_base_csv))
        logger.info(f"N_o (queries generated from database source): {n_o}")
        csvs_to_merge.append(_base_csv)
    else:
        logger.info("No database_path provided – skipping story generation.")
        # N_o = row count of the smallest valid alt source
        valid_sizes = [
            len(pd.read_csv(src))
            for src in alt_training_sources
            if os.path.isfile(src)
        ]
        if not valid_sizes:
            raise RuntimeError("No valid alt_training_sources found.")
        n_o = min(valid_sizes)
        logger.info(f"N_o (smallest alt source size): {n_o}")

    # ---- Step 2: sample and collect alt sources --------------------------
    if has_alt:
        logger.info("=" * 60)
        logger.info(f"STEP 2  Sampling alt training sources  (N_o={n_o})")
        logger.info("=" * 60)
        _sample_dir = run_dir if run_dir else os.path.dirname(os.path.abspath(_final_train_csv))
        for i, src in enumerate(alt_training_sources):
            if not os.path.isfile(src):
                logger.warning(f"Alt source not found, skipping: {src}")
                continue
            df_src = pd.read_csv(src)
            sample_n = min(len(df_src), n_o)
            df_sampled = df_src.sample(n=sample_n, replace=False, random_state=seed + i)
            sampled_csv = os.path.join(
                _sample_dir, f"sampled_{i:02d}_{os.path.basename(src)}"
            )
            df_sampled.to_csv(sampled_csv, index=False)
            _sampled_csvs.append(sampled_csv)
            csvs_to_merge.append(sampled_csv)
            logger.info(f"  sampled {sample_n}/{len(df_src)} rows from {src}")

    if not csvs_to_merge:
        raise RuntimeError("No CSV data was produced or found – nothing to train on.")

    # ---- Step 3: merge into final training CSV ----------------------------
    logger.info("=" * 60)
    logger.info("STEP 3  Merging CSVs")
    logger.info("=" * 60)
    merge_csvs(
        csvs_to_merge,
        _final_train_csv,
        max_final_size=max_final_training_size,
        seed=seed,
        logger=logger,
    )

    # Clean up intermediate sampled CSVs (base_csv and final_train_csv are kept)
    for p in _sampled_csvs:
        try:
            os.remove(p)
        except OSError:
            pass

    # ---- Step 4: train ----------------------------------------------------
    logger.info("=" * 60)
    logger.info("STEP 4  Training EdgeTransformer")
    logger.info("=" * 60)
    train_edge_transformer(
        train_csv_path=_final_train_csv,
        model_output_path=_model_path,
        unique_labels_path=unique_labels_path,
        dataset_type=dataset_type,
        epochs=epochs,
        batch_size=batch_size,
        lr=lr,
        seed=seed,
        log_dir=run_dir,
        logger=logger,
    )

    logger.info("=" * 60)
    logger.info("DONE")
    logger.info(f"  Run directory : {run_dir}")
    logger.info(f"  Training CSV  : {_final_train_csv}")
    logger.info(f"  Model         : {_model_path}")
    logger.info("=" * 60)

    return _model_path


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = build_arg_parser()
    args = parser.parse_args()

    logger = _build_logger(args.log_file)

    train_evaluator_for_next_round(
        outputs_dir=args.outputs_dir,
        database_path=args.database_path,
        train_csv_path=args.train_csv_path,
        base_csv_name=args.base_csv_name,
        model_output_path=args.model_output_path,
        alt_training_sources=args.alt_training_sources,
        unique_labels_path=args.unique_labels_path,
        num_stories=args.num_stories,
        base_seed=args.base_seed,
        min_entities=args.min_entities,
        max_entities=args.max_entities,
        num_cands=args.num_cands,
        rules_path=args.rules_path,
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
        seed=args.seed,
        dataset_type=args.dataset_type,
        max_final_training_size=args.max_final_training_size,
        logger=logger,
    )
