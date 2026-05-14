"""
Structural and connectivity analysis of directed knowledge graphs.

Functions for inspecting degree, neighbors, edge types, connected components,
and centrality metrics.  Designed to be called from LLM-generated priority
functions alongside the parsing and path_analysis modules.

Dependencies: networkx
"""

from typing import Optional
import networkx as nx


# ---------------------------------------------------------------------------
# Degree & neighbors
# ---------------------------------------------------------------------------

def node_degree(
    G: nx.DiGraph | nx.MultiDiGraph,
    node: str,
    mode: str = "all",
) -> int:
    """Return the degree of *node*.

    Args:
        G: A directed (multi-)graph.
        node: Node id (string).
        mode: One of ``"in"``, ``"out"``, or ``"all"`` (default).

    Returns:
        Degree count.  Returns ``0`` if the node is not in the graph.

    Examples:
        >>> from Funsearch.GraphWranglingMethods.parsing import build_simple_graph
        >>> G = build_simple_graph("a(1,2).\\nb(1,3).\\nc(3,1).")
        >>> node_degree(G, '1', 'out')
        2
        >>> node_degree(G, '1', 'in')
        1
        >>> node_degree(G, '1')
        3
    """
    if node not in G:
        return 0
    if mode == "in":
        return G.in_degree(node)
    elif mode == "out":
        return G.out_degree(node)
    else:
        return G.in_degree(node) + G.out_degree(node)


def get_neighbors(
    G: nx.DiGraph | nx.MultiDiGraph,
    node: str,
    mode: str = "all",
) -> set[str]:
    """Return the set of neighboring nodes.

    Args:
        G: A directed (multi-)graph.
        node: Node id.
        mode: ``"out"`` — successors only; ``"in"`` — predecessors only;
              ``"all"`` (default) — both.

    Returns:
        Set of neighboring node ids.  Empty set if *node* is not in *G*.

    Examples:
        >>> from Funsearch.GraphWranglingMethods.parsing import build_simple_graph
        >>> G = build_simple_graph("a(1,2).\\nb(1,3).\\nc(3,1).")
        >>> sorted(get_neighbors(G, '1', 'out'))
        ['2', '3']
        >>> get_neighbors(G, '1', 'in')
        {'3'}
    """
    if node not in G:
        return set()
    if mode == "out":
        return set(G.successors(node))
    elif mode == "in":
        return set(G.predecessors(node))
    else:
        return set(G.successors(node)) | set(G.predecessors(node))


# ---------------------------------------------------------------------------
# Edge type queries
# ---------------------------------------------------------------------------

def get_edge_types_between(
    G: nx.MultiDiGraph,
    source: str,
    target: str,
) -> set[str]:
    """Return the set of relation types on edges from *source* to *target*.

    Args:
        G: A ``MultiDiGraph`` with ``relation`` edge attributes
           (as produced by :func:`parsing.build_graph`).
        source: Source node id.
        target: Target node id.

    Returns:
        Set of relation name strings.  Empty set if no edge exists.

    Examples:
        >>> from Funsearch.GraphWranglingMethods.parsing import build_graph
        >>> G = build_graph("father_of(1,3).\\nparent_of(1,3).")
        >>> sorted(get_edge_types_between(G, '1', '3'))
        ['father_of', 'parent_of']
    """
    edge_data = G.get_edge_data(source, target)
    if edge_data is None:
        return set()
    return {d.get("relation", "unknown") for d in edge_data.values()}


def get_all_edge_types(G: nx.MultiDiGraph) -> set[str]:
    """Return the set of all distinct relation types present in the graph.

    Args:
        G: A ``MultiDiGraph`` with ``relation`` edge attributes.

    Returns:
        Set of relation name strings.

    Examples:
        >>> from Funsearch.GraphWranglingMethods.parsing import build_graph
        >>> G = build_graph("father_of(1,3).\\nliving_in(3,4).")
        >>> sorted(get_all_edge_types(G))
        ['father_of', 'living_in']
    """
    return {d.get("relation", "unknown") for _, _, d in G.edges(data=True)}


def count_edges_of_type(G: nx.MultiDiGraph, relation: str) -> int:
    """Count the number of edges with a specific relation type.

    Args:
        G: A ``MultiDiGraph`` with ``relation`` edge attributes.
        relation: The relation name to count (e.g. ``"parent_of"``).

    Returns:
        Number of edges with that relation.

    Examples:
        >>> from Funsearch.GraphWranglingMethods.parsing import build_graph
        >>> G = build_graph("parent_of(1,2).\\nparent_of(3,2).\\nliving_in(1,4).")
        >>> count_edges_of_type(G, 'parent_of')
        2
    """
    return sum(1 for _, _, d in G.edges(data=True) if d.get("relation") == relation)


# ---------------------------------------------------------------------------
# Graph size
# ---------------------------------------------------------------------------

def num_nodes(G: nx.DiGraph | nx.MultiDiGraph) -> int:
    """Return the number of nodes in the graph.

    Examples:
        >>> from Funsearch.GraphWranglingMethods.parsing import build_simple_graph
        >>> num_nodes(build_simple_graph("a(1,2).\\nb(2,3)."))
        3
    """
    return G.number_of_nodes()


def num_edges(G: nx.DiGraph | nx.MultiDiGraph) -> int:
    """Return the number of edges in the graph.

    For a ``MultiDiGraph``, parallel edges are counted separately.

    Examples:
        >>> from Funsearch.GraphWranglingMethods.parsing import build_graph
        >>> num_edges(build_graph("father_of(1,2).\\nparent_of(1,2)."))
        2
    """
    return G.number_of_edges()


# ---------------------------------------------------------------------------
# Connectivity
# ---------------------------------------------------------------------------

def connected_components(G: nx.DiGraph | nx.MultiDiGraph) -> list[set[str]]:
    """Return the weakly connected components of the graph.

    Args:
        G: A directed (multi-)graph.

    Returns:
        List of sets, each set containing the node ids of one component.
        Sorted by decreasing size.

    Examples:
        >>> from Funsearch.GraphWranglingMethods.parsing import build_simple_graph
        >>> G = build_simple_graph("a(1,2).\\nb(3,4).")
        >>> components = connected_components(G)
        >>> len(components)
        2
    """
    components = list(nx.weakly_connected_components(G))
    return sorted(components, key=len, reverse=True)


def strongly_connected_components(
    G: nx.DiGraph | nx.MultiDiGraph,
) -> list[set[str]]:
    """Return the strongly connected components of the graph.

    Args:
        G: A directed (multi-)graph.

    Returns:
        List of sets, sorted by decreasing size.

    Examples:
        >>> from Funsearch.GraphWranglingMethods.parsing import build_simple_graph
        >>> G = build_simple_graph("a(1,2).\\nb(2,3).\\nc(3,1).")
        >>> sccs = strongly_connected_components(G)
        >>> len(sccs)
        1
    """
    components = list(nx.strongly_connected_components(G))
    return sorted(components, key=len, reverse=True)


def has_cycle(G: nx.DiGraph | nx.MultiDiGraph) -> bool:
    """Check whether the directed graph contains at least one cycle.

    Examples:
        >>> from Funsearch.GraphWranglingMethods.parsing import build_simple_graph
        >>> has_cycle(build_simple_graph("a(1,2).\\nb(2,3)."))
        False
        >>> has_cycle(build_simple_graph("a(1,2).\\nb(2,1)."))
        True
    """
    view = nx.DiGraph(G) if isinstance(G, nx.MultiDiGraph) else G
    try:
        nx.find_cycle(view)
        return True
    except nx.NetworkXNoCycle:
        return False


# ---------------------------------------------------------------------------
# Centrality / importance metrics
# ---------------------------------------------------------------------------

def betweenness_centrality(
    G: nx.DiGraph | nx.MultiDiGraph,
) -> dict[str, float]:
    """Compute betweenness centrality for every node.

    Betweenness centrality of a node *v* is the fraction of all shortest
    paths between other node pairs that pass through *v*.  High values
    indicate a "bridge" node that many routes must pass through.

    Args:
        G: A directed (multi-)graph.

    Returns:
        Dict mapping **string node id** → centrality score (0.0 – 1.0).
        Keys are the same string identifiers as in the graph (e.g. ``'0'``,
        ``'1'``).  Scores sum to 1.0 only for special cases; in general
        they are fractions of pair-wise shortest paths.

    Examples:
        >>> from Funsearch.GraphWranglingMethods.parsing import build_graph
        >>> G = build_graph("a_of(0,1).\\nb_of(1,2).\\nc_of(2,3).")
        >>> bc = betweenness_centrality(G)
        >>> bc
        {'0': 0.0, '1': 0.333, '2': 0.333, '3': 0.0}
        # Nodes '1' and '2' lie on all paths through the chain;
        # endpoints '0' and '3' are never "between" other pairs.

        >>> G2 = build_graph("a_of(0,1).\\na_of(0,2).\\nb_of(1,3).\\nb_of(2,3).")
        >>> bc2 = betweenness_centrality(G2)
        >>> bc2
        {'0': 0.0, '1': 0.083, '2': 0.083, '3': 0.0}
        # Two parallel routes 0→1→3 and 0→2→3; neither 1 nor 2 dominates.
    """
    view = nx.DiGraph(G) if isinstance(G, nx.MultiDiGraph) else G
    return nx.betweenness_centrality(view)


def pagerank(G: nx.DiGraph | nx.MultiDiGraph) -> dict[str, float]:
    """Compute PageRank for every node.

    PageRank measures a node's importance by counting how many other
    important nodes point to it.  Nodes that are the target of many
    incoming edges (especially from high-PageRank nodes) score highest.

    Args:
        G: A directed (multi-)graph.

    Returns:
        Dict mapping **string node id** → PageRank score.  Keys are the
        same string identifiers as in the graph (e.g. ``'0'``, ``'1'``).
        Values sum to approximately 1.0.

    Examples:
        >>> from Funsearch.GraphWranglingMethods.parsing import build_graph
        >>> G = build_graph("a_of(0,1).\\nb_of(1,2).\\nc_of(2,3).")
        >>> pr = pagerank(G)
        >>> pr
        {'0': 0.1162, '1': 0.2149, '2': 0.2988, '3': 0.3701}
        # Node '3' (chain sink) accumulates the most rank;
        # node '0' (source with no incoming) has the least.

        >>> G2 = build_graph("a_of(0,1).\\na_of(0,2).\\nb_of(1,3).\\nb_of(2,3).")
        >>> pr2 = pagerank(G2)
        >>> pr2
        {'0': 0.1375, '1': 0.1959, '2': 0.1959, '3': 0.4706}
        # Node '3' receives flow from two branches → highest rank.
    """
    view = nx.DiGraph(G) if isinstance(G, nx.MultiDiGraph) else G
    return nx.pagerank(view)


def in_degree_centrality(
    G: nx.DiGraph | nx.MultiDiGraph,
) -> dict[str, float]:
    """Compute in-degree centrality for every node.

    In-degree centrality of node *v* is its in-degree divided by (n - 1)
    where n is the number of nodes.

    Args:
        G: A directed (multi-)graph.

    Returns:
        Dict mapping node id → centrality score.
    """
    view = nx.DiGraph(G) if isinstance(G, nx.MultiDiGraph) else G
    return nx.in_degree_centrality(view)


def out_degree_centrality(
    G: nx.DiGraph | nx.MultiDiGraph,
) -> dict[str, float]:
    """Compute out-degree centrality for every node.

    Args:
        G: A directed (multi-)graph.

    Returns:
        Dict mapping node id → centrality score.
    """
    view = nx.DiGraph(G) if isinstance(G, nx.MultiDiGraph) else G
    return nx.out_degree_centrality(view)

