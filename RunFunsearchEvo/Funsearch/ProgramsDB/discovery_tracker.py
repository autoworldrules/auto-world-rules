"""
Track new discoveries per evolution cycle.

A "discovery" is any program whose score strictly exceeds the global best
score that existed at the *start* of the cycle.  Because the pre-cycle
best was, by definition, the maximum, every program with a higher score
must have been added during that cycle.

Typical usage (integrated into ``_run_funsearch_cycles``)::

    from Funsearch.ProgramsDB.discovery_tracker import (
        snapshot_best_score,
        count_new_discoveries,
        save_discoveries,
    )

    discoveries = []
    for cycle_num in range(1, num_reset + 1):
        best_before = snapshot_best_score(programs_db)
        programs_db = run_evolution_cycle(...)
        n = count_new_discoveries(programs_db, best_before)
        discoveries.append({
            "round_num": round_num,
            "cycle_number": cycle_num,
            "num_new_discoveries": n,
        })
    save_discoveries(discoveries, path)
"""

import os
import sys
import pickle
import logging
from typing import Optional

this_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(this_dir, '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from DeepMindCodeReference.implementation import programs_database


def snapshot_best_score(db: programs_database.ProgramsDatabase) -> float:
    """Return the global best score across all islands."""
    return max(db._best_score_per_island)


def count_new_discoveries(
    db: programs_database.ProgramsDatabase,
    best_before: float,
) -> int:
    """Count programs whose cluster score strictly exceeds *best_before*.

    Iterates over every island → cluster → programs and counts individual
    programs that live in a cluster with ``score > best_before``.
    """
    count = 0
    for island in db._islands:
        for cluster in island._clusters.values():
            if cluster.score > best_before:
                count += len(cluster._programs)
    return count


def save_discoveries(
    discoveries: list,
    filepath: str,
    logger: Optional[logging.Logger] = None,
) -> None:
    """Persist the discoveries list as a pickle file."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "wb") as f:
        pickle.dump(discoveries, f)
    if logger:
        logger.info(f"Discoveries saved → {filepath} ({len(discoveries)} entries)")
