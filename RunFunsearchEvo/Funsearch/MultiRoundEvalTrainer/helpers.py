"""
Helper utilities for multi-round EdgeTransformer retraining.

Provides modular functions for:
  - Extracting the best priority function from a ProgramsDatabase
  - Generating training CSVs from a priority function
  - Merging multiple CSV sources into a single training set
  - Loading a pretrained EdgeTransformer for evaluation
  - Evaluating a model on a set of test CSVs
"""

import os
import sys
import csv
import ast
import pickle
import logging
from typing import Optional, List, Dict, Any, Tuple

import torch
import pandas as pd
import numpy as np
from functools import partial
from torch.utils.data import DataLoader
from sklearn.metrics import f1_score, accuracy_score

# ---------------------------------------------------------------------------
# Project imports – we rely on the existing Evaluator / DeepMindCodeReference
# packages that are already on ``sys.path`` when running from the project root.
# ---------------------------------------------------------------------------
from DeepMindCodeReference.implementation import programs_database
from Funsearch.Evaluator.model import EdgeTransformer
from Funsearch.Evaluator.eval_utils import (
    StoryDataset,
    StoryDataset2,
    load_rcc8_file_as_dict,
    set_seed,
)
from Funsearch.Evaluator.train import (
    parse_args,
    story_collate,
    load_dataset,
    batch_edges_multi,
    collate,
)
from Funsearch.Collaterals.story_query_generator_nora1_1 import (
    StoryQueryGeneratorNoRa1_1,
)
from Funsearch.Collaterals.PrioStoryGeneratorNoRa1_1 import (
    PrioStoryGeneratorNoRa1_1,
)

# Reference path to unique_labels.pkl shipped with the Evaluator package.
_EVALUATOR_DIR = os.path.join(os.path.dirname(__file__), "..", "Evaluator")
_DEFAULT_UNIQUE_LABELS_PATH = os.path.join(_EVALUATOR_DIR, "unique_labels.pkl")
_DEFAULT_RULES_PATH = os.path.join(
    os.path.dirname(__file__), "..", "Collaterals", "NoRa1.1.txt"
)

# ========================== 1. Database helpers ============================


def extract_best_priority_fn_str(
    database_path: str,
    logger: Optional[logging.Logger] = None,
) -> str:
    """Return the source code of the best priority function in *database_path*.

    Loads the ``ProgramsDatabase`` pickle, iterates over all islands, and
    picks the program with the highest score.  The function body is returned
    as a ready-to-``exec`` string.
    """
    if logger:
        logger.info(f"Loading database from {database_path}")
    db = programs_database.load_programs_database(database_path)

    best_score = float("-inf")
    best_body = None

    for island_id, (prog, score) in enumerate(
        zip(db._best_program_per_island, db._best_score_per_island)
    ):
        if prog is not None and score > best_score:
            best_score = score
            best_body = str(prog)

    if best_body is None:
        raise RuntimeError(
            f"No valid programs found in database at {database_path}"
        )

    if logger:
        logger.info(
            f"Best priority function found on island score={best_score:.6f}"
        )

    return best_body


# ======================== 2. Story / CSV generation ========================


def priority_str_to_fn(priority_fn_str: str):
    """Safely compile a priority-function string and return the callable."""
    namespace: Dict[str, Any] = {}
    exec(priority_fn_str, namespace)  # noqa: S102  – required for FunSearch
    if "priority" not in namespace:
        raise ValueError("Priority function must be named 'priority'")
    return namespace["priority"]


def _generate_single_story(args: tuple) -> tuple:
    """Worker function for parallel story generation (must be top-level for pickling).

    Parameters are packed as a tuple:
        (story_idx, seed, priority_fn_str, min_entities, max_entities, num_cands, rules_path)

    Returns ``(df, None)`` on success, or ``(None, (exc_type_name, exc_message))`` on
    failure so that the caller can retry and log a warning without the pool crashing.
    """
    story_idx, seed, priority_fn_str, min_entities, max_entities, num_cands, rules_path = args
    try:
        priority_fn = priority_str_to_fn(priority_fn_str)
        gen = PrioStoryGeneratorNoRa1_1(
            priority_fn=priority_fn,
            seed=seed,
            min_entities=min_entities,
            max_entities=max_entities,
            num_cands=num_cands,
        )
        story_info = gen.generate_story_from_rules(rules_path)
        query_gen = StoryQueryGeneratorNoRa1_1()
        df_q = query_gen.build_query_dataframe(story_info)
        df_q["story_id"] = story_idx
        return df_q, None
    except Exception as exc:
        return None, (type(exc).__name__, str(exc))


def generate_training_csv(
    priority_fn_str: str,
    output_csv_path: str,
    num_stories: int = 100,
    base_seed: int = 42,
    min_entities: int = 5,
    max_entities: int = 8,
    num_cands: int = 32,
    rules_path: str = None,
    max_workers: Optional[int] = None,
    logger: Optional[logging.Logger] = None,
    min_queries: Optional[int] = None,
) -> str:
    """Generate a CSV of training queries from a priority function.

    Stories are generated in parallel across CPU cores using separate
    processes (each with its own deterministic seed).  Set *max_workers*
    to control parallelism; defaults to ``min(num_stories, os.cpu_count())``.

    If *min_queries* is given and the initial batch of stories produces
    fewer query rows than this threshold, additional stories are generated
    (doubling the batch each iteration) until the threshold is met.

    Returns the *output_csv_path* on success.
    """
    from concurrent.futures import ProcessPoolExecutor

    if rules_path is None:
        rules_path = _DEFAULT_RULES_PATH

    total_stories_generated = 0
    all_dfs: List[pd.DataFrame] = []

    stories_to_generate = num_stories

    while True:
        effective_max_workers = max_workers
        if effective_max_workers is None:
            effective_max_workers = min(stories_to_generate, os.cpu_count() or 1)

        # Build work items with seeds offset by total_stories_generated so
        # additional batches never reuse seeds from earlier ones.
        work_items = [
            (total_stories_generated + idx,
             base_seed + 2 * (total_stories_generated + idx),
             priority_fn_str,
             min_entities, max_entities, num_cands, rules_path)
            for idx in range(stories_to_generate)
        ]

        if logger:
            logger.info(
                f"Generating {stories_to_generate} stories "
                f"({effective_max_workers} workers) → {output_csv_path}"
            )

        with ProcessPoolExecutor(max_workers=effective_max_workers) as pool:
            raw_results = list(pool.map(_generate_single_story, work_items))

        batch_dfs = []
        for i, (df, err) in enumerate(raw_results):
            if err is None:
                batch_dfs.append(df)
                continue
            orig_idx, orig_seed, _, min_e, max_e, nc, rp = work_items[i]
            retry_seed = (orig_seed * orig_seed) % (2 ** 31)
            if logger:
                logger.warning(
                    f"Story {orig_idx} (seed={orig_seed}) failed with "
                    f"{err[0]}: {err[1]}. "
                    f"PrioStoryGeneratorNoRa1_1 args: seed={orig_seed}, "
                    f"min_entities={min_e}, max_entities={max_e}, num_cands={nc}. "
                    f"priority_fn_str (first 200 chars): {priority_fn_str[:200]!r}. "
                    f"Retrying with seed={retry_seed}."
                )
            retry_df, retry_err = _generate_single_story(
                (orig_idx, retry_seed, priority_fn_str, min_e, max_e, nc, rp)
            )
            if retry_err is not None:
                if logger:
                    logger.warning(
                        f"Story {orig_idx} failed again on retry (seed={retry_seed}): "
                        f"{retry_err[0]}: {retry_err[1]}. Skipping this story."
                    )
            else:
                batch_dfs.append(retry_df)

        all_dfs.extend(batch_dfs)
        total_stories_generated += stories_to_generate

        total_queries = sum(len(df) for df in all_dfs)
        if min_queries is None or total_queries >= min_queries:
            break

        # Need more stories — double the batch size for the next iteration
        shortfall = min_queries - total_queries
        if logger:
            logger.info(
                f"Only {total_queries} queries so far (need {min_queries}). "
                f"Generating more stories to reach minimum …"
            )
        stories_to_generate = max(stories_to_generate, stories_to_generate)
        # Estimate: roughly (queries / stories) per story, then overshoot a bit
        if total_stories_generated > 0:
            avg_queries_per_story = total_queries / total_stories_generated
            if avg_queries_per_story > 0:
                stories_to_generate = max(
                    stories_to_generate,
                    int(shortfall / avg_queries_per_story) + 1,
                )

    final_df = pd.concat(all_dfs, ignore_index=True)
    final_df.to_csv(output_csv_path, index=False)

    if logger:
        logger.info(
            f"Saved {len(final_df)} query rows from {total_stories_generated} stories "
            f"to {output_csv_path}"
        )
    return output_csv_path


# ========================= 3. CSV merging =================================


def merge_csvs(
    csv_paths: List[str],
    output_csv_path: str,
    max_final_size: Optional[int] = None,
    seed: int = 42,
    logger: Optional[logging.Logger] = None,
) -> str:
    """Merge several CSVs with equal representation and save to *output_csv_path*.

    Steps:
    1. Load each source CSV.
    2. Find the smallest source (by row count).
    3. Randomly subsample every *other* source down to that size so all
       sources contribute equally.
    4. Re-number ``story_index`` / ``story_id`` per-source so indices are
       globally unique across all sources.
    5. Concatenate all (now equal-sized) frames.
    6. If *max_final_size* is given and the merged result still exceeds it,
       randomly subsample down to *max_final_size* rows.
    7. Write the result to *output_csv_path*.

    Returns the *output_csv_path*.
    """
    frames: list[pd.DataFrame] = []
    for p in csv_paths:
        if not os.path.isfile(p):
            raise FileNotFoundError(f"CSV not found: {p}")
        df = pd.read_csv(p)
        frames.append(df)
        if logger:
            logger.info(f"  loaded {len(df)} rows from {p}")

    # Equalise: subsample larger sources to match the smallest one
    min_rows = min(len(df) for df in frames)
    for i, df in enumerate(frames):
        if len(df) > min_rows:
            if logger:
                logger.debug(
                    f"  Subsampling source {i} ({len(df)} → {min_rows} rows) "
                    f"for equal representation"
                )
            frames[i] = df.sample(n=min_rows, replace=False, random_state=seed)

    # Per-source offsetting: each source's story_index/story_id is shifted so
    # that no two sources share the same value after merging.
    for col in ("story_index", "story_id"):
        offset = 0
        for df in frames:
            if col in df.columns:
                col_min = int(df[col].min())
                df[col] = df[col] - col_min + offset
                offset = int(df[col].max()) + 1

    merged = pd.concat(frames, ignore_index=True)

    if max_final_size is not None and len(merged) > max_final_size:
        if logger:
            logger.info(
                f"  Subsampling merged CSV: {len(merged)} → {max_final_size} rows"
            )
        merged = merged.sample(n=max_final_size, replace=False, random_state=seed)

    merged.to_csv(output_csv_path, index=False)
    if logger:
        logger.info(f"Merged CSV: {len(merged)} rows → {output_csv_path}")
    return output_csv_path


# ====================== 4. Training wrapper ================================


def train_edge_transformer(
    train_csv_path: str,
    model_output_path: str,
    initial_model_path: str = None,
    unique_labels_path: str = None,
    dataset_type: str = "no_ambiguity_v2",
    epochs: int = 100,
    batch_size: int = 32,
    lr: float = 1e-3,
    seed: int = 42,
    log_dir: str = None,
    val_check_interval: int = 10,
    logger: Optional[logging.Logger] = None,
) -> tuple[str, float]:
    """Train an EdgeTransformer from a CSV and save the state-dict.

    Mirrors ``Funsearch/Evaluator/train.py`` but is callable from Python
    (no subprocess) and accepts explicit file paths.

    If *initial_model_path* is provided, the model is initialized from that
    checkpoint before training. This is used for short calibration/fine-tuning
    passes that start from an existing ET rather than from random weights.

    Returns ``(model_output_path, best_val_acc)``.
    """
    import lightning.pytorch as pl

    if unique_labels_path is None:
        unique_labels_path = _DEFAULT_UNIQUE_LABELS_PATH

    set_seed(seed)

    # ---- load unique labels ------------------------------------------------
    with open(unique_labels_path, "rb") as f:
        unique_edge_labels, unique_query_labels = pickle.load(f)

    # ---- remove stale pickle cache so data is freshly parsed ---------------
    pkl_cache = train_csv_path + ".pkl"
    if os.path.exists(pkl_cache):
        os.remove(pkl_cache)
        if logger:
            logger.info(f"Removed stale cache: {pkl_cache}")

    # ---- parse args (defaults) then override what we need ------------------
    cl_args = parse_args([])
    cl_args.dataset_type = dataset_type
    cl_args.epochs = epochs
    cl_args.batch_size = batch_size
    cl_args.lr = lr
    cl_args.seed = seed

    # ---- load & split training data ----------------------------------------
    if logger:
        logger.info(f"Loading training data from {train_csv_path}")

    data = load_rcc8_file_as_dict(train_csv_path)
    from Funsearch.Evaluator.eval_utils import ClutrrDataset

    training_data = ClutrrDataset(
        data, False, False, unique_edge_labels, unique_query_labels
    )

    cl_args.edge_types = training_data.num_edge_labels + 1
    cl_args.target_size = training_data.num_query_labels

    training_len = int(0.8 * len(training_data))
    validation_len = len(training_data) - training_len
    training_set, validation_set = torch.utils.data.random_split(
        training_data, [training_len, validation_len]
    )

    collate_fn = partial(
        collate,
        batch_edges_fn=batch_edges_multi,
        num_edge_types=training_data.num_edge_labels + 1,
    )
    data_params = {
        "batch_size": batch_size,
        "shuffle": False,
        "drop_last": False,
        "num_workers": 8,
    }
    train_loader = DataLoader(training_set, **data_params, collate_fn=collate_fn)
    val_loader = DataLoader(validation_set, **data_params, collate_fn=collate_fn)

    # ---- optimizer / scheduler args ----------------------------------------
    num_training_steps = epochs * len(train_loader)
    cl_args.optimizer_args = {"lr": lr}
    cl_args.scheduler_args = {
        "num_warmup_steps": cl_args.num_warmup_steps,
        "num_training_steps": num_training_steps,
    }

    # ---- train --------------------------------------------------------------
    model = EdgeTransformer(cl_args)
    if initial_model_path is not None:
        if logger:
            logger.info(f"Initializing EdgeTransformer from {initial_model_path}")
        raw = torch.load(initial_model_path, map_location="cpu", weights_only=False)
        state_dict = raw["state_dict"] if isinstance(raw, dict) and "state_dict" in raw else raw
        model.load_state_dict(state_dict)

    pl_logger = None
    if log_dir is not None:
        from lightning.pytorch.loggers import CSVLogger
        pl_logger = CSVLogger(save_dir=log_dir, name="lightning_logs")
        if logger:
            logger.info(f"Lightning logs → {log_dir}/lightning_logs/")

    accelerator = "gpu" if torch.cuda.is_available() else "cpu"
    if torch.cuda.is_available():
        device_str = f"cuda:{torch.cuda.current_device()} ({torch.cuda.get_device_name(torch.cuda.current_device())})"
    else:
        device_str = "cpu"
    if logger:
        logger.info(f"ET training device: {device_str}")

    trainer = pl.Trainer(
        max_epochs=epochs,
        gradient_clip_val=cl_args.max_grad_norm,
        precision=cl_args.precision,
        logger=pl_logger if pl_logger is not None else True,
        accelerator=accelerator,
        devices=1,
        check_val_every_n_epoch=val_check_interval,
        num_sanity_val_steps=0,
    )

    # --- Baseline validation (epoch 0, before any gradient updates) ----------
    if logger:
        logger.info("Running baseline validation (epoch 0, before updates) …")
    baseline_results = trainer.validate(model, val_loader, verbose=False)
    baseline_acc = baseline_results[0].get("val_acc", float("nan")) if baseline_results else float("nan")
    baseline_loss = baseline_results[0].get("val_loss", float("nan")) if baseline_results else float("nan")
    if logger:
        logger.info(
            f"Epoch 0 baseline: val_loss={baseline_loss:.4f}  val_acc={baseline_acc:.4f}  "
            f"(validation every {val_check_interval} epochs)"
        )

    if logger:
        logger.info("Starting training …")

    import time

    start = time.time()
    trainer.fit(model, train_loader, val_loader)
    elapsed = time.time() - start

    # Extract best validation accuracy logged during training
    best_val_acc = float("nan")
    if "val_acc" in trainer.callback_metrics:
        best_val_acc = float(trainer.callback_metrics["val_acc"])

    if logger:
        logger.info(f"Training finished in {elapsed:.1f}s  (val_acc={best_val_acc:.4f})")

    # ---- save model ---------------------------------------------------------
    os.makedirs(os.path.dirname(os.path.abspath(model_output_path)), exist_ok=True)
    torch.save(model.state_dict(), model_output_path)
    if logger:
        logger.info(f"Model saved → {model_output_path}")

    return model_output_path, best_val_acc


# ====================== 5. Evaluation helpers ==============================


def checkpoint_to_path(ckpt_path: str, output_pth_path: str = None) -> str:
    """Convert a Lightning ``.ckpt`` checkpoint to a plain ``.pth`` state-dict file.

    Lightning checkpoints embed ``argparse.Namespace`` hyper-parameters
    (because ``EdgeTransformer.__init__`` calls ``self.save_hyperparameters()``),
    which PyTorch ≥ 2.6 refuses to unpickle with the new ``weights_only=True``
    default.  This function loads the full checkpoint (``weights_only=False``),
    extracts only the ``state_dict`` tensor weights, and saves them as a plain
    ``.pth`` file that is safe to load with ``weights_only=True``.

    Parameters
    ----------
    ckpt_path : str
        Path to the Lightning ``.ckpt`` file.
    output_pth_path : str, optional
        Destination ``.pth`` path.  Defaults to ``ckpt_path`` with the
        ``.ckpt`` extension replaced by ``.pth``.

    Returns
    -------
    str
        Absolute path to the written ``.pth`` file.
    """
    if output_pth_path is None:
        base = ckpt_path[:-5] if ckpt_path.endswith(".ckpt") else ckpt_path
        output_pth_path = base + ".pth"

    # weights_only=False is required because Lightning embeds argparse.Namespace
    # in hyper_parameters.  These files are produced by our own training runs
    # and are trusted sources.
    ckpt = torch.load(ckpt_path, map_location="cpu", weights_only=False)
    if "state_dict" not in ckpt:
        raise ValueError(
            f"{ckpt_path!r} does not look like a Lightning checkpoint "
            f"(no 'state_dict' key).  Keys found: {list(ckpt.keys())}"
        )
    torch.save(ckpt["state_dict"], output_pth_path)
    return output_pth_path


def load_et_model(
    model_path: str,
    unique_labels_path: str = None,
    device: str = "cuda",
) -> Tuple[EdgeTransformer, Any, Any, Any]:
    """Load an EdgeTransformer checkpoint and return (model, cl_args, edge_labels, query_labels).

    Accepts either:

    * A plain ``.pth`` state-dict (saved with ``torch.save(model.state_dict(), …)``).
    * A Lightning ``.ckpt`` checkpoint (auto-saved by ``pl.Trainer``).  The
      ``state_dict`` is extracted automatically; the embedded
      ``argparse.Namespace`` hyper-parameters are ignored (architecture is
      reconstructed from *unique_labels_path* instead).

    The model is moved to *device* (falls back to CPU when CUDA is
    unavailable).
    """
    if unique_labels_path is None:
        unique_labels_path = _DEFAULT_UNIQUE_LABELS_PATH

    with open(unique_labels_path, "rb") as f:
        unique_edge_labels, unique_query_labels = pickle.load(f)

    cl_args = parse_args([])
    cl_args.edge_types = len(unique_edge_labels) + 1
    cl_args.target_size = len(unique_query_labels)

    if device == "cuda" and not torch.cuda.is_available():
        device = "cpu"

    model = EdgeTransformer(cl_args)

    # weights_only=False is required for .ckpt files (Lightning embeds
    # argparse.Namespace in hyper_parameters).  Both file types are produced
    # by our own training code and are trusted sources.
    raw = torch.load(model_path, map_location="cpu", weights_only=False)
    state_dict = raw["state_dict"] if isinstance(raw, dict) and "state_dict" in raw else raw
    model.load_state_dict(state_dict)

    model.eval()
    if device != "cpu":
        model = model.to(device)

    return model, cl_args, unique_edge_labels, unique_query_labels


def _csv_to_story_loader(
    csv_path: str,
    unique_edge_labels: list,
    unique_query_labels: list,
    max_samples: Optional[int] = None,
    logger: Optional[logging.Logger] = None,
) -> DataLoader:
    """Load a CSV (with or without ``story_id``) into a per-story DataLoader.

    If *max_samples* is given and the CSV has more rows, a random sample of
    that many rows is used (sampled at the story level when story IDs exist).
    """
    # remove stale pickle cache
    pkl_cache = csv_path + ".pkl"
    if os.path.exists(pkl_cache):
        os.remove(pkl_cache)

    data = load_rcc8_file_as_dict(csv_path)

    # If no story_id in CSV, add a synthetic one (every row is its own story)
    df = pd.read_csv(csv_path)
    if "story_id" in df.columns:
        data["story_id"] = df["story_id"].tolist()
    elif "story_index" in df.columns:
        data["story_id"] = df["story_index"].tolist()
    else:
        data["story_id"] = list(range(len(data["edges"])))

    # ---- optional sampling ------------------------------------------------
    if max_samples is not None and len(data["edges"]) > max_samples:
        import random as _rng
        n_total = len(data["edges"])
        keep = sorted(_rng.sample(range(n_total), max_samples))
        for key in ("edges", "edge_labels", "query_edge", "query_label"):
            data[key] = [data[key][i] for i in keep]
        data["story_id"] = [data["story_id"][i] for i in keep]
        if logger:
            logger.info(f"  Sampled {max_samples} / {n_total} rows from {csv_path}")

    dataset = StoryDataset2(data, unique_edge_labels, unique_query_labels)
    num_edge_types = len(unique_edge_labels) + 1
    collate_fn = partial(story_collate, num_edge_types=num_edge_types)
    return DataLoader(dataset, batch_size=1, shuffle=False, collate_fn=collate_fn)


def evaluate_model_on_csv(
    model: EdgeTransformer,
    csv_path: str,
    unique_edge_labels: list,
    unique_query_labels: list,
    device: str = "cuda",
    max_samples: Optional[int] = None,
    logger: Optional[logging.Logger] = None,
) -> Dict[str, Any]:
    """Run the model on one test CSV and return per-story metrics.

    If *max_samples* is given, only that many rows are sampled from the CSV.
    On a CUDA error the model automatically falls back to CPU.

    Returns a dict with lists keyed by metric name
    (``acc``, ``macro_f1``, ``micro_f1``, ``loss``).
    """
    loader = _csv_to_story_loader(
        csv_path, unique_edge_labels, unique_query_labels,
        max_samples=max_samples, logger=logger,
    )

    if device == "cuda" and not torch.cuda.is_available():
        if logger:
            logger.warning("CUDA requested but not available — falling back to CPU")
        device = "cpu"

    if logger:
        if device == "cuda":
            logger.info(f"  Using device: cuda ({torch.cuda.get_device_name(0)})")
        else:
            logger.info(f"  Using device: cpu")

    metrics: Dict[str, list] = {
        "acc": [],
        "macro_f1": [],
        "micro_f1": [],
        "loss": [],
    }

    model.eval()
    with torch.no_grad():
        for story_idx, batch in enumerate(loader):
            batch = {
                k: v.to(device) if isinstance(v, torch.Tensor) else v
                for k, v in batch.items()
            }
            try:
                loss, logits = model._calculate_loss(batch)
            except RuntimeError as e:
                if device != "cpu" and ("CUDA" in str(e) or "device-side" in str(e)):
                    if logger:
                        logger.warning(
                            f"CUDA error on story {story_idx}, falling back to CPU: {e}"
                        )
                    torch.cuda.empty_cache()
                    model = model.cpu()
                    device = "cpu"
                    batch = {
                        k: v.cpu() if isinstance(v, torch.Tensor) else v
                        for k, v in batch.items()
                    }
                    loss, logits = model._calculate_loss(batch)
                else:
                    raise

            labels = batch["target_edge_type"].to(logits.dtype)
            preds = (logits.sigmoid() >= 0.5).to(logits.dtype)

            # exact-match accuracy
            acc = (preds == labels).all(dim=1).float().mean().item()
            macro = f1_score(
                labels.cpu().numpy(),
                preds.cpu().numpy(),
                average="macro",
                zero_division=0,
            )
            micro = f1_score(
                labels.cpu().numpy(),
                preds.cpu().numpy(),
                average="micro",
                zero_division=0,
            )

            metrics["acc"].append(acc)
            metrics["macro_f1"].append(macro)
            metrics["micro_f1"].append(micro)
            metrics["loss"].append(loss.item())

    if logger:
        n = len(metrics["acc"])
        logger.info(
            f"  {csv_path}: {n} stories, "
            f"mean_acc={np.mean(metrics['acc']):.4f}, "
            f"mean_macro_f1={np.mean(metrics['macro_f1']):.4f}"
        )

    return metrics


def evaluate_model_on_csvs(
    model_path: str,
    test_csv_paths: List[str],
    unique_labels_path: str = None,
    device: str = "cuda",
    max_samples: Optional[int] = None,
    logger: Optional[logging.Logger] = None,
) -> pd.DataFrame:
    """Evaluate a saved ET model on multiple test CSVs and return a summary DataFrame.

    Each row in the returned DataFrame corresponds to one test CSV and
    contains columns for the file name plus aggregated metrics:
    ``mean_acc``, ``std_acc``, ``mean_macro_f1``, ``std_macro_f1``,
    ``mean_micro_f1``, ``std_micro_f1``, ``mean_loss``, ``std_loss``,
    ``num_stories``.

    If *max_samples* is given, each CSV is down-sampled to at most that
    many rows before evaluation.
    """
    model, cl_args, uel, uql = load_et_model(
        model_path, unique_labels_path, device
    )

    rows: list[dict] = []
    for csv_path in test_csv_paths:
        if not os.path.isfile(csv_path):
            if logger:
                logger.warning(f"Skipping missing file: {csv_path}")
            continue
        if logger:
            logger.info(f"Evaluating on {csv_path} …")

        m = evaluate_model_on_csv(
            model, csv_path, uel, uql, device=device,
            max_samples=max_samples, logger=logger,
        )

        rows.append(
            {
                "test_csv": os.path.basename(csv_path),
                "test_csv_full_path": csv_path,
                "num_stories": len(m["acc"]),
                "mean_acc": float(np.mean(m["acc"])),
                "std_acc": float(np.std(m["acc"])),
                "mean_macro_f1": float(np.mean(m["macro_f1"])),
                "std_macro_f1": float(np.std(m["macro_f1"])),
                "mean_micro_f1": float(np.mean(m["micro_f1"])),
                "std_micro_f1": float(np.std(m["micro_f1"])),
                "mean_loss": float(np.mean(m["loss"])),
                "std_loss": float(np.std(m["loss"])),
            }
        )

    summary_df = pd.DataFrame(rows)
    if logger:
        logger.info(f"\n{summary_df.to_string(index=False)}")
    return summary_df
