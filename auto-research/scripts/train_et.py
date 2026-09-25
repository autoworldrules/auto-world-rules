#!/usr/bin/env python3
from __future__ import annotations

import argparse
import logging
import os
import sys


def _setup_import_paths() -> None:
    this_dir = os.path.dirname(os.path.abspath(__file__))
    auto_research_root = os.path.abspath(os.path.join(this_dir, ".."))
    repo_root = os.path.abspath(os.path.join(this_dir, "..", ".."))
    sys.path.insert(0, auto_research_root)
    sys.path.insert(0, repo_root)


def _build_logger() -> logging.Logger:
    logger = logging.getLogger("auto-research.train_et")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    return logger


def main() -> None:
    _setup_import_paths()
    from auto_research.et.train import train_edge_transformer

    p = argparse.ArgumentParser(description="Train EdgeTransformer from a CSV.")
    p.add_argument("--train_csv", required=True)
    p.add_argument("--out_model", required=True)
    p.add_argument("--unique_labels_path", default=None)
    p.add_argument("--dataset_type", default="no_ambiguity_v2")
    p.add_argument("--epochs", type=int, default=100)
    p.add_argument("--batch_size", type=int, default=32)
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--log_dir", default=None)
    p.add_argument("--val_check_interval", type=int, default=10)
    args = p.parse_args()

    logger = _build_logger()
    train_edge_transformer(
        train_csv_path=args.train_csv,
        model_output_path=args.out_model,
        unique_labels_path=args.unique_labels_path,
        dataset_type=args.dataset_type,
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
        seed=args.seed,
        log_dir=args.log_dir,
        val_check_interval=args.val_check_interval,
        logger=logger,
    )


if __name__ == "__main__":
    main()

