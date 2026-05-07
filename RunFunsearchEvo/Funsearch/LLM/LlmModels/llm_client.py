"""Format prompts and call a served LLM with openai for code generation using vLLM."""
from openai import OpenAI
import torch
import os
from typing import Optional
import warnings
import logging

class LLMClient:
    """
    Prepares and sends prompts to the server
    """

    def __init__(
        self,
        model_name: str,
        base_url: str = "http://10.99.212.26:8000/v1",
        api_key: str = "EMPTY",
        logger: Optional[logging.Logger] = None,
    ):
        """
        Initialize the LLM client.

        Args:
            model_name (str): Name of the served model (e.g., "qwen3-next")
            base_url (str): vLLM server URL
            api_key (str): API key (vLLM does not require a real key)
        """
        self.model_name = model_name
        self.client = OpenAI(
            base_url=base_url,
            api_key=api_key,
        )
        self._logger = logger or logging.getLogger(__name__)
        self._logger.info(f"Initialized LLMClient for model: {model_name} at base URL: {base_url}")

    def generate(
        self,
        prompt: str,
        temperature: float = 0.8,
        max_tokens: int = 2000,
    ) -> str:
        """
        Generate a response from the model.

        Args:
            prompt (str): User input prompt
            temperature (float): Sampling temperature
            max_tokens (int): Maximum number of tokens in output

        Returns:
            str: Model response text
        """
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[
                {"role": "user", "content": prompt}
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )

        return response.choices[0].message.content


    def format_prompt(self, code_context: list, prompt_template_path: Optional[str] = None) -> list:
        """
        Format prompts according to model-specific requirements.
        
        Args:
            code_context: code string with functions to complete
            prompt_template_path: Optional path to custom prompt template file.
                                If not provided, will auto-detect based on model name.
            
        Returns:
            A formatted prompt string
        """
        self._logger.debug(f'Formatting prompt')
        # self._logger.debug(f'First code context:\\n{code_contexts[0][:200]}...')
        
        # If custom template path is provided, use it
        if prompt_template_path and os.path.exists(prompt_template_path):
            with open(prompt_template_path, 'r', encoding='utf-8') as f:
                template = f.read()
        # Otherwise, auto-detect based on model name
        else:
            prompts_dir = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                'llm_prompts'
            )
        
            # Determine which template file to use based on model name
            #if "deepseek" in self.model_name.lower():
            #    template_file = "deepseek_prompt_template.txt"
            #if "qwen3-coder-next" in self.model_name.lower():
            #    template_file = "generic_prompt_template.txt" #"qwen3_code_next_prompt_template.txt"
            #elif "codellama" in self.model_name.lower():
            #    template_file = "codellama_prompt_template.txt"
            #elif "phi" in self.model_name.lower():
            #    template_file = "phi_prompt_template.txt"
            #else:
            template_file = "generic_prompt_template.txt"
        
            template_path = os.path.join(prompts_dir, template_file)
        
            # Load the template
            if os.path.exists(template_path):
                with open(template_path, 'r', encoding='utf-8') as f:
                    template = f.read()
            else:
                # Fallback to generic format if template file not found
                print(f"Warning: Template file not found at {template_path}, using generic format")
                return [f"# Complete this function:\n{code_context}\n\n" for code_context in code_contexts]

        # Format the prompt using the template.
        # Use str.replace instead of str.format so that literal {node_id: float},
        # {i}, and other documentation braces in the template are left untouched.
        return template.replace("{code_context}", code_context)
  
        
def test_model():
    """Test function to verify model loading and generation."""
    import logging
    
    # Set up basic logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    logger = logging.getLogger(__name__)
    
    logger.info("Testing vLLM model server call setup...")
    priority_function_1 = "def Iamthebest(cand_fact: str, definite_rules_program: str, entailed_facts: str, facts_program: str):\\n\\tchooseme=1\\n\\treturn chooseme"
    priority_function_2 = "def Noitisme(cand_fact: str, definite_rules_program: str, entailed_facts: str, facts_program: str):\\n\\tchoosemeinstead = 0.9\\n\\treturn choosemeinstead"
    test_prompts = [
        priority_function_1+"\\n\\n"+priority_function_2,
        priority_function_2+"\\n\\n"+priority_function_1,
    ]
    
    try:
        llm = LLMClient(
            model_name="qwen3-next-fp8",
            base_url="http://10.99.212.26:8000/v1",
            logger=logger
        )
        formatted = llm.format_prompt(test_prompts[0])
        result = llm.generate(formatted, max_tokens=2000, temperature=0.9)
        
        logger.info("\\n=== Generated Code ===")
        logger.info(f"Result:\\n{result}")
        logger.info("======================\\n")
        logger.info("✓ Model test successful!")
        
    except Exception as e:
        logger.error(f"✗ Model test failed: {e}")
        import traceback
        logger.error(traceback.format_exc())


if __name__ == "__main__":
    test_model()

