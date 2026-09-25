#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import os
import pickle
import shutil
import sys
import time
from typing import Any, Dict, List, Optional


def _setup_import_paths() -> None:
    this_dir = os.path.dirname(os.path.abspath(__file__))
    auto_research_root = os.path.abspath(os.path.join(this_dir, ".."))
    repo_root = os.path.abspath(os.path.join(this_dir, "..", ".."))
    sys.path.insert(0, auto_research_root)
    sys.path.insert(0, repo_root)


def _build_logger(log_file: str | None = None) -> logging.Logger:
    logger = logging.getLogger("auto-research.multiround")
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


def _copy_priority_fn(priority_fn_path: str, out_path: str) -> None:
    with open(priority_fn_path, "r", encoding="utf-8") as f:
        src = f.read()
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(src)


def _save_records(records: List[Dict[str, Any]], records_path: str, logger) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(records_path)), exist_ok=True)
    with open(records_path, "wb") as f:
        pickle.dump(records, f)
    logger.info(f"Records saved → {records_path}")


def _init_et0_from_model(
    *,
    init_et_dir: str,
    init_model_path: str,
    records: list[dict],
    logger,
) -> str:
    from auto_research.et.eval import checkpoint_to_path

    os.makedirs(init_et_dir, exist_ok=True)

    src = os.path.abspath(init_model_path)
    if not os.path.isfile(src):
        raise FileNotFoundError(src)

    if src.endswith(".ckpt"):
        src = checkpoint_to_path(src)

    dst = os.path.join(init_et_dir, "model.pth")
    shutil.copyfile(src, dst)
    logger.info(f"Initialized ET_0 from existing model → {dst}")

    records.append(
        {
            "et_id": 0,
            "model_path": dst,
            "priority_fn_path": None,
            "eval_csv": None,
            "base_train_csv": None,
            "final_train_csv": None,
            "et_val_acc": float("nan"),
            "round_duration_s": 0.0,
        }
    )
    return dst


def _train_initial_et(
    *,
    init_et_dir: str,
    alt_training_sources_init: list[str],
    alt_training_sources_everyrnd: Optional[list[str]],
    records: list[dict],
    # training
    epochs: int,
    batch_size: int,
    lr: float,
    training_seed: int,
    dataset_type: str,
    max_final_training_size: Optional[int],
    val_check_interval: int,
    unique_labels_path: Optional[str],
    logger,
) -> str:
    from auto_research.et.merge import merge_csvs
    from auto_research.et.train import train_edge_transformer

    start = time.time()
    os.makedirs(init_et_dir, exist_ok=True)

    seen: set[str] = set()
    all_sources: list[str] = []
    for src in alt_training_sources_init:
        resolved = os.path.abspath(src)
        if resolved not in seen:
            seen.add(resolved)
            all_sources.append(src)
    if alt_training_sources_everyrnd:
        for src in alt_training_sources_everyrnd:
            resolved = os.path.abspath(src)
            if resolved not in seen:
                seen.add(resolved)
                all_sources.append(src)

    valid_sources = [s for s in all_sources if os.path.isfile(s)]
    if not valid_sources:
        raise RuntimeError(
            "No valid CSV sources found for initial ET training. "
            f"Searched: {all_sources}"
        )

    final_train_csv = os.path.join(init_et_dir, "final_train.csv")
    merge_csvs(
        valid_sources,
        final_train_csv,
        max_final_size=max_final_training_size,
        seed=training_seed,
        logger=logger,
    )

    model_path = os.path.join(init_et_dir, "model.pth")
    model_path, et_val_acc = train_edge_transformer(
        train_csv_path=final_train_csv,
        model_output_path=model_path,
        unique_labels_path=unique_labels_path,
        dataset_type=dataset_type,
        epochs=epochs,
        batch_size=batch_size,
        lr=lr,
        seed=training_seed,
        log_dir=init_et_dir,
        val_check_interval=val_check_interval,
        logger=logger,
    )

    duration = time.time() - start
    records.append(
        {
            "et_id": 0,
            "model_path": model_path,
            "priority_fn_path": None,
            "eval_csv": None,
            "base_train_csv": None,
            "final_train_csv": final_train_csv,
            "et_val_acc": et_val_acc,
            "round_duration_s": duration,
        }
    )
    logger.info(f"Initial ET model saved → {model_path}  (val_acc={et_val_acc:.4f})")
    return model_path


def _run_round(
    *,
    round_num: int,
    round_dir: str,
    priority_fn_path: str,
    prev_round_dir: Optional[str],
    prev_final_train_csv: Optional[str],
    alt_training_sources_everyrnd: Optional[list[str]],
    records: list[dict],
    round_start_time: float,
    # story generation
    num_stories_train: int,
    num_stories_eval: int,
    base_seed: int,
    eval_seed_offset: int,
    min_entities: int,
    max_entities: int,
    num_cands: int,
    rules_path: Optional[str],
    # training
    epochs: int,
    batch_size: int,
    lr: float,
    training_seed: int,
    dataset_type: str,
    max_final_training_size: Optional[int],
    val_check_interval: int,
    # eval
    unique_labels_path: Optional[str],
    eval_device: str,
    eval_max_samples: Optional[int],
    logger,
) -> dict:
    from auto_research.et.eval import evaluate_model_on_csvs
    from auto_research.et.merge import merge_csvs
    from auto_research.et.train import train_edge_transformer
    from auto_research.nora.training_csv import generate_training_csv

    logger.info("=" * 80)
    logger.info(f"ROUND {round_num}")
    logger.info("=" * 80)

    os.makedirs(round_dir, exist_ok=True)

    best_priority_fn_out = os.path.join(round_dir, "best_priority_fn.py")
    _copy_priority_fn(priority_fn_path, best_priority_fn_out)
    logger.info(f"Priority function saved → {best_priority_fn_out}")

    eval_csv_path = os.path.join(round_dir, "eval.csv")
    logger.info(
        f"Generating eval.csv ({num_stories_eval} stories, seed={base_seed + eval_seed_offset}) …"
    )
    generate_training_csv(
        priority_fn_path=priority_fn_path,
        output_csv_path=eval_csv_path,
        num_stories=num_stories_eval,
        base_seed=base_seed + eval_seed_offset,
        min_entities=min_entities,
        max_entities=max_entities,
        num_cands=num_cands,
        rules_path=rules_path,
        logger=logger,
    )

    # Backfill: previous ET on this round's eval.csv
    if records and records[-1].get("model_path"):
        prev_et_model = records[-1]["model_path"]
        prev_et_id = records[-1]["et_id"]
        logger.info(
            f"Backfill: evaluating ET_{prev_et_id} (previous) on round {round_num}'s eval.csv …"
        )
        backfill_df = evaluate_model_on_csvs(
            model_path=prev_et_model,
            test_csv_paths=[eval_csv_path],
            unique_labels_path=unique_labels_path,
            device=eval_device,
            max_samples=eval_max_samples,
            logger=logger,
        )
        if not backfill_df.empty:
            records[-1]["acc_roundN+1_eval"] = float(backfill_df.iloc[0]["mean_acc"])

    base_train_csv_path = os.path.join(round_dir, "base_train.csv")
    logger.info(f"Generating base_train.csv ({num_stories_train} stories, seed={base_seed}) …")
    generate_training_csv(
        priority_fn_path=priority_fn_path,
        output_csv_path=base_train_csv_path,
        num_stories=num_stories_train,
        base_seed=base_seed,
        min_entities=min_entities,
        max_entities=max_entities,
        num_cands=num_cands,
        rules_path=rules_path,
        logger=logger,
    )

    csvs_to_merge = [base_train_csv_path]
    if prev_final_train_csv and os.path.isfile(prev_final_train_csv):
        csvs_to_merge.append(prev_final_train_csv)
    if alt_training_sources_everyrnd:
        for src in alt_training_sources_everyrnd:
            if os.path.isfile(src):
                csvs_to_merge.append(src)

    final_train_csv_path = os.path.join(round_dir, "final_train.csv")
    logger.info("Merging CSVs into final_train.csv …")
    merge_csvs(
        csvs_to_merge,
        final_train_csv_path,
        max_final_size=max_final_training_size,
        seed=training_seed,
        logger=logger,
    )

    model_path = os.path.join(round_dir, "model.pth")
    logger.info(
        f"Training EdgeTransformer … (batch_size={batch_size}, epochs={epochs}, val_every={val_check_interval})"
    )
    model_path, et_val_acc = train_edge_transformer(
        train_csv_path=final_train_csv_path,
        model_output_path=model_path,
        unique_labels_path=unique_labels_path,
        dataset_type=dataset_type,
        epochs=epochs,
        batch_size=batch_size,
        lr=lr,
        seed=training_seed,
        log_dir=round_dir,
        val_check_interval=val_check_interval,
        logger=logger,
    )

    logger.info("Evaluating trained model …")
    test_csvs: list[str] = []
    test_csv_labels: list[str] = []

    test_csvs.append(eval_csv_path)
    test_csv_labels.append("roundN_eval")

    if prev_round_dir:
        prev_eval = os.path.join(prev_round_dir, "eval.csv")
        if os.path.isfile(prev_eval):
            test_csvs.append(prev_eval)
            test_csv_labels.append("roundN-1_eval")

    test_csvs.append(base_train_csv_path)
    test_csv_labels.append("roundN_base_train")
    test_csvs.append(final_train_csv_path)
    test_csv_labels.append("roundN_final_train")

    summary_df = evaluate_model_on_csvs(
        model_path=model_path,
        test_csv_paths=test_csvs,
        unique_labels_path=unique_labels_path,
        device=eval_device,
        max_samples=eval_max_samples,
        logger=logger,
    )

    # Also evaluate ET_0 (baseline) on the same CSVs, if available.
    # This is useful for an agent: it can compare the current ET against the initial model.
    et0_model_path = records[0].get("model_path") if records else None
    if et0_model_path and os.path.isfile(et0_model_path):
        logger.info("Evaluating ET_0 baseline model …")
        et0_df = evaluate_model_on_csvs(
            model_path=et0_model_path,
            test_csv_paths=test_csvs,
            unique_labels_path=unique_labels_path,
            device=eval_device,
            max_samples=eval_max_samples,
            logger=logger,
        )
        if not et0_df.empty:
            et0_df = et0_df.rename(
                columns={
                    "num_stories": "num_stories_et0",
                    "mean_acc": "mean_acc_et0",
                    "std_acc": "std_acc_et0",
                    "mean_macro_f1": "mean_macro_f1_et0",
                    "std_macro_f1": "std_macro_f1_et0",
                    "mean_micro_f1": "mean_micro_f1_et0",
                    "std_micro_f1": "std_micro_f1_et0",
                    "mean_loss": "mean_loss_et0",
                    "std_loss": "std_loss_et0",
                }
            )
            summary_df = summary_df.merge(
                et0_df,
                on=["test_csv", "test_csv_full_path"],
                how="left",
            )
    eval_summary_path = os.path.join(round_dir, "eval_summary.csv")
    summary_df.to_csv(eval_summary_path, index=False)
    logger.info(f"Evaluation summary saved → {eval_summary_path}")

    round_duration_s = time.time() - round_start_time
    record: Dict[str, Any] = {
        "et_id": round_num,
        "model_path": model_path,
        "priority_fn_path": os.path.abspath(priority_fn_path),
        "eval_csv": eval_csv_path,
        "base_train_csv": base_train_csv_path,
        "final_train_csv": final_train_csv_path,
        "et_val_acc": et_val_acc,
        "round_duration_s": round_duration_s,
    }
    for idx, row in summary_df.iterrows():
        label = test_csv_labels[idx] if idx < len(test_csv_labels) else row["test_csv"]
        record[f"acc_{label}"] = float(row["mean_acc"])
        if "mean_acc_et0" in row and row["mean_acc_et0"] == row["mean_acc_et0"]:
            record[f"acc_et0_{label}"] = float(row["mean_acc_et0"])

    records.append(record)
    return record


def main() -> None:
    _setup_import_paths()

    p = argparse.ArgumentParser(description="Run multi-round ET analysis without ProgramDB/evolution.")
    p.add_argument("--run_dir", required=True, help="Output directory for the whole run.")
    p.add_argument(
        "--rounds",
        type=int,
        default=None,
        help="Number of rounds to run (>=1). Defaults to multi_round.num_rounds from --fullflow_config.",
    )
    p.add_argument("--priority_fns_dir", required=True, help="Directory containing round_<k>.py files.")
    p.add_argument(
        "--start_round",
        type=int,
        default=1,
        help="Round number to start from (skip earlier rounds). "
        "Requires that run_dir already contains round_0/ through round_{start_round-1}/ "
        "and a records.pkl with entries for those rounds.",
    )

    p.add_argument(
        "--fullflow_config",
        default="/home/user/auto-world-rules/stuff/stuff/auto-world-rules/Funsearch/Collaterals/FullFlowconfigs/configAD_served_qwen3-next.json",
        help="FullFlow config JSON path (used to set default story generation params from cfg.evaluation.*).",
    )
    p.add_argument(
        "--init_model_path",
        default=None,
        help="Optional path to an existing ET checkpoint (.pth or Lightning .ckpt). "
        "If provided, this is used as ET_0 (copied to run_dir/round_0/model.pth) and "
        "--alt_training_sources_init is ignored.",
    )
    p.add_argument(
        "--alt_training_sources_init",
        nargs="*",
        default=None,
        help="Defaults to multi_round.alt_training_sources_init from --fullflow_config when omitted.",
    )
    p.add_argument(
        "--alt_training_sources_everyrnd",
        nargs="*",
        default=None,
        help="Defaults to multi_round.alt_training_sources_everyrnd from --fullflow_config when omitted.",
    )

    # Story generation
    # Defaults below are filled from FullFlow config (cfg.evaluation.*) after parsing.
    p.add_argument("--num_stories_train", type=int, default=None)
    p.add_argument("--num_stories_eval", type=int, default=None)
    p.add_argument("--base_seed", type=int, default=None)
    p.add_argument("--eval_seed_offset", type=int, default=None)
    p.add_argument("--min_entities", type=int, default=None)
    p.add_argument("--max_entities", type=int, default=None)
    p.add_argument("--num_cands", type=int, default=None)
    p.add_argument("--rules_path", type=str, default=None)

    # Training
    p.add_argument("--epochs", type=int, default=None)
    p.add_argument("--batch_size", type=int, default=None)
    p.add_argument("--lr", type=float, default=None)
    p.add_argument("--training_seed", type=int, default=None)
    p.add_argument("--dataset_type", type=str, default=None)
    p.add_argument("--max_final_training_size", type=int, default=None)
    p.add_argument("--val_check_interval", type=int, default=None)
    p.add_argument("--unique_labels_path", type=str, default=None)

    # Evaluation
    p.add_argument("--eval_device", type=str, default=None, choices=["cuda", "cpu"])
    p.add_argument("--eval_max_samples", type=int, default=None)

    p.add_argument("--log_file", type=str, default=None)
    args = p.parse_args()

    logger = _build_logger(args.log_file)

    # Pull defaults from FullFlow config unless explicitly overridden.
    try:
        with open(args.fullflow_config, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        ev = cfg.get("evaluation", {})
        mr = cfg.get("multi_round", {}) or {}
    except Exception as e:
        raise RuntimeError(f"Failed to load --fullflow_config {args.fullflow_config!r}: {e}") from e

    # --- multi-round defaults (preferred) ---
    rounds = args.rounds if args.rounds is not None else int(mr.get("num_rounds", 1))
    if rounds < 1:
        raise ValueError("--rounds must be >= 1")

    num_stories_train = args.num_stories_train if args.num_stories_train is not None else int(
        mr.get("num_stories_train", ev.get("num_stories", 100))
    )
    num_stories_eval = args.num_stories_eval if args.num_stories_eval is not None else int(
        mr.get("num_stories_eval", ev.get("num_stories", 100))
    )
    eval_seed_offset = args.eval_seed_offset if args.eval_seed_offset is not None else int(
        mr.get("eval_seed_offset", 10000)
    )

    base_seed = args.base_seed if args.base_seed is not None else int(ev.get("base_seed", 42))
    min_entities = args.min_entities if args.min_entities is not None else int(ev.get("min_entities", 6))
    max_entities = args.max_entities if args.max_entities is not None else int(ev.get("max_entities", 8))
    # multi_round may want a distinct num_cands during post-round CSV creation
    num_cands = args.num_cands if args.num_cands is not None else int(
        mr.get("num_cands_training", ev.get("num_cands", 25))
    )

    # Training defaults from multi_round.*
    epochs = args.epochs if args.epochs is not None else int(mr.get("et_epochs", 100))
    batch_size = args.batch_size if args.batch_size is not None else int(mr.get("et_batch_size", 32))
    lr = args.lr if args.lr is not None else float(mr.get("et_lr", 1e-3))
    training_seed = (
        args.training_seed if args.training_seed is not None else int(mr.get("et_training_seed", 42))
    )
    dataset_type = args.dataset_type if args.dataset_type is not None else str(
        mr.get("et_dataset_type", "no_ambiguity_v2")
    )
    max_final_training_size = (
        args.max_final_training_size
        if args.max_final_training_size is not None
        else mr.get("et_max_final_training_size", None)
    )
    val_check_interval = (
        args.val_check_interval
        if args.val_check_interval is not None
        else int(mr.get("et_val_check_interval", 10))
    )

    # Eval defaults from multi_round.*
    eval_device = args.eval_device if args.eval_device is not None else str(mr.get("eval_device", "cuda"))
    eval_max_samples = (
        args.eval_max_samples
        if args.eval_max_samples is not None
        else mr.get("eval_max_samples", None)
    )

    # Paths default from multi_round.*
    unique_labels_path = (
        args.unique_labels_path
        if args.unique_labels_path is not None
        else mr.get("unique_labels_path", None)
    )
    rules_path = args.rules_path if args.rules_path is not None else mr.get("rules_path", None)

    # Default training sources from multi_round.*
    alt_training_sources_init = (
        args.alt_training_sources_init
        if args.alt_training_sources_init is not None
        else mr.get("alt_training_sources_init", None)
    )
    alt_training_sources_everyrnd = (
        args.alt_training_sources_everyrnd
        if args.alt_training_sources_everyrnd is not None
        else mr.get("alt_training_sources_everyrnd", None)
    )

    os.makedirs(args.run_dir, exist_ok=True)
    records_path = os.path.join(args.run_dir, "records.pkl")
    start_round = args.start_round

    # Resume: load existing records if starting from a later round
    if start_round > 1 and os.path.isfile(records_path):
        with open(records_path, "rb") as f:
            records = pickle.load(f)
        logger.info(f"Resumed from records.pkl with {len(records)} existing entries (start_round={start_round})")
    else:
        records: list[dict] = []

        # ET_0
        if args.init_model_path:
            logger.info("=" * 80)
            logger.info("INITIALIZING ET_0 (from existing model)")
            logger.info("=" * 80)
            _init_et0_from_model(
                init_et_dir=os.path.join(args.run_dir, "round_0"),
                init_model_path=args.init_model_path,
                records=records,
                logger=logger,
            )
            _save_records(records, records_path, logger)
        elif alt_training_sources_init:
            logger.info("=" * 80)
            logger.info("TRAINING ET_0 (initial model)")
            logger.info("=" * 80)
            _train_initial_et(
                init_et_dir=os.path.join(args.run_dir, "round_0"),
                alt_training_sources_init=alt_training_sources_init,
                alt_training_sources_everyrnd=alt_training_sources_everyrnd,
                records=records,
                epochs=epochs,
                batch_size=batch_size,
                lr=lr,
                training_seed=training_seed,
                dataset_type=dataset_type,
                max_final_training_size=max_final_training_size,
                val_check_interval=val_check_interval,
                unique_labels_path=unique_labels_path,
                logger=logger,
            )
            _save_records(records, records_path, logger)
        else:
            logger.info("No --alt_training_sources_init provided; skipping ET_0.")

    prev_round_dir: Optional[str] = (
        os.path.join(args.run_dir, f"round_{start_round - 1}")
        if start_round > 1
        else None
    )
    prev_final_train_csv: Optional[str] = None
    # Find the most recent final_train.csv
    for r in range(start_round - 1, -1, -1):
        candidate = os.path.join(args.run_dir, f"round_{r}", "final_train.csv")
        if os.path.isfile(candidate):
            prev_final_train_csv = candidate
            break

    for round_num in range(start_round, rounds + 1):
        round_start = time.time()
        round_dir = os.path.join(args.run_dir, f"round_{round_num}")

        priority_fn_path = os.path.join(args.priority_fns_dir, f"round_{round_num}.py")
        if not os.path.isfile(priority_fn_path):
            raise FileNotFoundError(
                f"Missing priority function for round {round_num}: {priority_fn_path}"
            )

        _run_round(
            round_num=round_num,
            round_dir=round_dir,
            priority_fn_path=priority_fn_path,
            prev_round_dir=prev_round_dir,
            prev_final_train_csv=prev_final_train_csv,
            alt_training_sources_everyrnd=alt_training_sources_everyrnd,
            records=records,
            round_start_time=round_start,
            num_stories_train=num_stories_train,
            num_stories_eval=num_stories_eval,
            base_seed=base_seed,
            eval_seed_offset=eval_seed_offset,
            min_entities=min_entities,
            max_entities=max_entities,
            num_cands=num_cands,
            rules_path=rules_path,
            epochs=epochs,
            batch_size=batch_size,
            lr=lr,
            training_seed=training_seed,
            dataset_type=dataset_type,
            max_final_training_size=max_final_training_size,
            val_check_interval=val_check_interval,
            unique_labels_path=unique_labels_path,
            eval_device=eval_device,
            eval_max_samples=eval_max_samples,
            logger=logger,
        )
        _save_records(records, records_path, logger)
        prev_round_dir = round_dir
        prev_final_train_csv = os.path.join(round_dir, "final_train.csv")

    logger.info("All rounds complete.")


if __name__ == "__main__":
    main()

