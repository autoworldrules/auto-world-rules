#!/usr/bin/env python3
from __future__ import annotations

import argparse
import logging
import os
import sys
import json


def _setup_import_paths() -> None:
    this_dir = os.path.dirname(os.path.abspath(__file__))
    auto_research_root = os.path.abspath(os.path.join(this_dir, ".."))
    repo_root = os.path.abspath(os.path.join(this_dir, "..", ".."))
    sys.path.insert(0, auto_research_root)
    sys.path.insert(0, repo_root)


def _build_logger() -> logging.Logger:
    logger = logging.getLogger("auto-research.generate_csv")
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
    from auto_research.nora.training_csv import generate_training_csv

    p = argparse.ArgumentParser(description="Generate NoRA1.1 training CSV from a priority function.")
    p.add_argument(
        "--fullflow_config",
        default="/home/user/auto-world-rules/stuff/stuff/auto-world-rules/Funsearch/Collaterals/FullFlowconfigs/configAD_served_qwen3-next.json",
        help="FullFlow config JSON path (used to set default generation params from cfg.evaluation.*).",
    )
    p.add_argument("--priority_fn", required=True, help="Path to a .py file defining `priority(...)`.")
    p.add_argument("--out", required=True, help="Output CSV path.")
    # Defaults below are filled from FullFlow config (cfg.evaluation.*) after parsing.
    p.add_argument("--num_stories", type=int, default=None)
    p.add_argument("--base_seed", type=int, default=None)
    p.add_argument("--min_entities", type=int, default=None)
    p.add_argument("--max_entities", type=int, default=None)
    p.add_argument("--num_cands", type=int, default=None)
    p.add_argument("--rules_path", type=str, default=None)
    p.add_argument("--max_workers", type=int, default=None)
    args = p.parse_args()

    logger = _build_logger()

    # Pull defaults from FullFlow config unless explicitly overridden.
    try:
        with open(args.fullflow_config, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        ev = cfg.get("evaluation", {})
    except Exception as e:
        raise RuntimeError(f"Failed to load --fullflow_config {args.fullflow_config!r}: {e}") from e

    num_stories = args.num_stories if args.num_stories is not None else int(ev.get("num_stories", 100))
    base_seed = args.base_seed if args.base_seed is not None else int(ev.get("base_seed", 42))
    min_entities = args.min_entities if args.min_entities is not None else int(ev.get("min_entities", 5))
    max_entities = args.max_entities if args.max_entities is not None else int(ev.get("max_entities", 8))
    num_cands = args.num_cands if args.num_cands is not None else int(ev.get("num_cands", 25))

    generate_training_csv(
        priority_fn_path=args.priority_fn,
        output_csv_path=args.out,
        num_stories=num_stories,
        base_seed=base_seed,
        min_entities=min_entities,
        max_entities=max_entities,
        num_cands=num_cands,
        rules_path=args.rules_path,
        max_workers=args.max_workers,
        logger=logger,
    )


if __name__ == "__main__":
    main()

