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
    logger = logging.getLogger("auto-research.evaluate_et")
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
    from auto_research.et.eval import evaluate_model_on_csvs

    p = argparse.ArgumentParser(description="Evaluate an EdgeTransformer on CSV(s).")
    p.add_argument("--model_path", required=True)
    p.add_argument("--test_csvs", nargs="+", required=True)
    p.add_argument("--unique_labels_path", default=None)
    p.add_argument("--device", default="cuda", choices=["cuda", "cpu"])
    p.add_argument("--max_samples", type=int, default=None)
    p.add_argument("--output_csv", default=None)
    args = p.parse_args()

    logger = _build_logger()
    df = evaluate_model_on_csvs(
        model_path=args.model_path,
        test_csv_paths=args.test_csvs,
        unique_labels_path=args.unique_labels_path,
        device=args.device,
        max_samples=args.max_samples,
        logger=logger,
    )
    if args.output_csv:
        os.makedirs(os.path.dirname(os.path.abspath(args.output_csv)), exist_ok=True)
        df.to_csv(args.output_csv, index=False)
        logger.info(f"Summary saved → {args.output_csv}")

    print("\n" + df.to_string(index=False))


if __name__ == "__main__":
    main()

