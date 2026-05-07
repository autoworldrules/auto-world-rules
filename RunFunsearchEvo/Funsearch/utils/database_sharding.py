"""
Utilities for sharding and merging ProgramsDatabase across parallel workers.

This module provides functions to:
1. Split a database into multiple independent databases (sharding)
2. Merge multiple databases back into one (merging)

Used for parallel execution where each worker needs its own database.
"""
import os
import sys
from typing import List, Optional

this_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(this_dir, '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from DeepMindCodeReference.implementation import programs_database
from DeepMindCodeReference.implementation import config as db_config


def shard_database(
    source_db: programs_database.ProgramsDatabase,
    num_shards: int,
) -> List[programs_database.ProgramsDatabase]:
    """
    Split a ProgramsDatabase into multiple independent databases.
    
    Each shard gets a subset of islands. Islands are distributed as evenly
    as possible across shards.
    
    Args:
        source_db: The original database to shard
        num_shards: Number of shards to create
        
    Returns:
        List of ProgramsDatabase objects, one per shard
        
    Example:
        If source_db has 5 islands and num_shards=2:
        - Shard 0 gets islands [0, 1, 2] (3 islands)
        - Shard 1 gets islands [3, 4] (2 islands)
    """
    if num_shards <= 0:
        raise ValueError(f"num_shards must be > 0, got {num_shards}")
    
    total_islands = len(source_db._islands)
    if total_islands == 0:
        raise ValueError("Cannot shard database with 0 islands")
    
    # Calculate how many islands each shard should get
    islands_per_shard = [total_islands // num_shards] * num_shards
    remainder = total_islands % num_shards
    
    # Distribute remainder islands (one extra to first 'remainder' shards)
    for i in range(remainder):
        islands_per_shard[i] += 1
    
    shards = []
    island_idx = 0
    
    for shard_id in range(num_shards):
        num_islands_this_shard = islands_per_shard[shard_id]
        
        # Create new database with fewer islands
        shard_db = programs_database.ProgramsDatabase(
            config=db_config.ProgramsDatabaseConfig(
                functions_per_prompt=source_db._config.functions_per_prompt,
                num_islands=num_islands_this_shard,
            ),
            template=source_db._template,
            function_to_evolve=source_db._function_to_evolve,
        )
        
        # Copy islands from source to shard
        for local_island_id in range(num_islands_this_shard):
            source_island_id = island_idx
            source_island = source_db._islands[source_island_id]
            shard_island = shard_db._islands[local_island_id]
            
            # Copy all programs from source island to shard island
            for cluster in source_island._clusters.values():
                # Use cluster's actual score, not island's best score
                cluster_scores = {'across_Story_scores': cluster.score}
                
                for program_idx, program in enumerate(cluster._programs):
                    # Register program in shard with cluster's actual score
                    shard_db.register_program(
                        program=program,
                        island_id=local_island_id,
                        scores_per_test=cluster_scores
                    )
            
            island_idx += 1
        
        shards.append(shard_db)
    
    return shards


def merge_databases(
    shard_dbs: List[programs_database.ProgramsDatabase],
    template=None,
    function_to_evolve: Optional[str] = None,
    functions_per_prompt: Optional[int] = None,
) -> programs_database.ProgramsDatabase:
    """
    Merge multiple ProgramsDatabase shards into one unified database.
    
    Args:
        shard_dbs: List of database shards to merge
        template: Template for the merged database (uses first shard's if None)
        function_to_evolve: Function name (uses first shard's if None)
        functions_per_prompt: Config value (uses first shard's if None)
        
    Returns:
        A new ProgramsDatabase containing all islands from all shards
        
    Example:
        shard_dbs[0] has 3 islands → becomes islands [0, 1, 2] in merged
        shard_dbs[1] has 2 islands → becomes islands [3, 4] in merged
    """
    if not shard_dbs:
        raise ValueError("Cannot merge empty list of databases")
    
    # Use first shard's metadata if not provided
    if template is None:
        template = shard_dbs[0]._template
    if function_to_evolve is None:
        function_to_evolve = shard_dbs[0]._function_to_evolve
    if functions_per_prompt is None:
        functions_per_prompt = shard_dbs[0]._config.functions_per_prompt
    
    # Calculate total islands
    total_islands = sum(len(db._islands) for db in shard_dbs)
    
    # Create merged database
    merged_db = programs_database.ProgramsDatabase(
        config=db_config.ProgramsDatabaseConfig(
            functions_per_prompt=functions_per_prompt,
            num_islands=total_islands,
        ),
        template=template,
        function_to_evolve=function_to_evolve,
    )
    
    # Copy programs from all shards
    merged_island_id = 0
    
    for shard_db in shard_dbs:
        for local_island_id, shard_island in enumerate(shard_db._islands):
            # Copy all programs from this shard island to merged database
            for cluster in shard_island._clusters.values():
                # Use cluster's actual score, not island's best score
                cluster_scores = {'across_Story_scores': cluster.score}
                
                for program_idx, program in enumerate(cluster._programs):
                    # Register in merged database with cluster's actual score
                    merged_db.register_program(
                        program=program,
                        island_id=merged_island_id,
                        scores_per_test=cluster_scores
                    )
            
            merged_island_id += 1
    
    return merged_db


def distribute_islands(total_islands: int, num_workers: int) -> List[int]:
    """
    Calculate how many islands each worker should get.
    
    Distributes islands as evenly as possible.
    
    Args:
        total_islands: Total number of islands to distribute
        num_workers: Number of workers
        
    Returns:
        List where result[i] = number of islands for worker i
        
    Example:
        >>> distribute_islands(5, 2)
        [3, 2]  # Worker 0 gets 3 islands, worker 1 gets 2
        >>> distribute_islands(10, 3)
        [4, 3, 3]  # As even as possible
    """
    if num_workers <= 0:
        raise ValueError(f"num_workers must be > 0, got {num_workers}")
    if total_islands <= 0:
        raise ValueError(f"total_islands must be > 0, got {total_islands}")
    
    base_count = total_islands // num_workers
    remainder = total_islands % num_workers
    
    result = []
    for i in range(num_workers):
        # First 'remainder' workers get one extra island
        if i < remainder:
            result.append(base_count + 1)
        else:
            result.append(base_count)
    
    return result
