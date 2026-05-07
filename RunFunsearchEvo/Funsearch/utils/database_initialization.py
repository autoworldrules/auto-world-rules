"""  
Utilities for initializing and seeding programs databases.

Provides functions to:
- Initialize a new database with an initial program
- Load top programs from a reference database
- Register programs from reference database to a new database
"""
import logging
import os
import textwrap
from typing import Optional

from DeepMindCodeReference.implementation import programs_database
from DeepMindCodeReference.implementation import config
from DeepMindCodeReference.implementation import code_manipulation
from Funsearch.Evaluator.evaluator import EvaluatorET
from Funsearch.FullFlow.EvaluatorMock import EvaluatorWrapper


def initialize_database_with_initial_program(
    template: code_manipulation.Program,
    function_to_evolve: str,
    num_islands: int,
    priority_fn_str_ini: str,
    num_stories: int,
    base_seed: int,
    min_entities: int,
    max_entities: int,
    num_cands: int,
    logger: logging.Logger,
    et_model_path: str = None,
) -> programs_database.ProgramsDatabase:
    """
    Create a new ProgramsDatabase and register the initial program to all islands.
    
    Args:
        template: Program template
        function_to_evolve: Name of function to evolve
        num_islands: Number of islands in the database
        priority_fn_str_ini: Initial priority function string
        num_stories: Number of stories for evaluation
        base_seed: Base random seed
        min_entities: Minimum entities for story generation
        max_entities: Maximum entities for story generation
        num_cands: Number of candidates to assess
        logger: Logger instance
        
    Returns:
        ProgramsDatabase with initial program registered to all islands
    """
    logger.info(f'Creating new ProgramsDatabase with {num_islands} islands')
    programs_db = programs_database.ProgramsDatabase(
        config=config.ProgramsDatabaseConfig(functions_per_prompt=2, num_islands=num_islands),
        template=template,
        function_to_evolve=function_to_evolve,
    )
    
    logger.info('Registering initial priority function to all islands...')
    evaluator = EvaluatorET(
        database=programs_db,
        template=None,
        function_to_evolve=None,
        function_to_run=None,
        inputs=None,
        num_stories=num_stories,
        model_path=et_model_path,
    )
    evaluator_wrapper = EvaluatorWrapper(
        evaluator=evaluator,
        programs_db=programs_db,
        num_stories=num_stories,
        base_seed=base_seed,
        min_entities=min_entities,
        max_entities=max_entities,
        num_cands=num_cands
    )
    
    # Score once and register to all islands
    evaluator_wrapper.analyse_and_register_to_all_islands(
        sample=priority_fn_str_ini,
        island_ids=list(range(num_islands)),
        version_generated=0,
        logger=logger
    )
    
    return programs_db


def extract_top_programs_from_reference_db(
    reference_db_path: str,
    num_programs: int,
    logger: logging.Logger = None
) -> list[tuple[code_manipulation.Function, float, dict]]:
    """
    Load reference database and extract top N programs with unique scores.
    
    Explores all clusters across all islands to find diverse programs.
    Each cluster represents a unique score signature, and we extract
    the best-scoring programs with unique scores across all clusters.
    
    Args:
        reference_db_path: Path to reference database pickle file
        num_programs: Maximum number of top programs to extract
        logger: Logger instance (optional)
        
    Returns:
        List of tuples (program, score, scores_per_test), sorted by score descending.
        Returns only programs with unique scores.
    """
    if not os.path.exists(reference_db_path):
        if logger:
            logger.warning(f'Reference database not found at {reference_db_path}')
        return []
    
    if logger:
        logger.info(f'Loading reference database from {reference_db_path}')
    ref_db = programs_database.load_programs_database(reference_db_path)
    
    # Collect programs from all clusters across all islands
    programs_with_scores = []
    total_clusters = 0
    
    for island_id, island in enumerate(ref_db._islands):
        num_clusters = len(island._clusters)
        total_clusters += num_clusters
        if logger:
            logger.info(f'Island {island_id}: {num_clusters} clusters')
        
        # Iterate through all clusters in this island
        for signature, cluster in island._clusters.items():
            score = cluster.score
            # Sample a representative program from this cluster
            program = cluster.sample_program()
            
            # Use best_scores_per_test from island as template for key name
            best_scores_per_test = ref_db._best_scores_per_test_per_island[island_id]
            if best_scores_per_test:
                # Use the same key as in the reference db
                test_key = list(best_scores_per_test.keys())[0]
                scores_per_test = {test_key: score}
            else:
                scores_per_test = {'score': score}
            
            programs_with_scores.append((program, score, scores_per_test))
            if logger:
                logger.debug(f'Island {island_id}, Cluster signature {signature}: score = {score}')
    
    if logger:
        logger.info(f'Collected {len(programs_with_scores)} programs from {total_clusters} clusters across {len(ref_db._islands)} islands')
    
    if not programs_with_scores:
        if logger:
            logger.warning('Reference database has no programs')
        return []
    
    # Sort by score descending
    programs_with_scores.sort(key=lambda x: x[1], reverse=True)
    
    # Extract programs with unique scores only
    seen_scores = set()
    unique_programs = []
    for program, score, scores_per_test in programs_with_scores:
        if score not in seen_scores:
            seen_scores.add(score)
            unique_programs.append((program, score, scores_per_test))
            if logger:
                logger.debug(f'Selected program with unique score: {score}')
            if len(unique_programs) >= num_programs:
                break
    
    if logger:
        logger.info(f'Extracted {len(unique_programs)} programs with unique scores from reference database')
        logger.info(f'Unique scores: {[score for _, score, _ in unique_programs]}')
    
    return unique_programs


def register_reference_programs_to_database(
    programs_db: programs_database.ProgramsDatabase,
    reference_programs: list[tuple[code_manipulation.Function, float, dict]],
    num_stories: int,
    base_seed: int,
    min_entities: int,
    max_entities: int,
    num_cands: int,
    logger: logging.Logger = None,
    et_model_path: str = None,
) -> None:
    """
    Register programs from reference database into islands of the target database.
    Each island gets one reference program (if available).
    
    Args:
        programs_db: Target database to register programs into
        reference_programs: List of (program, score, scores_per_test) from reference
        num_stories: Number of stories for evaluation
        base_seed: Base random seed
        min_entities: Minimum entities for story generation
        max_entities: Maximum entities for story generation
        num_cands: Number of candidates to assess
        logger: Logger instance
    """
    if not reference_programs:
        if logger:
            logger.info('No reference programs to register')
        return
    
    if logger:
        logger.info(f'Registering {len(reference_programs)} reference programs to islands')
    
    evaluator = EvaluatorET(
        database=programs_db,
        template=None,
        function_to_evolve=None,
        function_to_run=None,
        inputs=None,
        num_stories=num_stories,
        model_path=et_model_path,
    )
    evaluator_wrapper = EvaluatorWrapper(
        evaluator=evaluator,
        programs_db=programs_db,
        num_stories=num_stories,
        base_seed=base_seed,
        min_entities=min_entities,
        max_entities=max_entities,
        num_cands=num_cands
    )
    
    num_islands = len(programs_db._islands)
    for idx, (program, ref_score, ref_scores_per_test) in enumerate(reference_programs):
        if idx >= num_islands:
            if logger:
                logger.warning(f'More reference programs ({len(reference_programs)}) than islands ({num_islands}). Stopping at island {idx}')
            break
        
        island_id = idx
        
        # Get full function string using __str__ method (includes signature and body)
        program_str = str(program)
        
        # logger.info(f'Registering reference program to island {island_id} (ref score: {ref_score:.4f})')
        # logger.debug(f'Program string length: {len(program_str)} chars')
        # logger.debug(f'Program string first 100 chars: {repr(program_str[:100])}')
        # logger.debug(f'Full program string:\n{program_str}')
        
        # Clean any leading/trailing whitespace
        program_str = program_str.strip()
        
        evaluator_wrapper.analyse(
            sample=program_str,
            island_id=island_id,
            version_generated=1,  # Version 1 since version 0 is the initial program
            logger=logger
        )
    
    if logger:
        logger.info(f'Reference programs registered. Best scores after registration: {programs_db._best_score_per_island}')


def initialize_database(
    template: code_manipulation.Program,
    function_to_evolve: str,
    num_islands: int,
    priority_fn_str_ini: str,
    num_stories: int,
    base_seed: int,
    min_entities: int,
    max_entities: int,
    num_cands: int,
    referencedb_path: Optional[str],
    logger: logging.Logger,
    et_model_path: str = None,
) -> programs_database.ProgramsDatabase:
    """
    Initialize database with initial program and optionally seed with reference programs.
    
    If referencedb_path is None:
        - Creates database and registers initial program to all islands
    
    If referencedb_path is provided:
        - Creates database and registers initial program to all islands
        - Extracts top programs with unique scores from reference database
        - Registers reference programs to islands (one per island)
        - Islands with reference programs will have 2 programs, others will have 1
    
    Args:
        template: Program template
        function_to_evolve: Name of function to evolve
        num_islands: Number of islands in the database
        priority_fn_str_ini: Initial priority function string
        num_stories: Number of stories for evaluation
        base_seed: Base random seed
        min_entities: Minimum entities for story generation
        max_entities: Maximum entities for story generation
        num_cands: Number of candidates to assess
        referencedb_path: Path to reference database pickle file (None to skip)
        logger: Logger instance
        
    Returns:
        Initialized ProgramsDatabase
    """
    # Step 1: Always initialize with initial program
    programs_db = initialize_database_with_initial_program(
        template=template,
        function_to_evolve=function_to_evolve,
        num_islands=num_islands,
        priority_fn_str_ini=priority_fn_str_ini,
        num_stories=num_stories,
        base_seed=base_seed,
        min_entities=min_entities,
        max_entities=max_entities,
        num_cands=num_cands,
        logger=logger,
        et_model_path=et_model_path,
    )
    
    # Step 2: If reference database provided, extract and register top programs
    if referencedb_path is not None:
        logger.info(f'Before importing from reference db. Best scores: {programs_db._best_score_per_island}')
        reference_programs = extract_top_programs_from_reference_db(
            reference_db_path=referencedb_path,
            num_programs=num_islands,
            logger=logger
        )
        
        if reference_programs:
            register_reference_programs_to_database(
                programs_db=programs_db,
                reference_programs=reference_programs,
                num_stories=num_stories,
                base_seed=base_seed,
                min_entities=min_entities,
                max_entities=max_entities,
                num_cands=num_cands,
                logger=logger,
                et_model_path=et_model_path,
            )
    logger.info(f'Initial programs registered. Best scores: {programs_db._best_score_per_island}')
    return programs_db
