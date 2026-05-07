"""
Helper functions for parallel sampler execution.

This module contains functions to set up and run samplers in separate processes,
each with their own database shard, evaluators, and logger.
"""
import sys
import os
import logging
from typing import Dict, Any

this_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(this_dir, '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from DeepMindCodeReference.implementation import programs_database
from DeepMindCodeReference.implementation import code_manipulation
from Funsearch.Evaluator.evaluator import EvaluatorET
from Funsearch.FullFlow.EvaluatorMock import EvaluatorWrapper
from Funsearch.Sampler.samplerVLLMClient import Sampler
from Funsearch.ProgramsDB.discovery_event_logger import DiscoveryEventLogger


def setup_worker_logger(sampler_id: int, log_dir: str, log_level: str) -> logging.Logger:
    """
    Create a logger for this worker process.
    
    Args:
        sampler_id: ID of this sampler
        log_dir: Directory for log files
        log_level: Logging level string ('DEBUG', 'INFO', etc.)
        
    Returns:
        Configured logger instance
    """
    sampler_log_file = os.path.join(log_dir, f"sampler{sampler_id}.log")
    level = getattr(logging, log_level.upper(), logging.INFO)
    
    worker_logger = logging.getLogger(f'sampler{sampler_id}')
    worker_logger.setLevel(level)
    worker_logger.handlers = []  # Clear any inherited handlers
    
    file_handler = logging.FileHandler(sampler_log_file, mode='a')  # Append mode
    file_handler.setLevel(level)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(message)s')
    file_handler.setFormatter(formatter)
    worker_logger.addHandler(file_handler)
    
    return worker_logger


def load_worker_database(db_shard_path: str, logger: logging.Logger) -> programs_database.ProgramsDatabase:
    """
    Load this worker's database shard from disk.
    
    Args:
        db_shard_path: Path to the database shard file
        logger: Logger for this worker
        
    Returns:
        Loaded ProgramsDatabase
    """
    logger.info(f'Loading database shard from: {db_shard_path}')
    db = programs_database.load_programs_database(db_shard_path)
    logger.info(f'Database loaded with {len(db._islands)} islands')
    return db


def create_worker_evaluators(
    db: programs_database.ProgramsDatabase,
    num_evaluators: int,
    num_stories: int,
    base_seed: int,
    min_entities: int,
    max_entities: int,
    num_cands: int,
    logger: logging.Logger,
    log_eval_sample_frequency: int = 10,
    et_model_path: str = None,
    discovery_event_logger: DiscoveryEventLogger = None,
    parallel_stories: int = 1,
) -> list:
    """
    Create evaluators for this worker.
    
    Args:
        db: This worker's database
        num_evaluators: Number of evaluators to create
        num_stories: Number of stories for evaluation
        base_seed: Base seed for random generation
        min_entities: Minimum number of entities
        max_entities: Maximum number of entities
        num_cands: Number of candidates
        logger: Logger for this worker
        et_model_path: Optional path to ET model (None uses default)
        discovery_event_logger: Optional logger for recording new island-best discoveries
        parallel_stories: Max stories to generate in parallel (1 = sequential)
        
    Returns:
        List of EvaluatorWrapper instances
    """
    logger.info(f'Creating {num_evaluators} evaluator(s)...')
    evaluators = []
    
    for i in range(num_evaluators):
        underlying_evaluator = EvaluatorET(
            database=db,
            template=None,
            function_to_evolve=None,
            function_to_run=None,
            inputs=None,
            num_stories=num_stories,
            model_path=et_model_path,
            parallel_stories=parallel_stories,
        )
        evaluators.append(EvaluatorWrapper(
            evaluator=underlying_evaluator,
            programs_db=db,
            num_stories=num_stories,
            base_seed=base_seed,
            min_entities=min_entities,
            max_entities=max_entities,
            num_cands=num_cands,
            log_eval_sample_frequency=log_eval_sample_frequency,
            discovery_event_logger=discovery_event_logger,
        ))
    
    logger.info('Evaluators created successfully')
    return evaluators


def create_worker_sampler(
    db: programs_database.ProgramsDatabase,
    evaluators: list,
    sampler_id: int,
    samples_per_prompt: int,
    use_local_llm: bool,
    use_served_llm: bool,
    llm_config: str,
    max_retries: int,
    base_url: str = None,
    num_tries_per_sampler: int = 1,
    logger: logging.Logger = None,
    log_prompt_frequency: int = 10,
) -> Sampler:
    """
    Create a sampler for this worker.
    
    Args:
        db: This worker's database
        evaluators: List of evaluators
        sampler_id: ID of this sampler
        samples_per_prompt: Number of samples per prompt
        use_local_llm: Whether to use local LLM (maximum one of local or served should be True)
        use_served_llm: Whether to use served LLM (maximum one of local or served should be True)
        llm_config: LLM configuration name
        max_retries: Maximum LLM retries
        base_url: Optional base URL for served LLM API
        num_tries_per_sampler: Number of sampling iterations
        logger: Logger for this worker
        
    Returns:
        Sampler instance
    """
    logger.info('Creating sampler...')
    
    sampler = Sampler(
        database=db,
        evaluators=evaluators,
        samples_per_prompt=samples_per_prompt,
        use_local_llm=use_local_llm,
        use_served_llm=use_served_llm,
        llm_config=llm_config,
        max_retries=max_retries,
        base_url=base_url,
        num_tries_per_sampler=num_tries_per_sampler,
        use_island_partitioning=False,  # No partitioning needed - each worker has its own islands
        sampler_id=sampler_id,
        total_samplers=1,  # This worker only sees its own database
        logger=logger,
        log_prompt_frequency=log_prompt_frequency,
    )
    
    logger.info('Sampler created successfully')
    return sampler


def save_worker_database(
    db: programs_database.ProgramsDatabase,
    output_path: str,
    logger: logging.Logger
) -> None:
    """
    Save this worker's database shard to disk.
    
    Args:
        db: This worker's database
        output_path: Path to save the database
        logger: Logger for this worker
    """
    logger.info(f'Saving database shard to: {output_path}')
    programs_database.save_programs_database(db, output_path)
    logger.info('Database shard saved successfully')


def run_sampler_worker(
    sampler_id: int,
    worker_config: Dict[str, Any],
    log_dir: str,
    log_level: str,
    main_logger_queue,
    model_load_lock,
    load_ready_event,
    all_models_loaded_event
):
    """
    Main worker function - runs in a separate process.
    
    This function:
    1. Creates a logger for this worker
    2. Loads its database shard from disk
    3. Creates its own evaluators
    4. Waits for permission to load LLM model (sequential loading)
    5. Creates sampler and loads model
    6. Waits for all models to load
    7. Runs sampling in parallel with other workers
    8. Saves modified database shard to disk
    
    Args:
        sampler_id: ID of this sampler
        worker_config: Configuration dictionary with:
            - db_shard_path: Path to input database shard
            - output_db_path: Path to save output database shard
            - num_evaluators: Number of evaluators
            - num_stories: Number of stories
            - base_seed: Random seed
            - min_entities, max_entities, num_cands: Evaluator params
            - samples_per_prompt: Samples per prompt
            - use_local_llm: Whether to use LLM
            - use_served_llm: Whether to use served LLM (e.g. Qwen3-Next via API with vllm client)
            - llm_config: LLM configuration
            - max_retries: Max LLM retries
            - num_tries_per_sampler: Number of sampling iterations
        log_dir: Directory for log files
        log_level: Logging level string
        main_logger_queue: Queue to send messages to main process
        model_load_lock: Lock for sequential model loading
        load_ready_event: Event indicating this worker can load
        all_models_loaded_event: Event indicating all workers loaded
    """
    # Step 1: Set up logger
    worker_logger = setup_worker_logger(sampler_id, log_dir, log_level)
    worker_logger.info('=' * 80)
    worker_logger.info('NEW RUN/CYCLE STARTING')
    worker_logger.debug('=' * 80)
    worker_logger.info('Worker process started')
    main_logger_queue.put(f'Sampler {sampler_id} started')
    
    try:
        # Step 1b: Create discovery event logger for this worker
        discovery_logger = DiscoveryEventLogger(
            sampler_id=sampler_id,
            log_dir=log_dir,
            round_num=worker_config.get('round_num', 0),
            cycle_num=worker_config.get('cycle_num', 0),
            logger=worker_logger,
        )

        # Step 2: Load database shard
        db = load_worker_database(worker_config['db_shard_path'], worker_logger)
        worker_logger.info(f'Loaded database with {len(db._islands)} islands')
        main_logger_queue.put(f'Sampler {sampler_id} loaded database shard with {len(db._islands)} islands')
        
        # Step 3: Create evaluators
        evaluators = create_worker_evaluators(
            db=db,
            num_evaluators=worker_config['num_evaluators'],
            num_stories=worker_config['num_stories'],
            base_seed=worker_config['base_seed'],
            min_entities=worker_config['min_entities'],
            max_entities=worker_config['max_entities'],
            num_cands=worker_config['num_cands'],
            logger=worker_logger,
            log_eval_sample_frequency=worker_config.get('log_eval_sample_frequency', 10),
            et_model_path=worker_config.get('et_model_path'),
            discovery_event_logger=discovery_logger,
            parallel_stories=worker_config.get('parallel_stories', 1),
        )
        main_logger_queue.put(f'Sampler {sampler_id} created evaluators')
        
        # Step 4: Wait for permission to load model
        worker_logger.info('Waiting to load model...')
        main_logger_queue.put(f'Sampler {sampler_id} waiting to load model...')
        load_ready_event.wait()
        
        # Step 5: Load model with lock (sequential loading)
        with model_load_lock:
            worker_logger.info('Loading model (auto-sharding across GPUs)...')
            main_logger_queue.put(f'Sampler {sampler_id} loading model...')
            
            sampler = create_worker_sampler(
                db=db,
                evaluators=evaluators,
                sampler_id=sampler_id,
                samples_per_prompt=worker_config['samples_per_prompt'],
                use_local_llm=worker_config['use_local_llm'],
                use_served_llm=worker_config['use_served_llm'],
                llm_config=worker_config['llm_config'],
                max_retries=worker_config['max_retries'],
                base_url=worker_config.get('base_url'),  # Optional base_url
                num_tries_per_sampler=worker_config['num_tries_per_sampler'],
                logger=worker_logger,
                log_prompt_frequency=worker_config.get('log_prompt_frequency', 10),
            )
            
            # CRITICAL: Re-configure logging after vLLM loads
            # vLLM can override logging configuration, so we need to restore it
            worker_logger.handlers = []  # Clear handlers
            sampler_log_file = os.path.join(log_dir, f"sampler{sampler_id}.log")
            level = getattr(logging, log_level.upper(), logging.INFO)
            
            file_handler = logging.FileHandler(sampler_log_file, mode='a')
            file_handler.setLevel(level)
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(message)s')
            file_handler.setFormatter(formatter)
            worker_logger.addHandler(file_handler)
            worker_logger.setLevel(level)
            
            worker_logger.info('Model loaded successfully!')
            worker_logger.info('Logging reconfigured after vLLM initialization')
            main_logger_queue.put(f'Sampler {sampler_id} model loaded successfully!')
        
        # Step 6: Wait for all models to load
        worker_logger.info('Waiting for all models to load...')
        all_models_loaded_event.wait()
        
        # Step 7: Run sampling (PARALLEL)
        worker_logger.info('Starting sampling...')
        main_logger_queue.put(f'Sampler {sampler_id} starting sampling...')
        
        sampler.sample()
        
        worker_logger.info('Sampling completed!')
        main_logger_queue.put(f'Sampler {sampler_id} sampling completed')
        
        # Step 7b: Flush discovery events to per-worker pickle
        discovery_logger.flush()

        # Step 8: Save modified database shard
        save_worker_database(db, worker_config['output_db_path'], worker_logger)
        main_logger_queue.put(f'Sampler {sampler_id} saved database shard')
        
        worker_logger.info('Worker process completed successfully')
        main_logger_queue.put(f'==================done with sampler {sampler_id} =======================')
        
    except Exception as e:
        error_msg = f'Sampler {sampler_id} ERROR: {e}'
        worker_logger.error(error_msg)
        main_logger_queue.put(error_msg)
        import traceback
        worker_logger.error(traceback.format_exc())
        # Save database shard with whatever progress was made before failure
        try:
            save_worker_database(db, worker_config['output_db_path'], worker_logger)
            main_logger_queue.put(f'Sampler {sampler_id} saved database shard despite error')
        except Exception as save_error:
            worker_logger.error(f'Failed to save database after error: {save_error}')
            main_logger_queue.put(f'Sampler {sampler_id} FAILED to save database after error')
        
        raise


def copy_shard_as_fallback(
    input_path: str, 
    output_path: str, 
    logger: logging.Logger
) -> bool:
    """
    Copy input shard to output location as fallback.
    
    This preserves the pre-evolution state when a worker fails or times out.
    The shard will be merged with other shards as-is, without any new programs.
    
    Args:
        input_path: Path to input shard (pre-evolution state)
        output_path: Path where output shard should be saved
        logger: Logger for recording operations
        
    Returns:
        True if copy successful, False otherwise
    """
    import shutil
    
    try:
        logger.info(f'Copying input shard as fallback: {input_path} -> {output_path}')
        shutil.copy2(input_path, output_path)
        logger.info('Fallback copy successful')
        return True
    except Exception as e:
        logger.error(f'Failed to copy shard as fallback: {e}')
        import traceback
        logger.error(traceback.format_exc())
        return False


def terminate_worker_gracefully(
    process,
    worker_id: int, 
    logger: logging.Logger,
    grace_period: int = 5
) -> None:
    """
    Terminate a worker process gracefully.
    
    Process:
    1. Send SIGTERM (process.terminate()) for graceful shutdown
    2. Wait grace_period seconds for process to exit
    3. Send SIGKILL (process.kill()) if still alive after grace period
    4. Join to clean up zombie process
    
    Args:
        process: Multiprocessing Process object
        worker_id: ID of the worker (for logging)
        logger: Logger for recording operations
        grace_period: Seconds to wait for graceful termination before force kill
    """
    import time
    
    if not process.is_alive():
        logger.info(f'Worker {worker_id} (PID {process.pid}) is already dead')
        process.join(timeout=1)
        return
    
    try:
        logger.info(f'Terminating worker {worker_id} (PID {process.pid}) gracefully...')
        process.terminate()
        
        # Wait for graceful shutdown
        start = time.time()
        while time.time() - start < grace_period:
            if not process.is_alive():
                logger.info(f'Worker {worker_id} terminated gracefully')
                process.join(timeout=1)
                return
            time.sleep(0.5)
        
        # Force kill if still alive
        if process.is_alive():
            logger.warning(f'Worker {worker_id} did not terminate gracefully, forcing kill...')
            process.kill()
            time.sleep(1)
            
            if process.is_alive():
                logger.error(f'Worker {worker_id} could not be killed!')
            else:
                logger.info(f'Worker {worker_id} forcefully killed')
        
        process.join(timeout=1)
        
    except Exception as e:
        logger.error(f'Error terminating worker {worker_id}: {e}')
        import traceback
        logger.error(traceback.format_exc())


def handle_stuck_or_dead_worker(
    worker_id: int,
    process, 
    input_shard_path: str,
    output_shard_path: str,
    reason: str,
    logger: logging.Logger
) -> bool:
    """
    Handle a worker that timed out, died, or got stuck.
    
    This function performs cleanup operations:
    1. Terminates the process if still alive (graceful -> forceful)
    2. Copies input shard to output as fallback (preserves pre-evolution state)
    3. Logs incident details for debugging
    
    Args:
        worker_id: ID of the problematic worker
        process: Multiprocessing Process object
        input_shard_path: Path to worker's input shard
        output_shard_path: Path where output should be saved
        reason: Reason for failure ('timeout', 'died', 'stuck')
        logger: Logger for recording operations
        
    Returns:
        True if cleanup successful, False otherwise
    """
    logger.warning(f'=' * 80)
    logger.warning(f'Handling stuck/dead worker {worker_id}: reason={reason}')
    logger.warning(f'=' * 80)
    
    success = True
    
    # Step 1: Terminate process
    try:
        terminate_worker_gracefully(process, worker_id, logger, grace_period=5)
    except Exception as e:
        logger.error(f'Error during worker termination: {e}')
        success = False
    
    # Step 2: Copy input shard to output as fallback
    try:
        if not copy_shard_as_fallback(input_shard_path, output_shard_path, logger):
            success = False
    except Exception as e:
        logger.error(f'Error during fallback copy: {e}')
        success = False
    
    # Step 3: Log summary
    if success:
        logger.info(f'Worker {worker_id} cleanup completed successfully')
    else:
        logger.error(f'Worker {worker_id} cleanup completed with errors')
    
    logger.warning(f'=' * 80)
    
    return success
