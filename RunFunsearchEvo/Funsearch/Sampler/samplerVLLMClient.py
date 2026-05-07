# Copyright 2023 DeepMind Technologies Limited
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================

"""Class for sampling new programs."""
from collections.abc import Collection, Sequence
import ast
import sys
import os
from typing import Optional

this_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(this_dir, '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import numpy as np
import logging
from typing import Optional

from DeepMindCodeReference.implementation import evaluator
from DeepMindCodeReference.implementation import programs_database
from Funsearch.Sampler.process_llm_generation import extract_function_from_llm_output


class LLM:
    """Language model that predicts continuation of provided source code."""

    def __init__(
        self, 
        samples_per_prompt: int,
        use_local_llm: bool = False,
        use_served_llm: bool = False,
        llm_config: Optional[str] = "deepseek-1.3b",
        max_retries: int = 5,
        base_url: Optional[str] = None,
        logger: Optional[logging.Logger] = None,
        log_prompt_frequency: int = 10,
    ) -> None:
        """
        Initialize LLM sampler.
        
        Args:
            samples_per_prompt: Number of samples to generate per prompt
            use_local_llm: If True, use local LLM. If False, use placeholder.
            use_served_llm: If True, use served LLM via API.
            llm_config: Name of LLM config from llm_configs.py (e.g., "deepseek-1.3b")
            max_retries: Maximum number of retries if LLM fails to generate valid function
            base_url: Optional base URL for served LLM API (only used when use_served_llm=True)
            logger: Logger instance for logging
        """
        self._samples_per_prompt = samples_per_prompt
        self._use_local_llm = use_local_llm
        self._use_served_llm = use_served_llm
        self._local_llm = None
        self._max_retries = max_retries
        self._prompt_template = None  # Initialize here
        self._logger = logger or logging.getLogger(__name__)
        self._model_name = llm_config  # Initialize model name for served LLM
        self._log_prompt_frequency = log_prompt_frequency
        self._draw_sample_call_count = 0
        
        if use_served_llm:
            try:
                from Funsearch.LLM.LlmModels.llm_client import LLMClient
                from Funsearch.LLM.LlmModels.llm_configs import get_config
                self._logger.info(" initializing LLMClient successfully!")
                config = get_config(llm_config)
                self._logger.info(f"The model {llm_config} will be served through VLLM and OpenAI calls")

                # Extract generation parameters (not used in __init__)
                self._max_tokens = config.pop('max_tokens', 512)
                self._temperature = config.pop('temperature', 0.8)
                self._prompt_template = config.pop('prompt_template', None)  # Store prompt template path
                config.pop('description', None)  # Remove description from config
                
                # Add logger to config
                config['logger'] = self._logger
                
                # Now pass only the valid __init__ parameters
                if base_url:
                    self._served_llm = LLMClient(model_name=self._model_name, base_url=base_url, logger=self._logger)
                    self._logger.info(f"LLMClient initialized with custom base_url: {base_url}")
                else:
                    self._served_llm = LLMClient(model_name=self._model_name, logger=self._logger)
                    self._logger.info("LLMClient initialized with default base_url")
                self._logger.info("LLMClient initialized successfully! We use temperature: " 
                + str(self._temperature) + " and max tokens: " + str(self._max_tokens)
                )
                
            except Exception as e:
                self._logger.error(f"Failed to initialize OpenAI API: {e}")
                self._logger.error("Install requirements: uv pip install -e '.[openai]'")
                import traceback
                self._logger.error(traceback.format_exc())
                raise RuntimeError(
                    f"Failed to initialize OpenAI API. "
                    f"Ensure OpenAI API and dependencies are installed: uv pip install -e '.[openai]'"
                ) from e
        else:
            raise NotImplementedError(f'''Currently only use_served_llm=True is supported for FullFlowParallel_llm_client. 
                                      Set use_local_llm: false, use_served_llm: true, and give valid base_url in config file''')

    def _draw_sample(self, prompt: str) -> tuple[str, str]:
        """Returns ``(extracted_code, formatted_prompt)`` for `prompt`."""
        if self._use_served_llm and self._served_llm is not None:
            # Use served LLM (e.g., through OpenAI API) to generate code, with retries
            formatted_prompt = self._served_llm.format_prompt(prompt, self._prompt_template)
            self._draw_sample_call_count += 1
            if self._draw_sample_call_count == 1 or self._draw_sample_call_count % self._log_prompt_frequency == 0:
                self._logger.debug(f'[call #{self._draw_sample_call_count}] Formatted prompt being given to served LLM:\\n{formatted_prompt}...')
            generated = ""
            for attempt in range(self._max_retries):
                try:
                    generated = self._served_llm.generate(
                        prompt=formatted_prompt,
                        max_tokens=self._max_tokens,
                        temperature=self._temperature,
                    )
                except Exception as gen_error:
                    self._logger.error(f'[Attempt {attempt + 1}/{self._max_retries}] Served LLM generation encountered error')
                    self._logger.error(f'Error details: {gen_error}')
                    import traceback
                    self._logger.error(traceback.format_exc())
                    continue
                
                self._logger.info(f'[Attempt {attempt + 1}/{self._max_retries}] Raw generated by served LLM:\\n{generated[:300]}...')
                
                # Extract only the complete function definition
                extracted, is_valid = extract_function_from_llm_output(generated)
                
                if is_valid:
                    print(f'Successfully extracted function on attempt {attempt + 1}')
                    return extracted, formatted_prompt
                else:
                    self._logger.warning(f'[Attempt {attempt + 1}/{self._max_retries}] Failed to extract valid function, retrying...')
            
            # All retries exhausted - return placeholder string instead of raising error
            self._logger.error(
                f"Served LLM failed to generate a valid function after {self._max_retries} attempts. "
                f"Last generated text: {generated[:100] if generated else '(no output)'}... Returning placeholder."
            )
            return "No legitimate generation from llm", formatted_prompt
        else:   
            self._logger.error("LLM generation requested but no valid LLM is initialized. Returning placeholder.")
            raise NotImplementedError("need self._served_llm to be initialized for LLM generation. Check your config settings for use_served_llm and base_url.")

    def draw_samples(self, prompt: str) -> list[tuple[str, str]]:
        """Returns multiple ``(extracted_code, formatted_prompt)`` tuples."""
        return [self._draw_sample(prompt) for _ in range(self._samples_per_prompt)]


class Sampler:
    """Node that samples program continuations and sends them for analysis."""

    def __init__(
            self,
            database: programs_database.ProgramsDatabase,
            evaluators: Sequence[evaluator.Evaluator],
            samples_per_prompt: int,
            use_local_llm: bool = False,
            use_served_llm: bool = False,
            llm_config: Optional[str] = "deepseek-1.3b",
            max_retries: int = 5,
            base_url: Optional[str] = None,
            num_tries_per_sampler: int = 1,
            use_island_partitioning: bool = False,
            sampler_id: Optional[int] = None,
            total_samplers: Optional[int] = None,
            logger: Optional[logging.Logger] = None,
            log_prompt_frequency: int = 10,
    ) -> None:
        self._database = database
        self._evaluators = evaluators
        self._logger = logger or logging.getLogger(__name__)
        self._llm = LLM(samples_per_prompt, use_local_llm, use_served_llm, llm_config, max_retries, base_url, self._logger, log_prompt_frequency)
        self._num_tries_per_sampler = num_tries_per_sampler
        self._use_island_partitioning = use_island_partitioning
        self._sampler_id = sampler_id
        self._total_samplers = total_samplers
        

    def sample(self):
        """Continuously gets prompts, samples programs, sends them for analysis."""
        for try_num in range(self._num_tries_per_sampler):
            self._logger.debug(f'Sampler try {try_num + 1}/{self._num_tries_per_sampler}')
            
            # Get a prompt from the correct island
            while True:
                prompt = self._database.get_prompt()
                
                # If island partitioning is enabled, retry until we get a prompt from the correct island
                if self._use_island_partitioning:
                    if prompt.island_id % self._total_samplers != self._sampler_id:
                        # self._logger.info(f'Sampler {self._sampler_id} skipping island {prompt.island_id} '
                        #       f'(island_id % {self._total_samplers} = {prompt.island_id % self._total_samplers}, '
                        #       f'expected {self._sampler_id}), retrying...')
                        continue
                break
            
            self._logger.debug(f'Sampler {self._sampler_id if self._use_island_partitioning else ""} '
                  f'got prompt for island {prompt.island_id}')
            samples = self._llm.draw_samples(prompt.code)
            # This loop can be executed in parallel on remote evaluator machines.
            for sample, formatted_prompt in samples:
                chosen_evaluator = np.random.choice(self._evaluators)
                chosen_evaluator.analyse(
                        sample, prompt.island_id, prompt.version_generated, self._logger,
                        formatted_prompt=formatted_prompt)
