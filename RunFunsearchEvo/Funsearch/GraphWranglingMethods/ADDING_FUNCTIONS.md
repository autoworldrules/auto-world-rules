# Adding a New Function to GraphWranglingMethods

Every new toolkit function must be wired into **six places** so that
the LLM can discover it, the auto-importer can inject it, and the test
suites can verify it.

## Checklist

### 1. Module file
Add the function to the appropriate module:

| Module | Purpose |
|---|---|
| `parsing.py` | Converting ASP strings → networkx graphs |
| `path_analysis.py` | Paths, trails, diameter, eccentricity |
| `structure.py` | Degree, neighbours, centrality, components |

Follow existing conventions:
- Accept `nx.DiGraph | nx.MultiDiGraph` as the first argument.
- Node ids are **strings** (`"0"`, `"1"`, …).
- Include a docstring with Args / Returns / Examples sections.
- Guard against missing nodes (return `None`, `0`, `False`, or `[]`).

### 2. `__init__.py`
- Add the function to the **import block** for its module.
- Add its name to `__all__`.
- Add a one-line entry to the **Quick reference** docstring catalog,
  matching the format of existing entries.

### 3. Prompt template
Add a catalog entry in
`Funsearch/LLM/llm_prompts/generic_prompt_template.txt`
inside the `## Graph-analysis toolkit` section.  Use the same
`function(args) → return_type  # short description` format.

### 4. Auto-importer registry
Add the function name (as a string) to the `_TOOLKIT_FUNCTIONS`
frozenset in `Funsearch/Sampler/process_llm_generation.py`.
This lets `detect_toolkit_usage()` recognise it in LLM-generated code
and `inject_toolkit_imports()` prepend the right import.

### 5. Unit tests
Add tests in `Funsearch/tests/test_graph_algorithms.py`.
- Use the **naming convention** from the prompt template:
  lowercase relation names (`parent_of`, `sibling_of`) and integer
  node ids (`0`, `1`, `2`).
- Test at least: normal case, edge case (missing node / empty graph),
  and one "interesting" graph (cycle, diamond, parallel edges, etc.).

### 6. Integration test
Add a priority-function string (e.g. `PRIO_NEW_FUNC`) and a test case
in `Funsearch/tests/test_graph_toolkit_flow.py`.
The test should exercise the full pipeline:
`extract_function_from_llm_output` → import injection → `exec()` → call
with realistic fact strings.

### Quick verification

After all six steps, run:

```bash
python -m pytest Funsearch/tests/test_graph_algorithms.py Funsearch/tests/test_graph_toolkit_flow.py -v
```

The meta-test `test_all_toolkit_names_covered` (in the flow tests)
checks that every name in `__all__` appears in at least one `PRIO_*`
constant — it will fail if you forgot step 6.
