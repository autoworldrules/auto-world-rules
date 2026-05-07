import sys, os
this_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(this_dir, '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from Funsearch.Evaluator.evaluator import EvaluatorET
from DeepMindCodeReference.implementation import code_manipulation
from statistics import median
import logging
from typing import Optional
from Funsearch.ProgramsDB.discovery_event_logger import DiscoveryEventLogger


class EvaluatorWrapper:
    """Wrapper class that handles analysis, program extraction, and registration."""
    
    def __init__(
        self, 
        evaluator: EvaluatorET, 
        programs_db,
        num_stories: int = 3,
        base_seed: int = 42,
        min_entities: int = 6,
        max_entities: int = 9,
        num_cands: int = 22,
        log_eval_sample_frequency: int = 10,
        discovery_event_logger: Optional[DiscoveryEventLogger] = None,
    ):
        """
        Initialize the wrapper.
        
        Args:
            evaluator: The EvaluatorET instance to use for analysis
            programs_db: The programs database to register results
            num_stories: Default number of stories to generate
            base_seed: Default base seed for random generation
            min_entities: Default minimum number of entities
            max_entities: Default maximum number of entities
            num_cands: Default number of candidates
            discovery_event_logger: Optional logger for recording new island-best discoveries
        """
        self.evaluator = evaluator
        self.programs_db = programs_db
        self.num_stories = num_stories
        self.base_seed = base_seed
        self.min_entities = min_entities
        self.max_entities = max_entities
        self.num_cands = num_cands
        self._log_eval_sample_frequency = log_eval_sample_frequency
        self._analyse_call_count = 0
        self._discovery_event_logger = discovery_event_logger
    
    def analyse(
        self,
        sample: str,
        island_id: int,
        version_generated: int,
        logger: Optional[logging.Logger] = None,
        formatted_prompt: Optional[str] = None,
    ):
        """
        Analyze a priority function sample and register it to the database.
        Compatible with the Sampler interface.
        
        Following FunSearch approach: silently discard samples that fail to execute.
        
        Args:
            sample: The priority function as a string (sampled from LLM)
            island_id: The island ID to register the program to
            version_generated: The version number when this sample was generated
            logger: Logger instance for logging (if None, uses default logger)
            formatted_prompt: The formatted LLM prompt that generated this sample
                (passed through for discovery event logging)
        """
        log = logger or logging.getLogger(__name__)
        try:
            # Analyze the priority function using default parameters
            metrics = self.evaluator.analyse(
                priority_fn_str=sample,
                num_stories=self.num_stories,
                base_seed=self.base_seed,
                min_entities=self.min_entities,
                max_entities=self.max_entities,
                num_cands=self.num_cands
            )
            
            # Check if we got valid results
            if not metrics or "mean_min_logprobs" not in metrics:
                log.warning(f'[Island {island_id}, v{version_generated}] Evaluation failed: no valid metrics returned')
                return
            
            if not metrics["mean_min_logprobs"]:
                log.warning(f'[Island {island_id}, v{version_generated}] Evaluation failed: empty scores')
                return
            
            # Extract the program function
            try:
                program = code_manipulation.text_to_program(sample)
                base_prio = program.get_function('priority')
            except ValueError as e:
                log.warning(f'[Island {island_id}, v{version_generated}] Failed to extract priority function: {e}')
                return
            except Exception as e:
                log.warning(f'[Island {island_id}, v{version_generated}] Error processing program: {type(e).__name__}: {e}')
                return
            
            # Check if function extraction returned something valid
            if not base_prio:
                log.warning(f'[Island {island_id}, v{version_generated}] get_function returned empty/None')
                return
            
            # Register the program with median score
            registered_score = -1* median(metrics["mean_min_logprobs"])
            best_before = self.programs_db._best_score_per_island[island_id]
            self.programs_db.register_program(
                program=base_prio,
                island_id=island_id,
                scores_per_test={'across_Story_scores': registered_score},
            )

            # Log discovery event if this became a new island best
            if (self._discovery_event_logger is not None
                    and registered_score > best_before):
                self._discovery_event_logger.record(
                    island_id=island_id,
                    prio_fn_str=sample,
                    formatted_prompt=formatted_prompt or "",
                    registered_score=registered_score,
                )
            
            # Print registration details
            island = self.programs_db._islands[island_id]
            num_programs_in_island = island._num_programs
            all_scores = [cluster.score for cluster in island._clusters.values()]
            
            log.info(f'\n=== Registration Summary ===')
            log.info(f'Island ID: {island_id}')
            self._analyse_call_count += 1
            if self._analyse_call_count == 1 or self._analyse_call_count % self._log_eval_sample_frequency == 0:
                log.debug(f"[call #{self._analyse_call_count}] presentregistered program is {sample}")
            log.info(f'the present score registered : {registered_score}')
            log.debug(f'Number of programs in island: {num_programs_in_island}')
            log.debug(f'All cluster scores in island: {all_scores}')
            log.debug(f'\nCluster Details:')
            for signature, cluster in island._clusters.items():
                log.debug(f'  Signature {signature}: score = {cluster.score}, {len(cluster._programs)} program(s)')
            log.debug(f'==========================\n')
            
        except Exception as e:
            # Following FunSearch: silently discard samples that fail
            log.error(f'[Island {island_id}, v{version_generated}] Sample failed and will be discarded: {type(e).__name__}: {e}')
            return
    
    def analyse_and_register_to_all_islands(
        self,
        sample: str,
        island_ids: list[int],
        version_generated: int,
        logger: Optional[logging.Logger] = None,
    ):
        """
        Analyze a priority function sample ONCE and register it to multiple islands.
        More efficient than calling analyse() multiple times for the same sample.
        
        Args:
            sample: The priority function as a string
            island_ids: List of island IDs to register the program to
            version_generated: The version number when this sample was generated
            logger: Logger instance for logging (if None, uses default logger)
        """
        log = logger or logging.getLogger(__name__)
        try:
            # Analyze the priority function ONCE
            metrics = self.evaluator.analyse(
                priority_fn_str=sample,
                num_stories=self.num_stories,
                base_seed=self.base_seed,
                min_entities=self.min_entities,
                max_entities=self.max_entities,
                num_cands=self.num_cands
            )
            
            # Check if we got valid results
            if not metrics or "mean_min_logprobs" not in metrics:
                log.warning(f'[v{version_generated}] Evaluation failed: no valid metrics returned')
                return
            
            if not metrics["mean_min_logprobs"]:
                log.warning(f'[v{version_generated}] Evaluation failed: empty scores')
                return
            
            # Extract the program function ONCE
            try:
                program = code_manipulation.text_to_program(sample)
                base_prio = program.get_function('priority')
            except ValueError as e:
                log.warning(f'[v{version_generated}] Failed to extract priority function: {e}')
                return
            except Exception as e:
                log.warning(f'[v{version_generated}] Error processing program: {type(e).__name__}: {e}')
                return
            
            # Check if function extraction returned something valid
            if not base_prio:
                log.warning(f'[v{version_generated}] get_function returned empty/None')
                return
            
            # Calculate score ONCE
            registered_score = -1 * median(metrics["mean_min_logprobs"])
            
            # Register to ALL islands
            for island_id in island_ids:
                self.programs_db.register_program(
                    program=base_prio,
                    island_id=island_id,
                    scores_per_test={'across_Story_scores': registered_score},
                )
            
            log.info(f'Registered initial program to {len(island_ids)} islands with score: {registered_score}')
            
        except Exception as e:
            # Following FunSearch: silently discard samples that fail
            log.error(f'[v{version_generated}] Sample failed and will be discarded: {type(e).__name__}: {e}')
            return 
        


