"""Configuration presets for different LLM models."""
import os

# Get the prompts directory path
_this_dir = os.path.dirname(os.path.abspath(__file__))
_prompts_dir = os.path.join(os.path.dirname(_this_dir), 'llm_prompts')

LLM_CONFIGS = {
    # Small models (<8GB VRAM)
    "deepseek-1.3b": {
        "model_name": "deepseek-ai/deepseek-coder-1.3b-instruct",
        "load_in_8bit": True,
        "max_tokens": 512,
        "temperature": 0.8,
        "prompt_template": os.path.join(_prompts_dir, "deepseek_prompt_template.txt"),
        "description": "Fastest, best for testing (~3GB VRAM)",
    },
    
    # Medium models (8-16GB VRAM) - Original configs for old local_llm
    "deepseek-6.7b": {
        "model_name": "deepseek-ai/deepseek-coder-6.7b-instruct",
        "load_in_8bit": True,
        "max_tokens": 1024,  # Increased for complete functions
        "temperature": 0.9,  # Higher for more creative/varied generation
        "prompt_template": os.path.join(_prompts_dir, "deepseek_prompt_template.txt"),
        "description": "Better quality code generation (~7-8GB VRAM with 8-bit quantization)",
    },
    
    # vLLM configs - for use with LocalVLLM class
    # Note: vLLM handles model-specific chat templates automatically via tokenizer.apply_chat_template()
    # So all vLLM configs use generic_prompt_template.txt for task instructions
    "deepseek-6.7b-vllm": {
        "model_name": "deepseek-ai/DeepSeek-Coder-V2-Lite-Instruct",  # Newer 6.7B model
        "device": "auto",
        "load_in_4bit": False,  # No quantization for vLLM
        "model_path": os.path.expanduser("~/.cache/huggingface/hub"),  # Default HF cache
        "percent_gpu_utilization": 0.8,  # Conservative GPU memory usage
        "n_gpus": 2,  # Tensor parallelism across 2 GPUs
        "max_model_len": 8192,  # Control KV cache size (important!)
        "max_tokens": 1024,  # Generation length
        "temperature": 0.8,
        "prompt_template": os.path.join(_prompts_dir, "generic_prompt_template.txt"),
        "description": "DeepSeek 6.7B with vLLM - 2x RTX 3090 (24GB each)",
    },
    
    "qwen3-code-next-vllm": {
        "model_name": "Qwen/Qwen3-Coder-Next-FP8",  # Pre-quantized model
        "device": "auto",
        "load_in_4bit": False,
        "model_path": os.path.expanduser("~/.cache/huggingface/hub"),  # Default HF cache
        "percent_gpu_utilization": 0.7,
        "n_gpus": 2,
        "max_model_len": 16384,  # Qwen can handle longer sequences
        "max_tokens": 2048,
        "temperature": 0.8,
        "prompt_template": os.path.join(_prompts_dir, "generic_prompt_template.txt"),
        "description": "Qwen 33B (FP8) with vLLM - 2x RTX 3090",
    },

        "codellama-7b": {
        "model_name": "codellama/CodeLlama-7b-Instruct-hf",
        "load_in_8bit": True,
        "max_tokens": 512,
        "temperature": 0.8,
        "prompt_template": os.path.join(_prompts_dir, "codellama_prompt_template.txt"),
        "description": "Meta's code model (~14GB VRAM)",
    },

    # Medium-Large models (>70GB VRAM)
    "deepseek-33b": {
        "model_name": "deepseek-ai/deepseek-coder-33b-instruct",
        "load_in_4bit": True,
        "max_tokens": 2048,  # Increased for complete functions
        "temperature": 0.9,  # Higher for more creative/varied generation
        "prompt_template": os.path.join(_prompts_dir, "deepseek_prompt_template.txt"),
        "description": "Better quality code generation (~GB VRAM with 8-bit quantization)",
    },

    # Prequantized Large models (>30GB VRAM)
    "qwen3-code-next-fp8": {
        "model_name": "Qwen/Qwen3-Coder-Next-FP8",

        "max_tokens": 8192,  # Increased for complete functions
        "temperature": 0.9,  # Higher for more creative/varied generation
        "prompt_template": os.path.join(_prompts_dir, "generic_prompt_template.txt"),
        "description": "Better quality code generation (~33B VRAM with 8-bit quantization)",
    },
    
    # Large models (>70GB VRAM)
    "qwen3-next": {
        "model_name": "Qwen/Qwen3-Coder-Next",
        #"load_in_4bit": True,
        "max_tokens": 8192,  # Increased for complete functions
        "temperature": 0.9,  # Higher for more creative/varied generation
        "prompt_template": os.path.join(_prompts_dir, "generic_prompt_template.txt"),
        "description": "Better quality code generation (~80GB VRAM )",
    },

    "qwen3-next-fp8": {
        "model_name": "qwen3-next-fp8",  # ID as served by vLLM server
        "max_tokens": 8192,
        "temperature": 0.9,
        "prompt_template": os.path.join(_prompts_dir, "generic_prompt_template.txt"),
        "description": "Qwen3-Coder-Next FP8 served via vLLM at 10.99.212.26:8000",
    },
    
    # Ultra-light for CPU
    "deepseek-1.3b-cpu": {
        "model_name": "deepseek-ai/deepseek-coder-1.3b-instruct",
        "load_in_8bit": False,
        "device": "cpu",
        "max_tokens": 256,
        "temperature": 0.8,
        "prompt_template": os.path.join(_prompts_dir, "deepseek_prompt_template.txt"),
        "description": "CPU-only mode (slow but no GPU needed)",
    },
}


def get_config(name: str = "deepseek-1.3b") -> dict:
    """Get configuration for a specific model."""
    if name not in LLM_CONFIGS:
        available = ", ".join(LLM_CONFIGS.keys())
        raise ValueError(f"Unknown config '{name}'. Available: {available}")
    return LLM_CONFIGS[name].copy()


def list_configs():
    """Print all available model configurations."""
    print("\n=== Available LLM Configurations ===\n")
    for name, config in LLM_CONFIGS.items():
        print(f"{name:20s} - {config['description']}")
    print("\nUsage: llm = LocalLLM(**get_config('deepseek-1.3b'))")
