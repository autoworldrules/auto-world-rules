"""Helpers for resuming a multi-round FunSearch run that was interrupted.

Typical scenario: a SLURM job is killed mid-round N+1. The previous run
directory contains completed rounds 0..N (with entries in records.pkl)
and a partially written round N+1.  These helpers detect the last
completed round, clean up the partial round, and return enough state for
main() to restart seamlessly from round N+1.
"""

import os
import glob
import pickle
import shutil
import logging
import re
from typing import Optional, Tuple, List, Dict, Any


def detect_last_completed_round(
    run_dir: str,
    logger: Optional[logging.Logger] = None,
) -> Tuple[int, List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Scan *run_dir* and return (last_completed_round, records, discoveries).

    A round is considered *completed* if it has an entry in records.pkl
    with a matching ``et_id``.  Round 0 (initial ET, ``et_id == 0``) is
    treated specially: it counts as completed but does not correspond to
    an evolution round.

    Returns
    -------
    last_completed_round : int
        Highest round number whose post-round processing finished
        (i.e. has an entry in records.pkl with ``et_id == round_num``).
        Returns 0 if only the initial ET (et_id=0) completed.
    records : list[dict]
        The records loaded from records.pkl (empty list if missing).
    discoveries : list[dict]
        The discoveries loaded from discoveries.pkl (empty list if missing).
    """
    log = logger or logging.getLogger(__name__)

    records_path = os.path.join(run_dir, "records.pkl")
    discoveries_path = os.path.join(run_dir, "discoveries.pkl")

    records: List[Dict[str, Any]] = []
    discoveries: List[Dict[str, Any]] = []

    if os.path.exists(records_path):
        with open(records_path, "rb") as f:
            loaded = pickle.load(f)
        # Handle both DataFrame (new) and list[dict] (legacy) formats
        if hasattr(loaded, "to_dict"):
            records = loaded.to_dict(orient="records")
        else:
            records = loaded
        log.info(f"Loaded {len(records)} record(s) from {records_path}")
    else:
        log.warning(f"No records.pkl found in {run_dir}")

    if os.path.exists(discoveries_path):
        with open(discoveries_path, "rb") as f:
            discoveries = pickle.load(f)
        log.info(f"Loaded {len(discoveries)} discovery entries from {discoveries_path}")

    # Determine last completed round from records
    completed_et_ids = sorted(r["et_id"] for r in records)
    if not completed_et_ids:
        log.warning("records.pkl is empty — nothing completed")
        return 0, records, discoveries

    last_completed = max(completed_et_ids)
    log.info(f"Last completed round (et_id): {last_completed}")
    return last_completed, records, discoveries


def cleanup_partial_round(
    run_dir: str,
    round_num: int,
    discoveries: List[Dict[str, Any]],
    logger: Optional[logging.Logger] = None,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Remove partial artefacts of an incomplete round and prune discoveries.

    If a ``db_checkpoint_init.pkl`` already exists for the incomplete round
    (meaning rescoring finished before the interruption), it is preserved so
    the resume can skip rescoring.

    Parameters
    ----------
    run_dir : str
        The run directory (e.g. ``…/20260330_045414``).
    round_num : int
        The round number to clean up.
    discoveries : list[dict]
        Current discoveries list. Entries for *round_num* are removed.
    logger : Logger, optional

    Returns
    -------
    discoveries : list[dict]
        Cleaned discoveries list (entries for *round_num* removed).
    preserved_init_db : str or None
        Path to db_checkpoint_init.pkl if it was preserved, else None.
    """
    log = logger or logging.getLogger(__name__)
    round_dir = os.path.join(run_dir, f"round_{round_num}")
    preserved_init_db = None

    if os.path.isdir(round_dir):
        init_db_path = os.path.join(round_dir, "db_checkpoint_init.pkl")
        if os.path.exists(init_db_path):
            # Preserve the init DB (rescoring was already done)
            preserved_init_db = init_db_path
            log.info(
                f"Preserving db_checkpoint_init.pkl from partial round "
                f"(rescoring already completed)"
            )

        # Remove everything except db_checkpoint_init.pkl
        for entry in os.listdir(round_dir):
            entry_path = os.path.join(round_dir, entry)
            if entry == "db_checkpoint_init.pkl" and preserved_init_db:
                continue
            if os.path.isdir(entry_path):
                shutil.rmtree(entry_path)
            else:
                os.remove(entry_path)
        log.info(f"Cleaned partial round directory: {round_dir}")
    else:
        log.info(f"No partial round directory found: {round_dir}")

    # Prune discoveries for the incomplete round
    before = len(discoveries)
    discoveries = [d for d in discoveries if d.get("round_num") != round_num]
    pruned = before - len(discoveries)
    if pruned:
        log.info(f"Removed {pruned} discovery entries for round {round_num}")

    return discoveries, preserved_init_db


def prepare_resume_state(
    prev_run_dir: str,
    logger: Optional[logging.Logger] = None,
) -> Dict[str, Any]:
    """Analyse a previous run and prepare everything needed to resume.

    Returns a dict with all the state that main() needs to skip already-
    completed rounds and restart from the first incomplete one.

    Returns
    -------
    dict with keys:
        run_dir : str
            The run_dir to reuse (same as prev_run_dir).
        resume_from_round : int
            The round number to start from.
        records : list[dict]
            Cleaned records list.
        discoveries : list[dict]
            Cleaned discoveries list.
        et_model_path : str or None
            Path to the ET model to use for the resume round.
        prev_round_dir : str or None
            Path to the last completed round directory.
        prev_final_train_csv : str or None
            Path to the last completed round's final_train.csv.
        preserved_init_db : str or None
            Path to db_checkpoint_init.pkl if rescoring was already done
            for the resume round (so it can be skipped).
    """
    log = logger or logging.getLogger(__name__)
    log.info(f"Preparing resume state from: {prev_run_dir}")

    if not os.path.isdir(prev_run_dir):
        raise FileNotFoundError(f"Previous run directory not found: {prev_run_dir}")

    last_completed, records, discoveries = detect_last_completed_round(
        prev_run_dir, logger=log
    )

    # The round to resume is last_completed + 1
    # (last_completed=0 means only initial ET trained, resume from round 1)
    resume_round = last_completed + 1 if last_completed > 0 else 1

    # Special case: if last_completed == 0, only ET_0 was trained.
    # resume_round = 1, which is the first evolution round.
    if last_completed == 0:
        # Check if round_0 has model.pth (initial ET)
        round_0_model = os.path.join(prev_run_dir, "round_0", "model.pth")
        if os.path.exists(round_0_model):
            et_model_path = round_0_model
            prev_final_train_csv = os.path.join(prev_run_dir, "round_0", "final_train.csv")
        else:
            et_model_path = None
            prev_final_train_csv = None
        prev_round_dir = None
    else:
        # Normal case: last completed round N has model.pth and final_train.csv
        last_round_dir = os.path.join(prev_run_dir, f"round_{last_completed}")
        last_record = next(
            r for r in records if r["et_id"] == last_completed
        )
        et_model_path = last_record["model_path"]
        prev_final_train_csv = last_record["final_train_csv"]
        prev_round_dir = last_round_dir

    log.info(f"Resume from round {resume_round}")
    log.info(f"ET model path: {et_model_path}")
    log.info(f"Previous final_train.csv: {prev_final_train_csv}")

    # Clean up partial round (if it exists)
    discoveries, preserved_init_db = cleanup_partial_round(
        prev_run_dir, resume_round, discoveries, logger=log
    )

    # Persist cleaned discoveries
    disc_path = os.path.join(prev_run_dir, "discoveries.pkl")
    with open(disc_path, "wb") as f:
        pickle.dump(discoveries, f)
    log.info(f"Saved cleaned discoveries → {disc_path}")

    return {
        "run_dir": prev_run_dir,
        "resume_from_round": resume_round,
        "records": records,
        "discoveries": discoveries,
        "et_model_path": et_model_path,
        "prev_round_dir": prev_round_dir,
        "prev_final_train_csv": prev_final_train_csv,
        "preserved_init_db": preserved_init_db,
    }
