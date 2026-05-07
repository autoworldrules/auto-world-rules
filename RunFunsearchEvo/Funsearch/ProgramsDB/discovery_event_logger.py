"""
Per-worker discovery event logger.

When a sampler discovers a new island-best priority function during evolution,
this module records the event (round, cycle, island, function text, prompt).

**Parallelism strategy**: Each worker process creates its own
``DiscoveryEventLogger`` that writes to a private pickle file
(``discovery_events_sampler{id}.pkl``).  After all workers finish,
the main process calls ``consolidate_discovery_events()`` to merge
every per-worker file into a single ``discovery_events.pkl`` DataFrame
in the run directory.  This design avoids any file locks, shared memory,
or cross-process coordination.

Typical usage inside a worker::

    logger = DiscoveryEventLogger(sampler_id, log_dir, round_num, cycle_num)
    # ... inside EvaluatorWrapper.analyse, when score > island best:
    logger.record(island_id, prio_fn_str, formatted_prompt, registered_score)
    # ... at worker shutdown:
    logger.flush()

Consolidation (called from the main process)::

    consolidate_discovery_events(
        worker_event_dirs=[round_log_dir],
        output_path=os.path.join(run_dir, "discovery_events.pkl"),
    )

Directory layout relative to *run_dir*::

    <run_dir>/                               # e.g. Results/20260406_123456_JobId42/
    ├── discovery_events.pkl                  # consolidated DataFrame (append-mode, grows across rounds/cycles)
    ├── round_1/
    │   └── sampler_logs/                     # = log_dir passed to workers
    │       ├── discovery_events_sampler0.pkl  # transient per-worker file
    │       ├── discovery_events_sampler1.pkl
    │       └── ...                           # one per sampler that had at least one discovery
    ├── round_2/
    │   └── sampler_logs/
    │       └── ...
    └── ...

Per-worker files are **deleted** by ``consolidate_discovery_events()``
immediately after their contents are merged into the consolidated
``discovery_events.pkl``.  A new set of per-worker files is created
for each evolution cycle, so they never accumulate on disk.
"""

import os
import pickle
import logging
from typing import Optional, List

import pandas as pd


class DiscoveryEventLogger:
    """Accumulates discovery events in-memory and flushes to a per-worker pickle."""

    def __init__(
        self,
        sampler_id: int,
        log_dir: str,
        round_num: int,
        cycle_num: int,
        logger: Optional[logging.Logger] = None,
    ):
        self._sampler_id = sampler_id
        self._log_dir = log_dir
        self._round_num = round_num
        self._cycle_num = cycle_num
        self._logger = logger
        self._events: list[dict] = []

    # --- public API --------------------------------------------------------

    def update_cycle(self, cycle_num: int) -> None:
        """Update the current cycle number (called between cycles)."""
        self._cycle_num = cycle_num

    def record(
        self,
        island_id: int,
        prio_fn_str: str,
        formatted_prompt: str,
        registered_score: float,
    ) -> None:
        """Record a new island-best discovery event."""
        self._events.append({
            "round_num": self._round_num,
            "cycle_num": self._cycle_num,
            "island_id": island_id,
            "sampler_id": self._sampler_id,
            "registered_score": registered_score,
            "prio_fn_str": prio_fn_str,
            "formatted_prompt": formatted_prompt,
        })

    def flush(self) -> Optional[str]:
        """Write accumulated events to a per-worker pickle file.

        Returns the file path on success, or None if there are no events.
        """
        if not self._events:
            return None
        filepath = os.path.join(
            self._log_dir,
            f"discovery_events_sampler{self._sampler_id}.pkl",
        )
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "wb") as f:
            pickle.dump(self._events, f)
        if self._logger:
            self._logger.info(
                f"Flushed {len(self._events)} discovery events → {filepath}"
            )
        return filepath


def consolidate_discovery_events(
    worker_event_dirs: List[str],
    output_path: str,
    logger: Optional[logging.Logger] = None,
) -> pd.DataFrame:
    """Merge per-worker discovery event files into a single DataFrame.

    Scans *worker_event_dirs* for files matching
    ``discovery_events_sampler*.pkl``, loads them, concatenates into one
    DataFrame, and saves to *output_path*.

    If *output_path* already exists it is loaded first so that events from
    previous rounds/cycles are preserved (append-mode).

    Returns the consolidated DataFrame.
    """
    all_events: list[dict] = []

    # Load existing consolidated file if present (append mode)
    if os.path.isfile(output_path):
        with open(output_path, "rb") as f:
            prev = pickle.load(f)
        if isinstance(prev, pd.DataFrame):
            all_events.extend(prev.to_dict("records"))
        elif isinstance(prev, list):
            all_events.extend(prev)

    # Collect per-worker files
    for d in worker_event_dirs:
        if not os.path.isdir(d):
            continue
        for fname in sorted(os.listdir(d)):
            if fname.startswith("discovery_events_sampler") and fname.endswith(".pkl"):
                fpath = os.path.join(d, fname)
                with open(fpath, "rb") as f:
                    worker_events = pickle.load(f)
                all_events.extend(worker_events)
                # Remove per-worker file after reading
                os.remove(fpath)

    df = pd.DataFrame(all_events)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "wb") as f:
        pickle.dump(df, f)

    if logger:
        logger.info(
            f"Consolidated {len(df)} total discovery events → {output_path}"
        )
    return df
