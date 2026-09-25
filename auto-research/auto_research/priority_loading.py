from __future__ import annotations

import importlib.util
import os
from types import ModuleType
from typing import Callable


PriorityFn = Callable[[str, str, str, str], float]


def load_priority_module(path: str) -> ModuleType:
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise FileNotFoundError(path)

    mod_name = f"auto_research_priority_{abs(hash(path))}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module from {path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_priority_fn(path: str) -> PriorityFn:
    module = load_priority_module(path)
    fn = getattr(module, "priority", None)
    if fn is None or not callable(fn):
        raise ValueError(f"{path} must define a callable `priority(...)`")
    return fn

