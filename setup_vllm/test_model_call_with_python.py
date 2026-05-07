"""Minimal client to verify a running vLLM OpenAI-compatible server.

Set BASE_URL to point at your serving node:
    http://<NODE_ID>:8000/v1     (e.g. http://nid011187:8000/v1)
or http://localhost:8000/v1     when running on the same node.
"""

import os
from openai import OpenAI

MODEL_NAME = os.environ.get("MODEL_NAME", "qwen3-next")
BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000/v1")

client = OpenAI(
    base_url=BASE_URL,
    api_key="EMPTY",  # vLLM does not require a real key
)


def query_llm(prompt: str, temperature: float = 0.7, max_tokens: int = 200) -> str:
    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content


if __name__ == "__main__":
    print(query_llm("Explain quantum computing in simple terms.",
                    temperature=0.7, max_tokens=200))
