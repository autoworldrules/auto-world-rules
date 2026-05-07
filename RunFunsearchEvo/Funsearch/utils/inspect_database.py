#!/usr/bin/env python3
"""
Utility script to inspect saved ProgramsDatabase checkpoints.

Usage:
    python inspect_database.py <path_to_checkpoint.pkl>
    
Example:
    python inspect_database.py ../Logs/programs_db_checkpoint.pkl
"""
import sys
import os
import logging
from typing import Optional

this_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(this_dir, '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from DeepMindCodeReference.implementation import programs_database


def _get_logger(logger: Optional[logging.Logger] = None) -> logging.Logger:
    """Get a logger instance, creating a stdout logger if none provided."""
    if logger is not None:
        return logger
    
    # Create a logger that outputs to stdout
    logger = logging.getLogger('inspect_database')
    logger.setLevel(logging.DEBUG)
    
    # Remove any existing handlers
    logger.handlers = []
    
    # Create console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    
    # Create formatter
    formatter = logging.Formatter('%(message)s')
    console_handler.setFormatter(formatter)
    
    # Add handler to logger
    logger.addHandler(console_handler)
    
    return logger


def inspect_database_shallow(filepath: str, logger: Optional[logging.Logger] = None) -> None:
    """Load and display basic information about a saved ProgramsDatabase.
    
    Shows general information, best scores, and island statistics without
    detailed program code or per-test scores.
    
    Args:
        filepath: Path to the checkpoint file
        logger: Optional logger instance. If None, creates a stdout logger.
    """
    logger = _get_logger(logger)
    
    if not os.path.exists(filepath):
        logger.error(f"Error: File not found: {filepath}")
        return
    
    logger.debug(f"Loading database from: {filepath}")
    logger.debug("=" * 80)
    
    db = programs_database.load_programs_database(filepath)
    
    logger.debug(f"\n{'='*80}")
    logger.debug("GENERAL INFORMATION")
    logger.debug(f"{'='*80}")
    logger.debug(f"Number of islands: {len(db._islands)}")
    logger.debug(f"Function being evolved: {db._function_to_evolve}")
    logger.debug(f"Functions per prompt: {db._config.functions_per_prompt}")
    
    logger.debug(f"\n{'='*80}")
    logger.debug("BEST SCORES PER ISLAND")
    logger.debug(f"{'='*80}")
    for i, score in enumerate(db._best_score_per_island):
        logger.debug(f"Island {i}: {score:.6f}")
    
    logger.debug(f"\n{'='*80}")
    logger.debug("ISLAND DETAILS")
    logger.debug(f"{'='*80}")
    for i, island in enumerate(db._islands):
        logger.debug(f"\nIsland {i}:")
        logger.debug(f"  Total programs registered: {island._num_programs}")
        logger.debug(f"  Number of clusters: {len(island._clusters)}")
        
        if island._clusters:
            cluster_scores = [cluster.score for cluster in island._clusters.values()]
            logger.debug(f"  Cluster scores range: [{min(cluster_scores):.6f}, {max(cluster_scores):.6f}]")
            logger.debug(f"  Average cluster score: {sum(cluster_scores) / len(cluster_scores):.6f}")
    
    logger.debug(f"\n{'='*80}")
    logger.debug("SHALLOW INSPECTION COMPLETE")
    logger.debug(f"{'='*80}\n")


def inspect_database_deep(filepath: str, logger: Optional[logging.Logger] = None) -> None:
    """Load and display detailed information about a saved ProgramsDatabase.
    
    Shows all information including full program code, per-test scores,
    and detailed cluster information.
    
    Args:
        filepath: Path to the checkpoint file
        logger: Optional logger instance. If None, creates a stdout logger.
    """
    logger = _get_logger(logger)
    
    if not os.path.exists(filepath):
        logger.error(f"Error: File not found: {filepath}")
        return
    
    logger.debug(f"Loading database from: {filepath}")
    logger.debug("=" * 80)
    
    db = programs_database.load_programs_database(filepath)
    
    logger.debug(f"\n{'='*80}")
    logger.debug("GENERAL INFORMATION")
    logger.debug(f"{'='*80}")
    logger.debug(f"Number of islands: {len(db._islands)}")
    logger.debug(f"Function being evolved: {db._function_to_evolve}")
    logger.debug(f"Functions per prompt: {db._config.functions_per_prompt}")
    
    logger.debug(f"\n{'='*80}")
    logger.debug("BEST SCORES PER ISLAND")
    logger.debug(f"{'='*80}")
    for i, score in enumerate(db._best_score_per_island):
        logger.debug(f"Island {i}: {score:.6f}")
    
    logger.debug(f"\n{'='*80}")
    logger.debug("ISLAND DETAILS")
    logger.debug(f"{'='*80}")
    for i, island in enumerate(db._islands):
        logger.debug(f"\nIsland {i}:")
        logger.debug(f"  Total programs registered: {island._num_programs}")
        logger.debug(f"  Number of clusters: {len(island._clusters)}")
        
        if island._clusters:
            cluster_scores = [cluster.score for cluster in island._clusters.values()]
            logger.debug(f"  Cluster scores range: [{min(cluster_scores):.6f}, {max(cluster_scores):.6f}]")
            logger.debug(f"  Average cluster score: {sum(cluster_scores) / len(cluster_scores):.6f}")
    
    logger.debug(f"\n{'='*80}")
    logger.debug("BEST PROGRAMS (FULL TEXT)")
    logger.debug(f"{'='*80}")
    for i, program in enumerate(db._best_program_per_island):
        if program is not None:
            logger.debug(f"\nIsland {i} best program (score: {db._best_score_per_island[i]:.6f}):")
            logger.debug("-" * 80)
            logger.debug(str(program))
            logger.debug("-" * 80)
        else:
            logger.debug(f"\nIsland {i}: No program yet")
    
    logger.debug(f"\n{'='*80}")
    logger.debug("SCORES PER TEST (DETAILED)")
    logger.debug(f"{'='*80}")
    for i, scores_per_test in enumerate(db._best_scores_per_test_per_island):
        if scores_per_test is not None:
            logger.debug(f"\nIsland {i}:")
            for test_name, score in scores_per_test.items():
                logger.debug(f"  {test_name}: {score:.6f}")
        else:
            logger.debug(f"\nIsland {i}: No scores yet")
    
    logger.debug(f"\n{'='*80}")
    logger.debug("ALL PROGRAMS IN EACH ISLAND (BY CLUSTER)")
    logger.debug(f"{'='*80}")
    for i, island in enumerate(db._islands):
        logger.debug(f"\n{'='*40}")
        logger.debug(f"Island {i} - All Programs")
        logger.debug(f"{'='*40}")
        
        if not island._clusters:
            logger.debug("  No clusters/programs in this island")
            continue
            
        for cluster_idx, (signature, cluster) in enumerate(island._clusters.items()):
            logger.debug(f"\n  Cluster {cluster_idx} (Signature: {signature}, Score: {cluster.score:.6f}):")
            logger.debug(f"  Number of programs in cluster: {len(cluster._programs)}")
            
            for prog_idx, program in enumerate(cluster._programs):
                logger.debug(f"\n    Program {prog_idx + 1} (length: {cluster._lengths[prog_idx]} chars):")
                logger.debug("    " + "-" * 76)
                # Indent each line of the program
                for line in str(program).split('\n'):
                    logger.debug(f"    {line}")
                logger.debug("    " + "-" * 76)
    
    logger.debug(f"\n{'='*80}")
    logger.debug("DEEP INSPECTION COMPLETE")
    logger.debug(f"{'='*80}\n")


def print_best_program_of_island(filepath: str, island_id: int, logger: Optional[logging.Logger] = None) -> None:
    """Load database and print the full best program of a specific island.
    
    Args:
        filepath: Path to the database checkpoint file
        island_id: ID of the island to inspect (0-based index)
        logger: Optional logger instance. If None, creates a stdout logger.
    """
    logger = _get_logger(logger)
    
    if not os.path.exists(filepath):
        logger.error(f"Error: File not found: {filepath}")
        return
    
    logger.debug(f"Loading database from: {filepath}")
    db = programs_database.load_programs_database(filepath)
    
    # Validate island_id
    if island_id < 0 or island_id >= len(db._islands):
        logger.error(f"Error: Invalid island_id {island_id}. Database has {len(db._islands)} islands (0-{len(db._islands)-1})")
        return
    
    logger.debug(f"\n{'='*80}")
    logger.debug(f"BEST PROGRAM FOR ISLAND {island_id}")
    logger.debug(f"{'='*80}")
    
    # Get the best program and score
    best_program = db._best_program_per_island[island_id]
    best_score = db._best_score_per_island[island_id]
    
    if best_program is None:
        logger.debug(f"Island {island_id} has no programs yet.")
        return
    
    logger.debug(f"Score: {best_score:.6f}")
    logger.debug(f"\n{'-'*80}")
    logger.debug("Full Program:")
    logger.debug(f"{'-'*80}")
    logger.debug(str(best_program))
    logger.debug(f"{'-'*80}")
    
    # Optionally show per-test scores if available
    scores_per_test = db._best_scores_per_test_per_island[island_id]
    if scores_per_test is not None:
        logger.debug(f"\nPer-Test Scores:")
        for test_name, score in scores_per_test.items():
            logger.debug(f"  {test_name}: {score:.6f}")
    
    logger.debug(f"\n{'='*80}\n")


def main():
    if len(sys.argv) < 2:
        print("Usage: python inspect_database.py <path_to_checkpoint.pkl> [--deep|--island <id>]")
        print("Example (shallow):    python inspect_database.py ../Logs/programs_db_checkpoint.pkl")
        print("Example (deep):       python inspect_database.py ../Logs/programs_db_checkpoint.pkl --deep")
        print("Example (island):     python inspect_database.py ../Logs/programs_db_checkpoint.pkl --island 0")
        sys.exit(1)
    
    checkpoint_path = sys.argv[1]
    
    # Check for mode flags
    if len(sys.argv) > 2:
        if sys.argv[2] == '--deep':
            inspect_database_deep(checkpoint_path)
        elif sys.argv[2] == '--island':
            if len(sys.argv) < 4:
                print("Error: --island flag requires an island ID")
                print("Example: python inspect_database.py <path> --island 0")
                sys.exit(1)
            try:
                island_id = int(sys.argv[3])
                print_best_program_of_island(checkpoint_path, island_id)
            except ValueError:
                print(f"Error: Invalid island ID '{sys.argv[3]}'. Must be an integer.")
                sys.exit(1)
        else:
            print(f"Error: Unknown flag '{sys.argv[2]}'")
            print("Valid flags: --deep, --island <id>")
            sys.exit(1)
    else:
        inspect_database_shallow(checkpoint_path)


if __name__ == "__main__":
    main()
