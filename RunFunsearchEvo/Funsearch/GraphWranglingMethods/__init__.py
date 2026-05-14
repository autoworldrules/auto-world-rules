"""
GraphWranglingMethods — Graph toolkit for LLM-generated priority functions.

Provides parsing, path analysis, and structural analysis utilities that
operate on ASP-style fact strings (e.g. ``"parent_of(2,3)."``) and
networkx graph objects.

Quick reference (for prompt catalog injection)::

    # ── Parsing (from .parsing) ──
    parse_atom(atom)                                       → (relation, [args])
    break_edge(atom)                                       → (src, tgt, relation)
    text2edges(program)                                    → [(src, tgt, rel), ...]
    build_graph(facts, entailed="", cand_fact="")          → MultiDiGraph
    build_simple_graph(facts, entailed="", cand_fact="")   → DiGraph

    # ── Path analysis (from .path_analysis) ──
    has_path(G, src, tgt)                     → bool
    shortest_path_length(G, src, tgt)         → int | None
    count_paths(G, src, tgt, cutoff=10)       → int
    count_trails(G, src, tgt, cutoff=6)      → int  # trails = walks with no repeated edge; cap 6, max 50
    all_shortest_paths(G, src, tgt)           → [[node, ...], ...]
    paths_with_relations(G, src, tgt)         → [[(s,t,rel), ...], ...]
    graph_diameter(G)                         → int | None
    eccentricity(G, node)                     → int | None

    # ── Structure (from .structure) ──
    node_degree(G, node, mode='all')          → int
    get_neighbors(G, node, mode='all')        → {node, ...}
    get_edge_types_between(G, src, tgt)       → {rel, ...}
    get_all_edge_types(G)                     → {rel, ...}
    count_edges_of_type(G, relation)          → int
    num_nodes(G)                              → int
    num_edges(G)                              → int
    connected_components(G)                   → [{node, ...}, ...]
    strongly_connected_components(G)          → [{node, ...}, ...]
    has_cycle(G)                              → bool
    betweenness_centrality(G)                 → {node: float, ...}
    pagerank(G)                               → {node: float, ...}
    in_degree_centrality(G)                   → {node: float, ...}
    out_degree_centrality(G)                  → {node: float, ...}
"""

# -- Parsing --
from Funsearch.GraphWranglingMethods.parsing import (
    parse_atom,
    break_edge,
    text2edges,
    build_graph,
    build_simple_graph,
)

# -- Path analysis --
from Funsearch.GraphWranglingMethods.path_analysis import (
    has_path,
    shortest_path_length,
    count_paths,
    count_trails,
    all_shortest_paths,
    paths_with_relations,
    graph_diameter,
    eccentricity,
)

# -- Structure --
from Funsearch.GraphWranglingMethods.structure import (
    node_degree,
    get_neighbors,
    get_edge_types_between,
    get_all_edge_types,
    count_edges_of_type,
    num_nodes,
    num_edges,
    connected_components,
    strongly_connected_components,
    has_cycle,
    betweenness_centrality,
    pagerank,
    in_degree_centrality,
    out_degree_centrality,
)

__all__ = [
    # parsing
    "parse_atom", "break_edge", "text2edges", "build_graph", "build_simple_graph",
    # path_analysis
    "has_path", "shortest_path_length", "count_paths", "count_trails",
    "all_shortest_paths", "paths_with_relations", "graph_diameter", "eccentricity",
    # structure
    "node_degree", "get_neighbors", "get_edge_types_between", "get_all_edge_types",
    "count_edges_of_type", "num_nodes", "num_edges",
    "connected_components", "strongly_connected_components", "has_cycle",
    "betweenness_centrality", "pagerank", "in_degree_centrality", "out_degree_centrality",
]


# ---------------------------------------------------------------------------
# Introspection helpers (for future tool-use / dynamic discovery)
# ---------------------------------------------------------------------------

def list_functions() -> str:
    """Return a compact text catalog of all public toolkit functions.

    Intended for injection into LLM prompts or as a tool-call response
    so the model can discover available graph operations.
    """
    return __doc__ or ""


def describe_function(name: str) -> str:
    """Return the docstring of a toolkit function by name.

    Args:
        name: Function name, e.g. ``"count_paths"``.

    Returns:
        The function's docstring, or an error message if not found.
    """
    import importlib
    for module_name in (
        "Funsearch.GraphWranglingMethods.parsing",
        "Funsearch.GraphWranglingMethods.path_analysis",
        "Funsearch.GraphWranglingMethods.structure",
    ):
        mod = importlib.import_module(module_name)
        fn = getattr(mod, name, None)
        if fn is not None and callable(fn):
            return fn.__doc__ or "(no docstring)"
    return f"Function {name!r} not found in toolkit."
