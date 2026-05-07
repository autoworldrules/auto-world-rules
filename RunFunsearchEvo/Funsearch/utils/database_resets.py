"""
Database reset utilities for culling weak islands and keeping strong ones.
"""
import logging
from DeepMindCodeReference.implementation import programs_database


def reset_islands(
    db: programs_database.ProgramsDatabase,
    logger: logging.Logger = None
) -> programs_database.ProgramsDatabase:
    """
    Reset weaker half of islands by culling them and repopulating from stronger islands.
    
    This function calls the built-in reset_islands() method of ProgramsDatabase,
    which:
    - Sorts islands by their best score
    - Resets the weaker half (keeps their top program but resets to version 0)
    - Copies best programs from stronger islands to repopulate the weak islands
    
    Args:
        db: ProgramsDatabase to reset
        logger: Optional logger for reporting reset actions
        
    Returns:
        The same database object after reset (modified in-place)
    """
    if logger:
        logger.info(f'Resetting islands. Current state:')
        logger.info(f'  Number of islands: {len(db._islands)}')
        logger.info(f'  Best scores per island: {db._best_score_per_island}')
        logger.info(f'  Programs per island: {[island._num_programs for island in db._islands]}')
    
    # Call the built-in reset method
    db.reset_islands()
    
    if logger:
        logger.info(f'After reset:')
        logger.info(f'  Number of islands: {len(db._islands)}')
        logger.info(f'  Best scores per island: {db._best_score_per_island}')
        logger.info(f'  Programs per island: {[island._num_programs for island in db._islands]}')
    
    return db
   