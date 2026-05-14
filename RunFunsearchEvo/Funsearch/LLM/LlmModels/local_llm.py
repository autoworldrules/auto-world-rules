"""Local LLM wrapper for code generation."""
import torch
from typing import Optional
import warnings


class LocalLLM:
    """Wrapper for locally-hosted language models for code generation."""
    
    def __init__(
        self,
        model_name: str = "deepseek-ai/deepseek-coder-1.3b-instruct",
        device: str = "auto",
        load_in_8bit: bool = True,
        load_in_4bit: bool = False,
        max_memory: Optional[dict] = None,
    ):
        """
        Initialize local LLM.
        
        Args:
            model_name: HuggingFace model identifier
            device: Device to load model on ("cuda", "cpu", or "auto")
            load_in_8bit: Use 8-bit quantization (saves ~50% VRAM)
            load_in_4bit: Use 4-bit quantization (saves ~75% VRAM)
            max_memory: Dict of max memory per device, e.g., {0: "10GB", "cpu": "30GB"}
        """
        try:
            from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
        except ImportError:
            raise ImportError(
                "Please install transformers: pip install transformers torch accelerate"
            )
        
        self.model_name = model_name
        self.device = device
        
        # Configure quantization
        quantization_config = None
        if load_in_4bit:
            quantization_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=torch.float16,
                bnb_4bit_use_double_quant=True,
                bnb_4bit_quant_type="nf4"
            )
        elif load_in_8bit:
            quantization_config = BitsAndBytesConfig(load_in_8bit=True)
        
        print(f"Loading model: {model_name}")
        print(f"Quantization: {'4-bit' if load_in_4bit else '8-bit' if load_in_8bit else 'None'}")
        
        # Load tokenizer
        self.tokenizer = AutoTokenizer.from_pretrained(
            model_name,
            trust_remote_code=True
        )
        
        # Load model
        model_kwargs = {
            "trust_remote_code": True,
            "torch_dtype": torch.float16 if device != "cpu" else torch.float32,
        }
        
        if quantization_config:
            model_kwargs["quantization_config"] = quantization_config
            model_kwargs["device_map"] = device if device == "auto" else None
        else:
            model_kwargs["device_map"] = device
        
        if max_memory:
            model_kwargs["max_memory"] = max_memory
        
        self.model = AutoModelForCausalLM.from_pretrained(
            model_name,
            **model_kwargs
        )
        
        # Set padding token if not present
        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token
        
        # Print device information
        print(f"Model loaded successfully on {device}")
        if torch.cuda.is_available() and hasattr(self.model, 'hf_device_map'):
            print(f"Device map: {self.model.hf_device_map}")
            print(f"Using GPU: {torch.cuda.get_device_name(0)}")
            print(f"VRAM allocated: {torch.cuda.memory_allocated(0) / 1e9:.2f} GB")
        elif device == "cpu":
            print("Running on CPU (slower)")
        
        print(f"Model cache location: ~/.cache/huggingface/hub/")
    
    def generate(
        self,
        prompt: str,
        max_tokens: int = 512,
        temperature: float = 0.8,
        top_p: float = 0.95,
        stop_strings: Optional[list[str]] = None,
    ) -> str:
        """
        Generate code completion for the given prompt.
        
        Args:
            prompt: The code prompt to complete
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature (higher = more random)
            top_p: Nucleus sampling threshold
            stop_strings: List of strings that stop generation
            
        Returns:
            Generated code as a string
        """
        # Tokenize input
        inputs = self.tokenizer(
            prompt,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=4096
        )
        
        # Move to device
        if self.model.device.type != "cpu":
            inputs = {k: v.to(self.model.device) for k, v in inputs.items()}
        
        # Generate
        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                do_sample=temperature > 0,
                pad_token_id=self.tokenizer.pad_token_id,
                eos_token_id=self.tokenizer.eos_token_id,
            )
        
        # Decode
        generated_text = self.tokenizer.decode(
            outputs[0][inputs["input_ids"].shape[1]:],
            skip_special_tokens=True
        )
        
        # Apply stop strings
        if stop_strings:
            for stop in stop_strings:
                if stop in generated_text:
                    generated_text = generated_text[:generated_text.index(stop)]
        
        return generated_text.strip()
    
    def format_prompt(self, code_context: str, prompt_template_path: Optional[str] = None) -> str:
        """
        Format prompt according to model-specific requirements.
        
        Args:
            code_context: The skeleton code with function to complete
            prompt_template_path: Optional path to custom prompt template file.
                                If not provided, will auto-detect based on model name.
            
        Returns:
            Formatted prompt string
        """
        import os
        print(f' here is code context being given to format_prompt: \n{code_context}.')
        # If custom template path is provided, use it
        if prompt_template_path and os.path.exists(prompt_template_path):
            with open(prompt_template_path, 'r') as f:
                template = f.read()
            return template.format(code_context=code_context)
        
        # Otherwise, auto-detect based on model name
        prompts_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'llm_prompts'
        )
        
        # Determine which template file to use based on model name
        if "deepseek" in self.model_name.lower():
            template_file = "deepseek_prompt_template.txt"
        elif "codellama" in self.model_name.lower():
            template_file = "codellama_prompt_template.txt"
        elif "phi" in self.model_name.lower():
            template_file = "phi_prompt_template.txt"
        else:
            template_file = "generic_prompt_template.txt"
        
        template_path = os.path.join(prompts_dir, template_file)
        
        # Load the template
        if os.path.exists(template_path):
            with open(template_path, 'r') as f:
                template = f.read()
            return template.format(code_context=code_context)
        else:
            # Fallback to generic format if template file not found
            print(f"Warning: Template file not found at {template_path}, using generic format")
            return f"# Complete this function:\n{code_context}\n\n"


def test_model():
    """Test function to verify model loading and generation."""
    print("Testing local LLM setup...")
    
    test_prompt = """
def priority(cand_fact: str, definite_rules_program: str) -> float:
    \"\"\"Returns priority score for candidate fact.\"\"\"
"""
    
    try:
        llm = LocalLLM(
            model_name="deepseek-ai/deepseek-coder-1.3b-instruct",
            device="auto",
            load_in_8bit=True
        )
        
        formatted = llm.format_prompt(test_prompt)
        result = llm.generate(formatted, max_tokens=256, temperature=0.7)
        
        print("\n=== Generated Code ===")
        print(result)
        print("======================\n")
        print("✓ Model test successful!")
        
    except Exception as e:
        print(f"✗ Model test failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    test_model()
