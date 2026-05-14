"""
Path analysis utilities for directed knowledge graphs.

Functions for counting, measuring, and enumerating paths in graphs built
from ASP-style fact strings.  All functions accept ``networkx`` graph objects
(typically produced by :func:`parsing.build_graph` or
:func:`parsing.build_simple_graph`).

Design notes
------------
* Functions that take a *graph* accept **any** networkx DiGraph or
  MultiDiGraph.  When path-counting needs a simple graph, the function
  converts internally.
* Node identifiers are **strings** (``"0"``, ``"1"``, …) to match the
  output of the parsing module.
* A ``cutoff`` parameter is exposed wherever networkx supports it so that
  the LLM-generated priority function can cap expensive enumeration.

Dependencies: networkx
"""

from typing import Optional
import networkx as nx


# ---------------------------------------------------------------------------
# Reachability
# ---------------------------------------------------------------------------

def has_path(G: nx.DiGraph | nx.MultiDiGraph, source: str, target: str) -> bool:
    """Check whether *target* is reachable from *source* via directed edges.

    Args:
        G: A directed (multi-)graph.
        source: Source node id (string).
        target: Target node id (string).

    Returns:
        ``True`` if at least one directed path exists, ``False`` otherwise.
        Returns ``False`` if either node is not in the graph.

    Examples:
        >>> from Funsearch.GraphWranglingMethods.parsing import build_simple_graph
        >>> G = build_simple_graph("a_of(1,2).\\nb_of(2,3).")
        >>> has_path(G, '1', '3')
        True
        >>> has_path(G, '3', '1')
        False
    """
    if source not in G or target not in G:
        return False
    return nx.has_path(G, source, target)


# ---------------------------------------------------------------------------
# Shortest-path length
# ---------------------------------------------------------------------------

def shortest_path_length(
    G: nx.DiGraph | nx.MultiDiGraph,
    source: str,
    target: str,
) -> Optional[int]:
    """Return the length of the shortest directed path (in hops).

    Args:
        G: A directed (multi-)graph.
        source: Source node id.
        target: Target node id.

    Returns:
        Number of edges on the shortest path, or ``None`` when no path
        exists or either node is missing.

    Examples:
        >>> from Funsearch.GraphWranglingMethods.parsing import build_simple_graph
        >>> G = build_simple_graph("a(1,2).\\nb(2,3).\\nc(1,3).")
        >>> shortest_path_length(G, '1', '3')
        1
        >>> shortest_path_length(G, '3', '1') is None
        True
    """
    if source not in G or target not in G:
        return None
    try:
        return nx.shortest_path_length(G, source, target)
    except nx.NetworkXNoPath:
        return None


# ---------------------------------------------------------------------------
# Path counting
# ---------------------------------------------------------------------------

def count_paths(
    G: nx.DiGraph | nx.MultiDiGraph,
    source: str,
    target: str,
    cutoff: int = 10,
) -> int:
    """Count the number of simple directed paths from *source* to *target*.

    A *simple* path visits each node at most once.

    Args:
        G: A directed (multi-)graph.
        source: Source node id.
        target: Target node id.
        cutoff: Maximum path length (in edges) to consider.  Limits
                computation on dense graphs.  Defaults to ``10``.

    Returns:
        Number of simple paths up to length *cutoff*.  Returns ``0`` when
        no path exists or a node is missing.

    Examples:
        >>> from Funsearch.GraphWranglingMethods.parsing import build_simple_graph
        >>> G = build_simple_graph("a(1,2).\\nb(2,3).\\nc(1,3).")
        >>> count_paths(G, '1', '3')   # direct + via 2
        2
    """
    if source not in G or target not in G:
        return 0
    view = G
    # For MultiDiGraph, convert to simple DiGraph for path enumeration
    if isinstance(G, nx.MultiDiGraph):
        view = nx.DiGraph(G)
    return sum(1 for _ in nx.all_simple_paths(view, source, target, cutoff=cutoff))


def all_shortest_paths(
    G: nx.DiGraph | nx.MultiDiGraph,
    source: str,
    target: str,
) -> list[list[str]]:
    """Return all shortest directed paths from *source* to *target*.

    Args:
        G: A directed (multi-)graph.
        source: Source node id.
        target: Target node id.

    Returns:
        List of paths, where each path is a list of node ids.
        Returns an empty list when no path exists.

    Examples:
        >>> from Funsearch.GraphWranglingMethods.parsing import build_simple_graph
        >>> G = build_simple_graph("a(0,1).\\nb(0,2).\\nc(1,3).\\nd(2,3).")
        >>> paths = all_shortest_paths(G, '0', '3')
        >>> len(paths)  # 0→1→3 and 0→2→3
        2
    """
    if source not in G or target not in G:
        return []
    try:
        return list(nx.all_shortest_paths(G, source, target))
    except nx.NetworkXNoPath:
        return []


# ---------------------------------------------------------------------------
# Path enumeration (with relations)
# ---------------------------------------------------------------------------

def paths_with_relations(
    G: nx.MultiDiGraph,
    source: str,
    target: str,
    cutoff: int = 10,
) -> list[list[tuple[str, str, str]]]:
    """Enumerate simple paths, returning edges with their relation labels.

    Each path is a list of ``(src, tgt, relation)`` triples so that the
    priority function can reason about *which* edge types appear along paths.

    Args:
        G: A ``MultiDiGraph`` (must carry ``relation`` edge attributes,
           as produced by :func:`parsing.build_graph`).
        source: Source node id.
        target: Target node id.
        cutoff: Maximum path length.

    Returns:
        List of paths.  Each path is a list of ``(src, tgt, relation)``
        triples for every edge in the path.

    Examples:
        >>> from Funsearch.GraphWranglingMethods.parsing import build_graph
        >>> G = build_graph("father_of(1,2).\\nparent_of(2,3).")
        >>> result = paths_with_relations(G, '1', '3')
        >>> len(result)
        1
        >>> result[0]  # [(src, tgt, rel), ...]
        [('1', '2', 'father_of'), ('2', '3', 'parent_of')]
    """
    if source not in G or target not in G:
        return []
    # Get node-level simple paths first
    simple_G = nx.DiGraph(G)
    result = []
    for node_path in nx.all_simple_paths(simple_G, source, target, cutoff=cutoff):
        edge_path: list[tuple[str, str, str]] = []
        for u, v in zip(node_path[:-1], node_path[1:]):
            # Pick the first relation on this edge (arbitrary but deterministic)
            edge_data = G.get_edge_data(u, v)
            if edge_data:
                first_key = next(iter(edge_data))
                rel = edge_data[first_key].get("relation", "unknown")
            else:
                rel = "unknown"
            edge_path.append((u, v, rel))
        result.append(edge_path)
    return result


# ---------------------------------------------------------------------------
# Trail counting (walks with no repeated edge)
# ---------------------------------------------------------------------------

def count_trails(
    G: nx.DiGraph | nx.MultiDiGraph,
    source: str,
    target: str,
    cutoff: int = 6,
    max_count: int = 50,
) -> int:
    """Count trails from *source* to *target* (capped for safety).

    A **trail** is a walk in which no directed edge is traversed more than
    once.  Unlike simple paths, a trail *may* revisit nodes — it is only
    edges that must be unique.  This makes trails strictly more numerous
    than simple paths in graphs with parallel edges.

    **No NetworkX native**: ``nx.all_simple_edge_paths`` forbids repeated
    *nodes* (same as simple paths, returned as edge lists) — it is **not**
    a trail enumerator.  No mainstream Python graph package provides
    directed-multigraph trail counting, so this function uses backtracking
    DFS over edges.

    **Safety caps** (essential for real story graphs with 20–50 edges):

    * ``cutoff`` is silently capped at **6** — beyond that the
      combinatorial explosion makes exact counting infeasible.
    * ``max_count`` (default 50) triggers an early exit: once that many
      trails have been found the search stops and returns ``max_count``.
      For a *priority heuristic* the distinction between 50 and 500
      trails is irrelevant.
    * If the graph has **> 30 edges** the effective cutoff is further
      reduced to ``min(cutoff, 4)`` to keep wall-clock time bounded.

    Args:
        G: A directed (multi-)graph.
        source: Source node id (string).
        target: Target node id (string).
        cutoff: Maximum trail length in edges.  Hard cap 6.
        max_count: Stop counting once this many trails are found.

    Returns:
        Number of trails found (at most *max_count*).  Returns ``0``
        when no trail exists or either node is missing.

    Examples:
        >>> from Funsearch.GraphWranglingMethods.parsing import build_graph
        >>> G = build_graph("parent_of(1,3).\nsibling_of(1,3).")
        >>> count_trails(G, '1', '3')
        2
        >>> G2 = build_graph("parent_of(1,2).\nparent_of(2,3).")
        >>> count_trails(G2, '1', '3')
        1
    """
    if source not in G or target not in G:
        return 0

    cutoff = min(cutoff, 6)  # hard cap

    # Ensure MultiDiGraph so edges have keys for identity
    if not isinstance(G, nx.MultiDiGraph):
        G = nx.MultiDiGraph(G)

    # Extra guard for dense graphs
    if G.number_of_edges() > 30:
        cutoff = min(cutoff, 4)

    # Pre-build per-node out-edge list once
    out_edges_map: dict = {n: list(G.out_edges(n, keys=True)) for n in G.nodes()}
    count = [0]

    def _dfs(node: str, used: set, depth: int) -> None:
        if count[0] >= max_count:
            return
        if depth > cutoff:
            return
        if node == target and depth > 0:
            count[0] += 1
            if count[0] >= max_count:
                return
        for u, v, key in out_edges_map[node]:
            edge_id = (u, v, key)
            if edge_id not in used:
                used.add(edge_id)
                _dfs(v, used, depth + 1)
                used.remove(edge_id)
                if count[0] >= max_count:
                    return

    _dfs(source, set(), 0)
    return count[0]


# ---------------------------------------------------------------------------
# Diameter & eccentricity
# ---------------------------------------------------------------------------

def graph_diameter(G: nx.DiGraph | nx.MultiDiGraph) -> Optional[int]:
    """Return the diameter of the graph.

    The diameter is defined as::

        max over all pairs (u, v) of shortest_path_length(u, v)

    It measures how "spread out" the graph is — the worst-case number of
    hops needed to travel between any two nodes via the shortest route.
    A small diameter means every node can reach every other node quickly;
    a large diameter indicates a long "chain-like" structure.

    Only meaningful for strongly-connected graphs (every node reachable
    from every other node via directed edges).  Returns ``None`` if the
    graph is not strongly connected or is empty.

    Args:
        G: A directed (multi-)graph.

    Returns:
        The diameter (int) or ``None``.

    Examples:
        >>> from Funsearch.GraphWranglingMethods.parsing import build_simple_graph
        >>> # Cycle 1→2→3→1: longest shortest path is 1→3 (length 2)
        >>> G = build_simple_graph("a(1,2).\\nb(2,3).\\nc(3,1).")
        >>> graph_diameter(G)
        2
        >>> # Chain 1→2→3: not strongly connected → None
        >>> G2 = build_simple_graph("a(1,2).\\nb(2,3).")
        >>> graph_diameter(G2) is None
        True
    """
    view = nx.DiGraph(G) if isinstance(G, nx.MultiDiGraph) else G
    if len(view) == 0 or not nx.is_strongly_connected(view):
        return None
    return nx.diameter(view)


def eccentricity(
    G: nx.DiGraph | nx.MultiDiGraph,
    node: str,
) -> Optional[int]:
    """Return the eccentricity of *node*.

    Eccentricity of node *v* is defined as::

        max over all other nodes u of shortest_path_length(v, u)

    It measures how "far" the node is from the most distant reachable node.
    A node with **low eccentricity** is "central" — it can reach everything
    quickly.  A node with **high eccentricity** is "peripheral" — some
    nodes require many hops to reach from it.

    Returns ``None`` when *node* cannot reach all other nodes in the graph
    (i.e. the graph is not strongly connected from *node*).

    Args:
        G: A directed (multi-)graph.
        node: Node id (string).

    Returns:
        The eccentricity (int), or ``None`` if not all nodes are reachable.

    Examples:
        >>> from Funsearch.GraphWranglingMethods.parsing import build_simple_graph
        >>> # Cycle 1→2→3→1: max shortest path from '1' is to '3' (length 2)
        >>> G = build_simple_graph("a(1,2).\\nb(2,3).\\nc(3,1).")
        >>> eccentricity(G, '1')
        2
        >>> # Chain 1→2→3: '1' cannot reach itself via directed path → None
        >>> G2 = build_simple_graph("a(1,2).\\nb(2,3).")
        >>> eccentricity(G2, '1') is None
        True
    """
    if node not in G:
        return None
    try:
        lengths = nx.single_source_shortest_path_length(G, node)
        if len(lengths) < G.number_of_nodes():
            return None  # not all nodes reachable
        return max(lengths.values())
    except nx.NetworkXError:
        return None
