"""
Parallel FunSearch execution with database sharding.

Each worker process gets its own database shard, creates its own evaluators,
runs sampling, and saves its shard to disk. The main process then merges
all shards into a final database.

Main Process Flow:
Create DB → Shard → Save shards → Launch workers → 
Wait → Load shards → Merge → Save final DB

Worker Process Flow:
Load shard → Create evaluators → Load model → 
Sample (parallel) → Save shard → Exit

Per-round artefacts (round_N/):

    ET Model USED During Round N (for scoring programs):
    ----------------------------------------------------
    "ET model for round N" refers to the ET used DURING round N to score
    all programs in the database, NOT the ET trained at the end of round N.
    
    Round 1:
      • If multi_round.num_rounds > 1 AND multi_round.alt_training_sources_init
        is specified: Uses ET_0 (trained before round 1 from
        alt_training_sources_init, saved in round_0/model.pth).
      • Otherwise: Uses default hardcoded ET (Funsearch/Evaluator/edget.pth).
    Round N (N > 1):
      • Uses ET_{N-1} (trained at the end of round N-1, saved in
        round_{N-1}/model.pth).

    ALL program scores in both DB files below (db_checkpoint_init.pkl and
    db_checkpoint_end.pkl) are computed using the ET model specified above.
    The model.pth in THIS directory (round_N/) is ET_N, which is trained
    AFTER both DBs are saved and will only be used starting in round N+1.

    db_checkpoint_init.pkl – Database at the START of the round, right after
                             creation (round 1) or rescoring with the ET from
                             the previous round (round > 1).  Never overwritten.
                             All program scores computed by ET model for round N.
    db_checkpoint_end.pkl  – Database at the END of the round, after all
                             evolution cycles complete.  This is the DB that
                             post-round processing (Step 4) extracts the best
                             priority function from.
                             All program scores computed by ET model for round N.
    base_train.csv      – Stories generated from the best priority function
                          found in db_checkpoint_end.pkl.  Produced at the
                          END of the round during post-round processing
                          (Step 4). Uses base_seed for reproducibility.
    final_train.csv     – Merged training CSV that combines base_train.csv
                          with any alt_training_sources.  Used to train
                          model.pth (ET_N) in this same directory.
    model.pth           – EdgeTransformer ET_N trained at the END of round N
                          (Step 4) on final_train.csv.  Will be loaded as
                          the ET evaluator for round N+1.
    best_priority_fn.py – The best priority function extracted from this
                          round's evolved DB (from db_checkpoint_end.pkl).
    eval.csv            – Evaluation stories generated from the best priority
                          function (best_priority_fn.py) using a different seed
                          (base_seed + eval_seed_offset) to measure
                          out-of-sample quality and avoid train-test leakage.
    eval_summary.csv    – Aggregated evaluation metrics for this round.
    lightning_logs/     – PyTorch-Lightning training logs for model.pth.
    cycle_dbs/          – Per-cycle database snapshots (one pair per cycle):
        db_roundN_cycleC_pre_reset.pkl  – Database state immediately after
                                          evolution cycle C completes, before
                                          island resets are applied.  Scores
                                          reflect the ET active during round N.
        db_roundN_cycleC_post_reset.pkl – Database state after island resets
                                          are applied at the end of cycle C.
                                          Only written for cycles < num_reset
                                          (the final cycle has no reset, so
                                          only a pre_reset file is written).
                                          Useful for inspecting diversity
                                          recovery between cycles.

Resuming interrupted runs:
    Set ``multi_round.resume_run_dir`` in the config to the path of a
    previous run_dir (e.g. ``Funsearch/Logs/runs/20260330_045414``).
    The launcher detects the last fully completed round N (via records.pkl),
    cleans up any partial round N+1 artefacts, and restarts from round N+1
    reusing the ET and database from round N (no retraining or rescoring
    needed if db_checkpoint_init.pkl was already written).
"""
import sys, os
this_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(this_dir, '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
    
import datetime
import multiprocessing as mp
import pickle
import time
import logging
from DeepMindCodeReference.implementation import code_manipulation
from DeepMindCodeReference.implementation import programs_database
from DeepMindCodeReference.implementation import config
from Funsearch.Evaluator.evaluator import EvaluatorET
from Funsearch.FullFlow.EvaluatorMock import EvaluatorWrapper
from Funsearch.utils.logging_utils import create_log_directory
from Funsearch.utils.inspect_database import inspect_database_shallow
from Funsearch.utils.database_sharding import shard_database, merge_databases
from Funsearch.utils.parallel_process_helper_vllmclient import (
    run_sampler_worker, 
    handle_stuck_or_dead_worker
)
from Funsearch.utils.database_resets import reset_islands
from Funsearch.utils.database_initialization import initialize_database
from Funsearch.utils.config_loader import load_config, FunSearchConfig
from Funsearch.MultiRoundEvalTrainer.post_round_processing import (
    run_post_round,
    train_initial_et,
    save_records,
)
from Funsearch.MultiRoundEvalTrainer.rescore_database import rescore_database
from Funsearch.MultiRoundEvalTrainer.resume_run import prepare_resume_state
from Funsearch.ProgramsDB.discovery_tracker import (
    snapshot_best_score,
    count_new_discoveries,
    save_discoveries,
)
from Funsearch.ProgramsDB.discovery_event_logger import consolidate_discovery_events


def run_evolution_cycle(
    programs_db: programs_database.ProgramsDatabase,
    cycle_num: int,
    round_num: int,
    num_samplers: int,
    num_evaluators: int,
    num_stories: int,
    base_seed: int,
    min_entities: int,
    max_entities: int,
    num_cands: int,
    use_local_llm: bool,
    use_served_llm: bool,
    llm_model: str,
    max_llm_retries: int,
    base_url: str,
    num_tries_per_sampler: int,
    log_dir: str,
    log_level: str,
    save_db_path: str,
    template,
    function_to_evolve: str,
    enable_worker_timeout: bool,
    worker_timeout_after_first_completion: int,
    absolute_worker_timeout: int,
    main_logger: logging.Logger,
    log_prompt_frequency: int = 10,
    log_eval_sample_frequency: int = 10,
    et_model_path: str = None,
    discovery_events_path: str = None,
    parallel_stories: int = 1,
) -> programs_database.ProgramsDatabase:
    """
    Run one complete evolution cycle: shard → distribute → evolve → merge → save.
    
    Args:
        programs_db: Current database to evolve
        cycle_num: Current cycle number (for logging)
        discovery_events_path: If set, per-worker discovery event files in
            ``log_dir`` are consolidated into this path after each cycle.
        ... (other parameters for worker configuration)
        
    Returns:
        Merged database after evolution
    """
    main_logger.debug(f'=' * 80)
    main_logger.info(f'Starting evolution cycle {cycle_num}')
    main_logger.debug(f'Database has {len(programs_db._islands)} islands before cycle')
    main_logger.debug(f'=' * 80)
    
    # ===================Shard database for parallel workers
    main_logger.debug(f'Sharding database into {num_samplers} pieces...')
    db_shards = shard_database(programs_db, num_shards=num_samplers)
    
    # Save shards to temporary files (overwrite previous shards)
    shard_dir = os.path.join(log_dir, 'shards')
    os.makedirs(shard_dir, exist_ok=True)
    
    shard_input_paths = []
    shard_output_paths = []
    for i, shard in enumerate(db_shards):
        input_path = os.path.join(shard_dir, f'shard_{i}_input.pkl')
        output_path = os.path.join(shard_dir, f'shard_{i}_output.pkl')
        programs_database.save_programs_database(shard, input_path)
        shard_input_paths.append(input_path)
        shard_output_paths.append(output_path)
        main_logger.info(f'Shard {i}: {len(shard._islands)} islands saved to {input_path}')
    
    # =================== Prepare worker configurations
    worker_configs = []
    for i in range(num_samplers):
        worker_config = {
            'db_shard_path': shard_input_paths[i],
            'output_db_path': shard_output_paths[i],
            'num_evaluators': num_evaluators,
            'num_stories': num_stories,
            'base_seed': base_seed,
            'min_entities': min_entities,
            'max_entities': max_entities,
            'num_cands': num_cands,
            'samples_per_prompt': 1,  # Fixed: always generate 1 sample per prompt
            'use_local_llm': use_local_llm,
            'use_served_llm': use_served_llm,  
            'llm_config': llm_model,
            'max_retries': max_llm_retries,
            'base_url': base_url,  # Optional base URL for served LLM
            'num_tries_per_sampler': num_tries_per_sampler,
            'log_prompt_frequency': log_prompt_frequency,
            'log_eval_sample_frequency': log_eval_sample_frequency,
            'et_model_path': et_model_path,
            'round_num': round_num,
            'cycle_num': cycle_num,
            'parallel_stories': parallel_stories,
        }
        worker_configs.append(worker_config)
    
    # =================== Start parallel workers
    main_logger.info('Starting parallel workers...')
    manager = mp.Manager()
    log_queue = manager.Queue()
    model_load_lock = manager.Lock()
    
    # Create events for sequential model loading
    load_events = [manager.Event() for _ in range(num_samplers)]
    all_models_loaded_event = manager.Event()
    
    # Signal first worker to start
    load_events[0].set()
    
    # Create and start worker processes
    processes = []
    for i in range(num_samplers):
        p = mp.Process(
            target=run_sampler_worker,
            args=(i, worker_configs[i], log_dir, log_level, log_queue, model_load_lock, load_events[i], all_models_loaded_event)
        )
        p.start()
        processes.append(p)
        main_logger.info(f'Started worker {i} in process {p.pid}')
        
        # Monitor for model load completion
        time.sleep(2)
        check_timeout = 3000
        start_time = time.time()
        model_loaded = False
        
        while time.time() - start_time < check_timeout:
            try:
                msg = log_queue.get(timeout=1)
                main_logger.info(msg)
                if f'Sampler {i} model loaded successfully!' in msg:
                    model_loaded = True
                    # Signal next worker
                    if i + 1 < num_samplers:
                        load_events[i + 1].set()
                    break
            except:
                pass
        
        if not model_loaded:
            main_logger.warning(f'Worker {i} model loading timeout')
            if i + 1 < num_samplers:
                load_events[i + 1].set()
    
    # =======================   Signal all workers to start sampling
    main_logger.info('All models loaded, starting parallel sampling...')
    all_models_loaded_event.set()
    
    # Monitor workers with timeout support
    worker_states = {i: 'RUNNING' for i in range(num_samplers)}  # RUNNING, COMPLETED, FAILED, TIMEOUT
    first_completion_time = None
    workers_start_time = time.time()
    
    main_logger.debug(f'Monitoring {num_samplers} workers...')
    if enable_worker_timeout:
        main_logger.debug(f'Worker timeouts enabled:')
        main_logger.debug(f'  - Absolute timeout: {absolute_worker_timeout}s from start')
        if worker_timeout_after_first_completion:
            main_logger.debug(f'  - Relative timeout: {worker_timeout_after_first_completion}s after first completion')
    else:
        main_logger.debug('Worker timeouts disabled - workers can run indefinitely')
    
    # Helper to extract worker ID from message
    def extract_worker_id_from_msg(msg: str) -> int:
        """Extract worker/sampler ID from log message."""
        import re
        match = re.search(r'[Ss]ampler (\d+)', msg)
        if match:
            return int(match.group(1))
        return -1
    
    while any(state == 'RUNNING' for state in worker_states.values()):
        current_time = time.time()
        elapsed = current_time - workers_start_time
        
        # Check timeouts if enabled
        if enable_worker_timeout:
            # Check absolute timeout
            if absolute_worker_timeout and elapsed > absolute_worker_timeout:
                main_logger.warning(f'Absolute timeout reached ({absolute_worker_timeout}s)!')
                main_logger.warning(f'Terminating remaining workers...')
                for i, state in worker_states.items():
                    if state == 'RUNNING':
                        worker_states[i] = 'TIMEOUT'
                        handle_stuck_or_dead_worker(
                            i, processes[i], shard_input_paths[i], shard_output_paths[i],
                            'absolute_timeout', main_logger
                        )
                break
            
            # Check relative timeout (after first completion)
            if (first_completion_time and worker_timeout_after_first_completion and
                current_time - first_completion_time > worker_timeout_after_first_completion):
                main_logger.warning(
                    f'Relative timeout reached ({worker_timeout_after_first_completion}s after first completion)!'
                )
                main_logger.warning(f'Terminating remaining workers...')
                for i, state in worker_states.items():
                    if state == 'RUNNING':
                        worker_states[i] = 'TIMEOUT'
                        handle_stuck_or_dead_worker(
                            i, processes[i], shard_input_paths[i], shard_output_paths[i],
                            'relative_timeout', main_logger
                        )
                break
        
        # Check for messages from workers
        try:
            msg = log_queue.get(timeout=1)
            main_logger.info(msg)
            
            # Check if a worker completed
            if 'done with sampler' in msg.lower():
                worker_id = extract_worker_id_from_msg(msg)
                if worker_id >= 0 and worker_id < num_samplers:
                    if worker_states[worker_id] == 'RUNNING':
                        worker_states[worker_id] = 'COMPLETED'
                        main_logger.info(f'Worker {worker_id} marked as COMPLETED')
                        
                        # Start relative timeout on first completion
                        if first_completion_time is None and enable_worker_timeout:
                            first_completion_time = current_time
                            if worker_timeout_after_first_completion:
                                main_logger.info(
                                    f'First worker completed, starting {worker_timeout_after_first_completion}s '
                                    f'timeout for remaining workers'
                                )
                
        except Exception as e:
            # Timeout on queue.get() - check for dead processes
            for i, state in worker_states.items():
                if state == 'RUNNING' and not processes[i].is_alive():
                    main_logger.warning(f'Worker {i} (PID {processes[i].pid}) died unexpectedly!')
                    worker_states[i] = 'FAILED'
                    handle_stuck_or_dead_worker(
                        i, processes[i], shard_input_paths[i], shard_output_paths[i],
                        'died', main_logger
                    )
        
        # Log progress periodically
        if int(elapsed) % 600 == 0:  # Every 10 minutes
            running_count = sum(1 for s in worker_states.values() if s == 'RUNNING')
            completed_count = sum(1 for s in worker_states.values() if s == 'COMPLETED')
            main_logger.debug(
                f'Progress: {completed_count}/{num_samplers} completed, '
                f'{running_count} still running (elapsed: {int(elapsed)}s)'
            )
    
    # Final status report
    completed = sum(1 for s in worker_states.values() if s == 'COMPLETED')
    failed = sum(1 for s in worker_states.values() if s == 'FAILED')
    timeout = sum(1 for s in worker_states.values() if s == 'TIMEOUT')
    
    main_logger.info(f'Worker completion summary:')
    main_logger.info(f'  Completed: {completed}/{num_samplers}')
    main_logger.info(f'  Failed: {failed}/{num_samplers}')
    main_logger.info(f'  Timed out: {timeout}/{num_samplers}')
    
    # Wait for all processes to finish
    for i, p in enumerate(processes):
        if p.is_alive():
            main_logger.warning(f'Worker {i} still alive, joining with timeout...')
            p.join(timeout=5)
            if p.is_alive():
                main_logger.error(f'Worker {i} did not join, may be zombie')
        else:
            p.join(timeout=1)
            main_logger.debug(f'Worker {i} (PID {p.pid}) joined')
    
    # Collect remaining queue messages
    while not log_queue.empty():
        try:
            main_logger.info(log_queue.get_nowait())
        except:
            break
    
    # Load and merge worker shards
    main_logger.info('Loading worker database shards...')
    worker_dbs = []
    for i, output_path in enumerate(shard_output_paths):
        if os.path.exists(output_path):
            worker_db = programs_database.load_programs_database(output_path)
            worker_dbs.append(worker_db)
            main_logger.info(f'Loaded shard {i}: {len(worker_db._islands)} islands')
        else:
            main_logger.warning(f'Shard {i} output not found: {output_path}')
    
    # Merge all shards
    main_logger.info(f'Merging {len(worker_dbs)} database shards...')
    final_db = merge_databases(worker_dbs, template=template, function_to_evolve=function_to_evolve)
    main_logger.info(f'Merged database has {len(final_db._islands)} islands')
    
    # Save final database
    main_logger.debug(f'Saving merged database to: {save_db_path}')
    programs_database.save_programs_database(final_db, save_db_path)
    
    # Inspect database
    main_logger.debug(f'Inspecting database after cycle {cycle_num}...')
    if log_level == 'DEBUG':
        inspect_database_shallow(save_db_path, logger=main_logger)

    # Consolidate per-worker discovery event files
    if discovery_events_path:
        consolidate_discovery_events(
            worker_event_dirs=[log_dir],
            output_path=discovery_events_path,
            logger=main_logger,
        )
    
    main_logger.debug(f'Evolution cycle {cycle_num} completed!')
    main_logger.debug(f'=' * 80)
    
    return final_db


def _run_funsearch_cycles(
    programs_db,
    num_reset: int,
    num_samplers: int,
    num_evaluators: int,
    num_stories: int,
    base_seed: int,
    min_entities: int,
    max_entities: int,
    num_cands: int,
    use_local_llm: bool,
    use_served_llm: bool,
    llm_model: str,
    max_llm_retries: int,
    base_url: str,
    num_tries_per_sampler: int,
    log_dir: str,
    log_level: str,
    save_db_path: str,
    template,
    function_to_evolve: str,
    enable_worker_timeout: bool,
    worker_timeout_after_first_completion: int,
    absolute_worker_timeout: int,
    main_logger: logging.Logger,
    log_prompt_frequency: int = 10,
    log_eval_sample_frequency: int = 10,
    et_model_path: str = None,
    round_num: int = 1,
    discoveries: list = None,
    round_dir: str = None,
    discovery_events_path: str = None,
    parallel_stories: int = 1,
):
    """Run num_reset evolution cycles with island resets in between.

    Returns the evolved ProgramsDatabase after all cycles complete.

    If *discoveries* is not None, discovery counts are appended after every
    cycle.

    If *round_dir* is given, a ``cycle_dbs/`` subdirectory is created inside
    it and the program database is saved there at the end of every cycle
    (scored by the ET active during this round).

    If *discovery_events_path* is given, per-worker discovery event files
    are consolidated into this path after every evolution cycle.
    """
    # Prepare cycle_dbs directory for per-cycle DB snapshots
    cycle_dbs_dir = None
    if round_dir is not None:
        cycle_dbs_dir = os.path.join(round_dir, "cycle_dbs")
        os.makedirs(cycle_dbs_dir, exist_ok=True)

    for cycle_num in range(1, num_reset + 1):
        main_logger.info(f'\n{"#" * 80}')
        main_logger.info(f'# STARTING RESET CYCLE {cycle_num}/{num_reset}')
        main_logger.info(f'{"#" * 80}\n')

        best_before = snapshot_best_score(programs_db)

        programs_db = run_evolution_cycle(
            programs_db=programs_db,
            cycle_num=cycle_num,
            round_num=round_num,
            num_samplers=num_samplers,
            num_evaluators=num_evaluators,
            num_stories=num_stories,
            base_seed=base_seed,
            min_entities=min_entities,
            max_entities=max_entities,
            num_cands=num_cands,
            use_local_llm=use_local_llm,
            use_served_llm=use_served_llm,
            llm_model=llm_model,
            max_llm_retries=max_llm_retries,
            base_url=base_url,
            num_tries_per_sampler=num_tries_per_sampler,
            log_dir=log_dir,
            log_level=log_level,
            save_db_path=save_db_path,
            template=template,
            function_to_evolve=function_to_evolve,
            enable_worker_timeout=enable_worker_timeout,
            worker_timeout_after_first_completion=worker_timeout_after_first_completion,
            absolute_worker_timeout=absolute_worker_timeout,
            main_logger=main_logger,
            log_prompt_frequency=log_prompt_frequency,
            log_eval_sample_frequency=log_eval_sample_frequency,
            et_model_path=et_model_path,
            discovery_events_path=discovery_events_path,
            parallel_stories=parallel_stories,
        )

        # ---- Discovery tracking (all cycles, including the first) ----
        if discoveries is not None:
            n_disc = count_new_discoveries(programs_db, best_before)
            discoveries.append({
                "round_num": round_num,
                "cycle_number": cycle_num,
                "num_new_discoveries": n_disc,
            })
            main_logger.info(
                f"Discoveries in round {round_num} cycle {cycle_num}: "
                f"{n_disc} programs beat pre-cycle best ({best_before:.6f})"
            )

        # ---- Save per-cycle DB snapshot (before island reset) ----
        if cycle_dbs_dir is not None:
            pre_reset_path = os.path.join(
                cycle_dbs_dir,
                f"db_round{round_num}_cycle{cycle_num}_pre_reset.pkl",
            )
            programs_database.save_programs_database(programs_db, pre_reset_path)
            main_logger.info(f"Cycle DB (pre-reset) saved → {pre_reset_path}")

        if cycle_num < num_reset:
            main_logger.info(f'\nResetting islands after cycle {cycle_num}...')
            programs_db = reset_islands(programs_db, logger=main_logger)
            main_logger.info(
                f'After reset: {len(programs_db._islands)} islands, '
                f'best scores: {programs_db._best_score_per_island}'
            )

            # ---- Save per-cycle DB snapshot (after island reset) ----
            if cycle_dbs_dir is not None:
                post_reset_path = os.path.join(
                    cycle_dbs_dir,
                    f"db_round{round_num}_cycle{cycle_num}_post_reset.pkl",
                )
                programs_database.save_programs_database(programs_db, post_reset_path)
                main_logger.info(f"Cycle DB (post-reset) saved → {post_reset_path}")

            main_logger.info(f'Saving reset database to: {save_db_path}')
            programs_database.save_programs_database(programs_db, save_db_path)

    return programs_db


def main(config_path: str = None, log_dir: str = None):
    """
    Launch a multi-round parallel FunSearch experiment.

    Directory structure created::

        base_run_dir/
          YYYYMMDD_HHMMSS/            ← run_dir
            round_1/
              sampler_logs/           ← per-worker log files
              db_checkpoint_init.pkl  ← database at start of round
              db_checkpoint_end.pkl   ← database at end of round (pre-rescore)
              base_train.csv          ← stories from best priority fn
              final_train.csv         ← merged training CSV for ET
              model.pth               ← trained EdgeTransformer
              lightning_logs/         ← training logs
              eval.csv                ← evaluation CSV (different seed)
              best_priority_fn.py     ← extracted best priority fn
              eval_summary.csv        ← evaluation results
            round_2/
              ...
            records.pkl               ← per-round performance table

    When ``multi_round.num_rounds == 1`` the behaviour is equivalent to the
    legacy single-round mode (no ET retraining).

    To resume an interrupted run, set ``multi_round.resume_run_dir`` to the
    path of the previous run_dir (the datetime-stamped directory).

    Args:
        config_path: Path to JSON config file
        log_dir: Directory for logs (deprecated; use multi_round.base_run_dir)
    """
    # ================================ Configuration ================================
    cfg = load_config(config_path)
    print(f"Loaded configuration from: {config_path}")

    # -- Parallel --
    num_samplers = cfg.parallel.num_samplers
    num_islands = cfg.parallel.num_islands
    enable_worker_timeout = cfg.parallel.enable_worker_timeout
    worker_timeout_after_first_completion = cfg.parallel.worker_timeout_after_first_completion
    absolute_worker_timeout = cfg.parallel.absolute_worker_timeout
    # -- Evaluation --
    num_evaluators = cfg.evaluation.num_evaluators
    num_stories = cfg.evaluation.num_stories
    base_seed = cfg.evaluation.base_seed
    min_entities = cfg.evaluation.min_entities
    max_entities = cfg.evaluation.max_entities
    num_cands = cfg.evaluation.num_cands
    parallel_stories = cfg.evaluation.parallel_stories
    # -- Sampling --
    num_tries_per_sampler = cfg.sampling.num_tries_per_sampler
    num_reset = cfg.sampling.num_reset
    # -- LLM --
    use_local_llm = cfg.llm.use_local_llm
    use_served_llm = cfg.llm.use_served_llm
    llm_model = cfg.llm.llm_model
    max_llm_retries = cfg.llm.max_llm_retries
    base_url = cfg.llm.base_url
    # -- Logging --
    log_level = cfg.logging.log_level
    log_prompt_frequency = cfg.logging.log_prompt_frequency
    log_eval_sample_frequency = cfg.logging.log_eval_sample_frequency
    # -- Database --
    load_from_checkpoint = cfg.database.load_from_checkpoint
    referencedb = cfg.database.referencedb
    # -- Template --
    skeleton_path = cfg.template.skeleton_path
    function_to_evolve = cfg.template.function_to_evolve
    priority_fn_str_ini = cfg.template.priority_fn_str_ini
    # -- Multi-round --
    mr = cfg.multi_round
    num_rounds = mr.num_rounds

    # ======================== Directory structure ==================================
    resuming = mr.resume_run_dir is not None
    preserved_init_db = None  # set when resuming with completed rescoring

    if resuming:
        # --- Resume from a previous interrupted run ---
        # Use a temporary logger for resume prep (before run_dir is known)
        _tmp_logger = logging.getLogger('resume_prep')
        _tmp_logger.setLevel(logging.INFO)
        if not _tmp_logger.handlers:
            _tmp_logger.addHandler(logging.StreamHandler())
        resume_state = prepare_resume_state(mr.resume_run_dir, logger=_tmp_logger)
        run_dir = resume_state["run_dir"]
        start_round = resume_state["resume_from_round"]
        records = resume_state["records"]
        discoveries = resume_state["discoveries"]
        et_model_path = resume_state["et_model_path"]
        prev_round_dir = resume_state["prev_round_dir"]
        prev_final_train_csv = resume_state["prev_final_train_csv"]
        preserved_init_db = resume_state["preserved_init_db"]
    else:
        # --- Fresh run ---
        base_run_dir = mr.base_run_dir
        os.makedirs(base_run_dir, exist_ok=True)
        run_dir = os.path.join(base_run_dir, datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
        os.makedirs(run_dir, exist_ok=True)
        start_round = 1
        records = []
        discoveries = []
        et_model_path = None          # None → use default hardcoded model
        prev_round_dir = None
        prev_final_train_csv = None

    # ======================== Logging =============================================
    main_log_file = os.path.join(run_dir, "main-code.log")
    level = getattr(logging, log_level.upper(), logging.INFO)

    main_logger = logging.getLogger('main')
    main_logger.setLevel(level)
    main_logger.handlers = []

    log_file_mode = 'a' if resuming else 'w'
    file_handler = logging.FileHandler(main_log_file, mode=log_file_mode)
    file_handler.setLevel(level)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(message)s')
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    main_logger.addHandler(file_handler)
    main_logger.addHandler(console_handler)

    main_logger.info(f'evaluation.base_seed: {base_seed}')
    main_logger.info(f'Run directory: {run_dir}')
    if resuming:
        main_logger.info(f'RESUMING from round {start_round} '
                         f'(previous run: {mr.resume_run_dir})')
    main_logger.info(f'Starting FunSearch: {num_rounds} round(s), '
                     f'{num_reset} cycles/round, {num_samplers} workers, '
                     f'{num_islands} islands')

    # ======================== Load template =======================================
    with open(skeleton_path, 'r') as f:
        skeleton_text = f.read()
    template = code_manipulation.text_to_program(skeleton_text)
    main_logger.info(f'Loaded template for function: {function_to_evolve}')

    # ======================== Record-keeping ======================================
    records_path = os.path.join(run_dir, "records.pkl")
    discoveries_path = os.path.join(run_dir, "discoveries.pkl")
    discovery_events_path = os.path.join(run_dir, "discovery_events.pkl")

    # ======================== Outer rounds loop ===================================
    for round_num in range(start_round, num_rounds + 1):
        main_logger.info('\n' + '=' * 80)
        main_logger.info('=' * 80)
        main_logger.info(f'     STARTING ROUND {round_num}/{num_rounds}')
        main_logger.info('=' * 80)
        main_logger.info('=' * 80)

        # ---- Per-round directory structure ----
        round_dir = os.path.join(run_dir, f"round_{round_num}")
        os.makedirs(round_dir, exist_ok=True)
        round_log_dir = os.path.join(round_dir, "sampler_logs")
        os.makedirs(round_log_dir, exist_ok=True)
        round_db_path_init = os.path.join(round_dir, "db_checkpoint_init.pkl")
        round_db_path_end = os.path.join(round_dir, "db_checkpoint_end.pkl")

        round_start_time = time.time()

        # ---- Check for resume shortcut (skip Steps 1-2 if init DB preserved) ----
        if preserved_init_db and round_db_path_init == preserved_init_db:
            main_logger.info(
                f'Resuming: loading preserved init DB (rescoring already done) '
                f'→ {preserved_init_db}'
            )
            programs_db = programs_database.load_programs_database(preserved_init_db)
            main_logger.info(f'Loaded {len(programs_db._islands)} islands from preserved init DB')
            main_logger.info(f'ET model for this round: {et_model_path}')
            main_logger.info(f'Best scores per island (initial DB): {programs_db._best_score_per_island}')
            # Clear the flag so subsequent rounds use normal logic
            preserved_init_db = None
        else:
            # ---- Step 1: Prepare ET model for this round ----
            if round_num == 1:
                if mr.alt_training_sources_init and num_rounds > 1:
                    # Multi-round mode: train initial ET from alt_training_sources_init
                    # Saves artefacts into round_0/ to avoid colliding with round_1/
                    main_logger.info('Training initial ET (ET_0) from alt_training_sources_init …')
                    init_et_dir = os.path.join(run_dir, "round_0")
                    et_model_path = train_initial_et(
                        init_et_dir=init_et_dir,
                        alt_training_sources_init=mr.alt_training_sources_init,
                        alt_training_sources_everyrnd=mr.alt_training_sources_everyrnd,
                        records=records,
                        epochs=mr.et_epochs,
                        batch_size=mr.et_batch_size,
                        lr=mr.et_lr,
                        training_seed=mr.et_training_seed,
                        dataset_type=mr.et_dataset_type,
                        max_final_training_size=mr.et_max_final_training_size,
                        val_check_interval=mr.et_val_check_interval,
                        unique_labels_path=mr.unique_labels_path,
                        logger=main_logger,
                    )
                    save_records(records, records_path, logger=main_logger)
                    prev_final_train_csv = os.path.join(init_et_dir, "final_train.csv")
                else:
                    # Single-round or no alt sources: use default hardcoded ET
                    main_logger.info('Using default ET model (no initial retraining)')
                    et_model_path = None
            # For round > 1, et_model_path is set by the previous round's post-processing

            # ---- Step 2: Create or load database ----
            if round_num == 1:
                if load_from_checkpoint and os.path.exists(cfg.database.save_db_path):
                    main_logger.debug(f'Loading ProgramsDatabase from checkpoint: {cfg.database.save_db_path}')
                    programs_db = programs_database.load_programs_database(cfg.database.save_db_path)
                    main_logger.debug(f'Loaded database with {len(programs_db._islands)} islands')
                else:
                    programs_db = initialize_database(
                        template=template,
                        function_to_evolve=function_to_evolve,
                        num_islands=num_islands,
                        priority_fn_str_ini=priority_fn_str_ini,
                        num_stories=num_stories,
                        base_seed=base_seed,
                        min_entities=min_entities,
                        max_entities=max_entities,
                        num_cands=num_cands,
                        referencedb_path=referencedb,
                        logger=main_logger,
                        et_model_path=et_model_path,
                    )
            else:
                # Round > 1: carry forward the full database from the previous round,
                # rescoring every representative program with the newly trained ET.
                prev_db_path = os.path.join(run_dir, f"round_{round_num - 1}", "db_checkpoint_end.pkl")
                main_logger.info(f'Loading database from previous round: {prev_db_path}')
                old_db = programs_database.load_programs_database(prev_db_path)
                main_logger.info(f'Loaded previous DB with {len(old_db._islands)} islands')

                main_logger.info(f'Rescoring programs with new ET: {et_model_path}')
                programs_db = rescore_database(
                    old_db=old_db,
                    new_et_model_path=et_model_path,
                    num_stories=num_stories,
                    base_seed=base_seed,
                    min_entities=min_entities,
                    max_entities=max_entities,
                    num_cands=num_cands,
                    logger=main_logger,
                )
                main_logger.info(f'Rescored database has {len(programs_db._islands)} islands')

            programs_database.save_programs_database(programs_db, round_db_path_init)
            main_logger.info(f'Initial database saved → {round_db_path_init}')
            main_logger.info(f'Best scores per island (initial DB): {programs_db._best_score_per_island}')

        # ---- Step 3: Run FunSearch evolution cycles ----
        programs_db = _run_funsearch_cycles(
            programs_db=programs_db,
            num_reset=num_reset,
            num_samplers=num_samplers,
            num_evaluators=num_evaluators,
            num_stories=num_stories,
            base_seed=base_seed,
            min_entities=min_entities,
            max_entities=max_entities,
            num_cands=num_cands,
            use_local_llm=use_local_llm,
            use_served_llm=use_served_llm,
            llm_model=llm_model,
            max_llm_retries=max_llm_retries,
            base_url=base_url,
            num_tries_per_sampler=num_tries_per_sampler,
            log_dir=round_log_dir,
            log_level=log_level,
            save_db_path=round_db_path_end,
            template=template,
            function_to_evolve=function_to_evolve,
            enable_worker_timeout=enable_worker_timeout,
            worker_timeout_after_first_completion=worker_timeout_after_first_completion,
            absolute_worker_timeout=absolute_worker_timeout,
            main_logger=main_logger,
            log_prompt_frequency=log_prompt_frequency,
            log_eval_sample_frequency=log_eval_sample_frequency,
            et_model_path=et_model_path,
            round_num=round_num,
            discoveries=discoveries,
            round_dir=round_dir,
            discovery_events_path=discovery_events_path,
            parallel_stories=parallel_stories,
        )

        # Save final DB for this round (before rescoring with freshly trained ET)
        programs_database.save_programs_database(programs_db, round_db_path_end)
        main_logger.info(f'Round {round_num} end-of-round DB saved → {round_db_path_end}')

        # ---- Step 4: Post-round processing ----
        record = run_post_round(
            round_num=round_num,
            round_dir=round_dir,
            db_path=round_db_path_end,
            prev_round_dir=prev_round_dir,
            prev_final_train_csv=prev_final_train_csv,
            alt_training_sources_everyrnd=mr.alt_training_sources_everyrnd,
            records=records,
            round_start_time=round_start_time,
            num_stories_train=mr.num_stories_train,
            num_stories_eval=mr.num_stories_eval,
            base_seed=base_seed,
            eval_seed_offset=mr.eval_seed_offset,
            min_entities=min_entities,
            max_entities=max_entities,
            num_cands=mr.num_cands_training,
            rules_path=mr.rules_path,
            epochs=mr.et_epochs,
            batch_size=mr.et_batch_size,
            lr=mr.et_lr,
            training_seed=mr.et_training_seed,
            dataset_type=mr.et_dataset_type,
            max_final_training_size=mr.et_max_final_training_size,
            val_check_interval=mr.et_val_check_interval,
            unique_labels_path=mr.unique_labels_path,
            eval_device=mr.eval_device,
            eval_max_samples=mr.eval_max_samples,
            logger=main_logger,
        )

        # Persist records after every round
        save_records(records, records_path, logger=main_logger)
        save_discoveries(discoveries, discoveries_path, logger=main_logger)

        # Carry forward for next round
        et_model_path = record["model_path"]
        prev_final_train_csv = record["final_train_csv"]
        prev_round_dir = round_dir

    # ======================== Final summary ========================================
    main_logger.info('\n' + '=' * 80)
    main_logger.info('FUNSEARCH EXPERIMENT COMPLETED')
    main_logger.info('=' * 80)
    main_logger.info(f'Run directory: {run_dir}')
    main_logger.info(f'Rounds: {num_rounds}, Cycles/round: {num_reset}, '
                     f'Tries/sampler: {num_tries_per_sampler}')
    if records:
        import pandas as pd
        records_df = pd.DataFrame(records)
        main_logger.info('\nFinal performance table:\n' + records_df.to_string(index=False))
    main_logger.info(f'Records saved → {records_path}')


if __name__ == "__main__":
    import argparse

    # CRITICAL: Use 'spawn' instead of 'fork' to avoid CUDA/PyTorch deadlock
    mp.set_start_method('spawn', force=True)

    parser = argparse.ArgumentParser(description='Run multi-round parallel FunSearch')
    parser.add_argument('--config', type=str,
                        default='Funsearch/Collaterals/FullFlowconfigs/configAD_served_qwen3-next.json',
                        help='Path to configuration file')
    args = parser.parse_args()

    main(config_path=args.config)
