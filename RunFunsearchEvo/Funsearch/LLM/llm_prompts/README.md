# LLM Prompt Templates

This directory contains prompt templates for different LLM models used in FunSearch.

## Files

- `deepseek_prompt_template.txt` - Template for DeepSeek Coder models
- `codellama_prompt_template.txt` - Template for CodeLlama models  
- `phi_prompt_template.txt` - Template for Phi models
- `generic_prompt_template.txt` - Generic fallback template

## Usage

The templates use `{code_context}` as a placeholder that gets replaced with the actual code skeleton during prompt formatting.

Templates are loaded by `LocalLLM.format_prompt()` method based on the model name.
