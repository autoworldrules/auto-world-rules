"""
Configuration loader with Pydantic validation for FunSearch.

This module provides:
1. Pydantic models for type-safe configuration
2. JSON config file loading with validation
3. Field descriptions preserved from inline comments
"""
import json
import os
from typing import Optional, Literal
from pydantic import BaseModel, Field, field_validator


class ParallelConfig(BaseModel):
    """Configuration for parallel execution settings."""
    
    num_samplers: int = Field(
        default=5,
        description=(
            "Number of parallel worker processes to run simultaneously. "
            "Used by run_evolution_cycle() and parallel_process_helper.run_sampler_worker(). "
            "Each worker gets a database shard and samples in parallel."
        ),
        gt=0
    )
    
    num_islands: int = Field(
        default=15,
        description=(
            "Total number of islands across all workers for evolutionary diversity. "
            "Used by programs_database.ProgramsDatabase.__init__() via ProgramsDatabaseConfig. "
            "Islands are independent sub-populations that evolve separately."
        ),
        gt=0
    )
    
    worker_timeout_after_first_completion: Optional[int] = Field(
        default=3600,
        description=(
            "Timeout in seconds for remaining workers after first worker completes. "
            "Used by run_evolution_cycle() to detect stuck/hung workers. "
            "If a worker doesn't complete within this time after the first completion, "
            "it will be terminated and its input shard copied to output as fallback. "
            "Set to None to disable this timeout."
        ),
        ge=0
    )
    
    absolute_worker_timeout: Optional[int] = Field(
        default=7200,
        description=(
            "Absolute timeout in seconds from when workers start. "
            "Safety net to prevent infinite waiting if all workers fail early. "
            "Used by run_evolution_cycle() monitoring loop. "
            "Set to None to disable this timeout."
        ),
        ge=0
    )
    
    enable_worker_timeout: bool = Field(
        default=True,
        description=(
            "Whether to enable worker timeout mechanisms. "
            "If False, workers can run indefinitely (useful for debugging). "
            "If True, workers are subject to timeout constraints above."
        )
    )


class EvaluationConfig(BaseModel):
    """Configuration for evaluation settings."""
    
    num_evaluators: int = Field(
        default=1,
        description=(
            "Number of evaluator instances per worker/process. "
            "Used by parallel_process_helper.create_worker_evaluators(). "
            "Creates EvaluatorWrapper instances that wrap EvaluatorET."
        ),
        gt=0
    )
    
    num_stories: int = Field(
        default=24,
        description=(
            "Number of stories to generate per evaluation. "
            "Used by Evaluator.evaluator.EvaluatorET.__init__() and EvaluatorMock.EvaluatorWrapper.__init__(). "
            "Determines batch size for story generation and evaluation."
        ),
        gt=0
    )
    
    base_seed: int = Field(
        default=42,
        description=(
            "Base random seed for reproducible story generation. "
            "Used by Collaterals.PrioStoryGeneratorNoRa1_1 via EvaluatorWrapper. "
            "Seeds are derived from this for different entities/stories."
        )
    )
    
    min_entities: int = Field(
        default=6,
        description=(
            "Minimum number of entities for story generation. "
            "Used by Collaterals.PrioStoryGeneratorNoRa1_1 via EvaluatorWrapper. "
            "Controls complexity of generated stories."
        ),
        gt=0
    )
    
    max_entities: int = Field(
        default=7,
        description=(
            "Maximum number of entities for story generation. "
            "Used by Collaterals.PrioStoryGeneratorNoRa1_1 via EvaluatorWrapper. "
            "Controls complexity of generated stories."
        ),
        gt=0
    )
    
    num_cands: int = Field(
        default=8,
        description=(
            "Number of candidate facts to assess before choosing one. "
            "Used by Collaterals.PrioStoryGeneratorNoRa1_1 via EvaluatorWrapper. "
            "Higher num_cands means more candidates will be assessed before one is chosen. "
            "Passed to evolved priority function for fact selection."
        ),
        gt=0
    )

    parallel_stories: int = Field(
        default=1,
        description=(
            "Maximum number of stories to generate in parallel within each "
            "evaluator call using ProcessPoolExecutor. Stories beyond this "
            "count are generated in subsequent batches. Set to 1 to disable "
            "parallel story generation."
        ),
        ge=1,
    )
    
    @field_validator('max_entities')
    @classmethod
    def check_max_greater_than_min(cls, v, info):
        if 'min_entities' in info.data and v < info.data['min_entities']:
            raise ValueError('max_entities must be >= min_entities')
        return v


class SamplingConfig(BaseModel):
    """Configuration for sampling settings."""
    
    num_tries_per_sampler: int = Field(
        default=3,
        description=(
            "Number of LLM calls each worker makes per cycle. "
            "Each call generates new code that is evaluated and inserted into one of the worker's islands. "
            "Used by run_evolution_cycle()."
        ),
        gt=0
    )
    
    num_reset: int = Field(
        default=2,
        description=(
            "Number of reset/culling cycles (evolve → reset → evolve → reset...). "
            "Used by main() loop - controls outer evolutionary loop. "
            "Each cycle: evolve with LLM, then cull weak islands, keep strong ones."
        ),
        gt=0
    )


class LLMConfig(BaseModel):
    """Configuration for LLM settings."""
    
    use_local_llm: bool = Field(
        default=True,
        description=(
            "Whether to use local LLM for code generation (False = mock/random or served). "
            "Used by Sampler.samplerVLLMClient.Sampler.__init__() and parallel_process_helper.create_worker_sampler(). "
            "If False, generates random/mock code instead of calling LLM..only for testing."
        )
    )
    

    use_served_llm: bool = Field(
        default=False,
        description=(
            "Whether to use served LLM for code generation (False = local or mock). "
            "Used by Sampler.samplerVLLMClient.Sampler.__init__() and parallel_process_helper.create_worker_sampler(). "
            "If False, generates random/mock code instead of calling LLM..only for testing."
        )
    )
    llm_model: str = Field(
        default="deepseek-33b",
        description=(
            "Model identifier for LLM configuration. "
            "Used by Sampler.sampler.Sampler._setup_llm() via llm_config parameter. "
            "Maps to model path in LlmModels directory."
        )
    )
    
    max_llm_retries: int = Field(
        default=3,
        description=(
            "Maximum retry attempts for LLM API calls on failure. "
            "Used by Sampler.sampler.Sampler.__init__() and parallel_process_helper.create_worker_sampler(). "
            "Handles transient LLM errors with exponential backoff."
        ),
        ge=0
    )
    
    base_url: Optional[str] = Field(
        default=None,
        description=(
            "Base URL for served LLM API endpoint (e.g., 'http://10.99.212.26:8000/v1'). "
            "Used when use_served_llm is True. If not provided, LLMClient will use its default base_url. "
            "Used by Sampler.samplerVLLMClient.LLM.__init__() and passed to LLMClient.__init__()."
        )
    )


class LoggingConfig(BaseModel):
    """Configuration for logging settings."""
    
    log_level: Literal['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] = Field(
        default='DEBUG',
        description=(
            "Logging verbosity level: DEBUG, INFO, WARNING, ERROR, CRITICAL. "
            "Used by parallel_process_helper.setup_worker_logger() and main() for logger configuration. "
            "DEBUG shows detailed execution info, INFO shows key milestones only."
        )
    )

    log_prompt_frequency: int = Field(
        default=10,
        description=(
            "Log the formatted LLM prompt on the 1st call and then every N-th call. "
            "Controls verbosity of prompt debug logging in samplerVLLMClient.LLM._draw_sample()."
        ),
        gt=0
    )

    log_eval_sample_frequency: int = Field(
        default=10,
        description=(
            "Log the registered program sample on the 1st call and then every N-th call. "
            "Controls verbosity of sample debug logging in EvaluatorMock.EvaluatorWrapper.analyse()."
        ),
        gt=0
    )


class DatabaseConfig(BaseModel):
    """Configuration for database persistence."""
    
    save_db_path: str = Field(
        description=(
            "Path to save/load the programs database checkpoint. "
            "Used by programs_database.save_programs_database() and load_programs_database(). "
            "Enables resuming experiments from saved state. "
            "Can be relative to project root or absolute."
        )
    )
    
    load_from_checkpoint: bool = Field(
        default=False,
        description=(
            "Whether to load existing database or create new one. "
            "Used by main() - controls initialization logic. "
            "If True and file exists: loads checkpoint; else: creates new database."
        )
    )
    
    referencedb: Optional[str] = Field(
        default=None,
        description=(
            "Path to reference database pickle file for seeding (None to skip). "
            "Used by database_initialization.initialize_database(). "
            "If provided, top programs from reference DB are extracted and registered "
            "to new database islands alongside the initial program. "
            "Can be relative to project root or absolute."
        )
    )


class TemplateConfig(BaseModel):
    """Configuration for template and evolution."""
    
    skeleton_path: str = Field(
        description=(
            "Path to skeleton file containing program structure/template. "
            "Used by code_manipulation.text_to_program() to create template Program object. "
            "Template defines the structure that evolved priority functions fit into. "
            "Can be relative to project root or absolute."
        )
    )
    
    function_to_evolve: str = Field(
        default='priority',
        description=(
            "Name of the function that the LLM will evolve. "
            "Used by programs_database.ProgramsDatabase.__init__() and database_sharding.shard_database(). "
            "Identifies which function in the template to replace with evolved versions."
        )
    )
    
    priority_fn_str_ini: str = Field(
        default="""
def priority(cand_fact: str, definite_rules_program: str, entailed_facts: str, facts_program: str) -> float:
    '''Priority function for selecting among candidate facts.'''
    return 0.0
""",
        description=(
            "Initial version of the priority function to evolve. "
            "Used by EvaluatorMock.EvaluatorWrapper.analyse() for initial program registration. "
            "This is version 0 registered to all islands; LLM evolves improved versions."
        )
    )


class MultiRoundConfig(BaseModel):
    """Configuration for multi-round FunSearch with ET retraining.

    Each 'round' consists of ``num_reset`` evolution cycles followed by
    post-round processing: extracting the best priority function, generating
    training / evaluation CSVs, retraining the EdgeTransformer, and recording
    performance metrics.
    """

    num_rounds: int = Field(
        default=1,
        description=(
            "Number of outer rounds. Each round runs num_reset evolution "
            "cycles, then retrains the ET model from the best priority "
            "function. Set to 1 to disable multi-round logic (legacy mode)."
        ),
        ge=1,
    )

    base_run_dir: str = Field(
        default="Funsearch/Logs/runs",
        description=(
            "Root directory for run outputs. A datetime-stamped sub-directory "
            "(the *run_dir*) is created inside, and each round gets its own "
            "sub-directory within the run_dir."
        ),
    )

    resume_run_dir: Optional[str] = Field(
        default=None,
        description=(
            "Path to a previous run_dir to resume from. When set, the run "
            "picks up from the first incomplete round, reusing the ET model "
            "and database from the last completed round without retraining "
            "or rescoring. Set to null/None for a fresh run."
        ),
    )

    alt_training_sources_init: Optional[list[str]] = Field(
        default=None,
        description=(
            "List of CSV paths used to train the initial EdgeTransformer "
            "(ET_0, before round 1 evolution). Only used once. Paths are "
            "resolved relative to the project root."
        ),
    )

    alt_training_sources_everyrnd: Optional[list[str]] = Field(
        default=None,
        description=(
            "List of CSV paths merged into every round's final_train.csv "
            "alongside base_train.csv and the previous round's "
            "final_train.csv. Empty/null means no extra sources."
        ),
    )

    # -- Story generation for post-round CSV creation -----------------------
    num_stories_train: int = Field(
        default=100,
        description=(
            "Number of stories to generate when creating base_train.csv from "
            "the best priority function at the end of each round."
        ),
        gt=0,
    )

    num_stories_eval: int = Field(
        default=100,
        description=(
            "Number of stories to generate when creating eval.csv from the "
            "best priority function at the end of each round."
        ),
        gt=0,
    )

    eval_seed_offset: int = Field(
        default=10000,
        description=(
            "Added to evaluation.base_seed to obtain the seed for eval.csv "
            "generation, ensuring it differs from base_train.csv."
        ),
    )

    # -- ET training hyper-parameters ----------------------------------------
    et_epochs: int = Field(
        default=100,
        description="Number of training epochs for the EdgeTransformer.",
        gt=0,
    )

    et_batch_size: int = Field(
        default=32,
        description="Batch size for EdgeTransformer training.",
        gt=0,
    )

    et_lr: float = Field(
        default=1e-3,
        description="Learning rate for EdgeTransformer training.",
        gt=0,
    )

    et_training_seed: int = Field(
        default=42,
        description="Random seed for EdgeTransformer training.",
    )

    et_dataset_type: str = Field(
        default="no_ambiguity_v2",
        description="Dataset type passed to the training routine.",
    )

    et_max_final_training_size: Optional[int] = Field(
        default=None,
        description=(
            "If set, the final merged training CSV is randomly subsampled to "
            "at most this many rows before training."
        ),
    )

    et_val_check_interval: int = Field(
        default=10,
        description="Run validation every N epochs during ET training.",
        gt=0,
    )

    # -- ET evaluation hyper-parameters -------------------------------------
    eval_device: str = Field(
        default="cuda",
        description="Device for model evaluation ('cuda' or 'cpu').",
    )

    eval_max_samples: Optional[int] = Field(
        default=None,
        description=(
            "If set, randomly sample at most this many rows from each test "
            "CSV during evaluation."
        ),
    )

    unique_labels_path: Optional[str] = Field(
        default=None,
        description=(
            "Path to unique_labels.pkl. Defaults to "
            "Funsearch/Evaluator/unique_labels.pkl."
        ),
    )

    rules_path: Optional[str] = Field(
        default=None,
        description=(
            "Path to rules file for story generation. Defaults to "
            "Funsearch/Collaterals/NoRa1.1.txt."
        ),
    )

    num_cands_training: int = Field(
        default=25,
        description=(
            "Number of candidate facts for story generation during post-round "
            "CSV creation (may differ from evaluation.num_cands used during "
            "FunSearch cycles)."
        ),
        gt=0,
    )


class FunSearchConfig(BaseModel):
    """Complete FunSearch configuration."""
    
    parallel: ParallelConfig = Field(default_factory=ParallelConfig)
    evaluation: EvaluationConfig = Field(default_factory=EvaluationConfig)
    sampling: SamplingConfig = Field(default_factory=SamplingConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    database: DatabaseConfig
    template: TemplateConfig
    multi_round: MultiRoundConfig = Field(default_factory=MultiRoundConfig)
    
    @field_validator('database', 'template', 'multi_round', mode='before')
    @classmethod
    def resolve_paths(cls, v):
        """Resolve relative paths to absolute paths relative to project root."""
        if isinstance(v, dict):
            # Get project root (assuming this file is in Funsearch/utils/)
            this_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.abspath(os.path.join(this_dir, '..', '..'))
            
            # Resolve paths in database config
            if 'save_db_path' in v and v['save_db_path'] and not os.path.isabs(v['save_db_path']):
                v['save_db_path'] = os.path.join(project_root, v['save_db_path'])
            
            if 'referencedb' in v and v['referencedb'] and not os.path.isabs(v['referencedb']):
                v['referencedb'] = os.path.join(project_root, v['referencedb'])
            
            # Resolve paths in template config
            if 'skeleton_path' in v and v['skeleton_path'] and not os.path.isabs(v['skeleton_path']):
                v['skeleton_path'] = os.path.join(project_root, v['skeleton_path'])
            
            # Resolve paths in multi_round config
            if 'base_run_dir' in v and v['base_run_dir'] and not os.path.isabs(v['base_run_dir']):
                v['base_run_dir'] = os.path.join(project_root, v['base_run_dir'])
            
            if 'resume_run_dir' in v and v['resume_run_dir'] and not os.path.isabs(v['resume_run_dir']):
                v['resume_run_dir'] = os.path.join(project_root, v['resume_run_dir'])
            
            if 'alt_training_sources_init' in v and v['alt_training_sources_init']:
                v['alt_training_sources_init'] = [
                    os.path.join(project_root, p) if not os.path.isabs(p) else p
                    for p in v['alt_training_sources_init']
                ]
            
            if 'alt_training_sources_everyrnd' in v and v['alt_training_sources_everyrnd']:
                v['alt_training_sources_everyrnd'] = [
                    os.path.join(project_root, p) if not os.path.isabs(p) else p
                    for p in v['alt_training_sources_everyrnd']
                ]
            
            if 'unique_labels_path' in v and v['unique_labels_path'] and not os.path.isabs(v['unique_labels_path']):
                v['unique_labels_path'] = os.path.join(project_root, v['unique_labels_path'])
            
            if 'rules_path' in v and v['rules_path'] and not os.path.isabs(v['rules_path']):
                v['rules_path'] = os.path.join(project_root, v['rules_path'])
        
        return v


def load_config(config_path: str, project_root: Optional[str] = None) -> FunSearchConfig:
    """
    Load and validate FunSearch configuration from JSON file.
    
    Args:
        config_path: Path to JSON config file (relative to project root or absolute)
        project_root: Optional project root path (auto-detected if not provided)
        
    Returns:
        Validated FunSearchConfig object
        
    Raises:
        FileNotFoundError: If config file doesn't exist
        ValueError: If config validation fails
        json.JSONDecodeError: If JSON is malformed
        
    Example:
        >>> config = load_config('Funsearch/Collaterals/FullFlowconfigs/configJB.json')
        >>> print(config.parallel.num_samplers)
        5
    """
    # Determine project root
    if project_root is None:
        this_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.abspath(os.path.join(this_dir, '..', '..'))
    
    # Resolve config path
    if not os.path.isabs(config_path):
        config_path = os.path.join(project_root, config_path)
    
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config file not found: {config_path}")
    
    # Load and parse JSON
    with open(config_path, 'r') as f:
        config_dict = json.load(f)
    
    # Remove _comment fields (used for inline documentation in JSON)
    def remove_comments(obj):
        if isinstance(obj, dict):
            return {k: remove_comments(v) for k, v in obj.items() if not k.startswith('_')}
        elif isinstance(obj, list):
            return [remove_comments(item) for item in obj]
        return obj
    
    config_dict = remove_comments(config_dict)
    
    # Validate and create config object
    config = FunSearchConfig(**config_dict)
    
    return config


def save_config(config: FunSearchConfig, config_path: str, project_root: Optional[str] = None):
    """
    Save FunSearch configuration to JSON file.
    
    Args:
        config: FunSearchConfig object to save
        config_path: Path to save JSON config (relative to project root or absolute)
        project_root: Optional project root path (auto-detected if not provided)
    """
    # Determine project root
    if project_root is None:
        this_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.abspath(os.path.join(this_dir, '..', '..'))
    
    # Resolve config path
    if not os.path.isabs(config_path):
        config_path = os.path.join(project_root, config_path)
    
    # Create directory if needed
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    
    # Convert to dict and save
    config_dict = config.model_dump()
    
    with open(config_path, 'w') as f:
        json.dump(config_dict, f, indent=2)
