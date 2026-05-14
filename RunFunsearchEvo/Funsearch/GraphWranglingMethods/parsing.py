"""
Parsing utilities for converting ASP-style atom/fact strings into graph objects.

This module bridges the gap between the text-based representation of knowledge
graph facts (e.g. "parent_of(2,3).") used throughout the FunSearch pipeline
and networkx graph structures that enable algorithmic analysis.

Designed to be called from LLM-generated priority functions. Every public
function has a stable signature and returns plain Python / networkx types.

Dependencies: networkx
"""

import re
from typing import Optional
import networkx as nx


# ---------------------------------------------------------------------------
# Atom-level parsing
# ---------------------------------------------------------------------------

def parse_atom(atom: str) -> tuple[str, list[str]]:
    """Parse a single ASP atom string into its relation name and arguments.

    Args:
        atom: An ASP-style atom, e.g. ``"parent_of(2,3)."`` or ``"is_person(0)."``.
              Trailing period and whitespace are stripped automatically.

    Returns:
        A tuple ``(relation, args)`` where *relation* is the predicate name
        (e.g. ``"parent_of"``) and *args* is a list of argument strings
        (e.g. ``["2", "3"]``).

    Examples:
        >>> parse_atom("parent_of(2,3).")
        ('parent_of', ['2', '3'])
        >>> parse_atom("is_person(0)")
        ('is_person', ['0'])
        >>> parse_atom("living_in_same_place(1, 4).")
        ('living_in_same_place', ['1', '4'])
    """
    atom = atom.strip().rstrip(".")
    m = re.match(r"([a-zA-Z_][a-zA-Z0-9_]*)\((.+)\)", atom)
    if not m:
        raise ValueError(f"Cannot parse atom: {atom!r}")
    relation = m.group(1)
    args = [a.strip() for a in m.group(2).split(",")]
    return relation, args


def break_edge(atom: str) -> tuple[str, str, str]:
    """Parse a single directed-edge atom into ``(source, target, relation)``.

    For binary predicates (two arguments), returns the two nodes and the
    relation.  For unary predicates like ``is_person(0)`` (which represent
    self-loops), source and target are the same node.

    Args:
        atom: ASP-style atom string, e.g. ``"father_of(1,3)."``.

    Returns:
        ``(source, target, relation)`` — all strings.

    Examples:
        >>> break_edge("father_of(1,3).")
        ('1', '3', 'father_of')
        >>> break_edge("is_male(2,2).")
        ('2', '2', 'is_male')
        >>> break_edge("is_person(0).")
        ('0', '0', 'is_person')
    """
    relation, args = parse_atom(atom)
    if len(args) == 2:
        return args[0], args[1], relation
    elif len(args) == 1:
        return args[0], args[0], relation  # self-loop
    else:
        raise ValueError(
            f"Expected 1 or 2 arguments in atom, got {len(args)}: {atom!r}"
        )


def text2edges(program: str) -> list[tuple[str, str, str]]:
    """Parse a multi-line facts/entailed-facts string into edge triples.

    Each non-empty line that contains a predicate call is parsed into a
    ``(source, target, relation)`` triple via :func:`break_edge`.
    Lines that cannot be parsed (comments, blank lines, constraints) are
    silently skipped.

    Args:
        program: Multi-line string where each line is an ASP atom ending in
                 a period, e.g.::

                     is_person(0).
                     father_of(1,3).
                     living_in(3,4).

    Returns:
        List of ``(source, target, relation)`` triples.

    Examples:
        >>> text = "is_person(0).\\nfather_of(1,3).\\nliving_in(3,4)."
        >>> text2edges(text)
        [('0', '0', 'is_person'), ('1', '3', 'father_of'), ('3', '4', 'living_in')]
    """
    edges: list[tuple[str, str, str]] = []
    for line in program.splitlines():
        line = line.strip()
        if not line or line.startswith("%"):  # skip blanks & ASP comments
            continue
        try:
            edges.append(break_edge(line))
        except ValueError:
            continue  # skip unparseable lines (rules, constraints, etc.)
    return edges


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def build_graph(
    facts_program: str,
    entailed_facts: str = "",
    cand_fact: str = "",
    include_self_loops: bool = True,
) -> nx.MultiDiGraph:
    """Build a directed multigraph from fact strings.

    Constructs a ``networkx.MultiDiGraph`` where each edge carries a
    ``relation`` attribute.  Multiple edges of different types between the
    same pair of nodes are supported (hence *multi*-digraph).

    Args:
        facts_program: The explicit graph edges (the ``facts_program``
            argument of the priority function).
        entailed_facts: Optional entailed edges to include in the graph.
            Pass ``""`` to build a graph from explicit facts only.
        cand_fact: Optional single candidate edge atom (the ``cand_fact``
            argument of the priority function).  If provided, the candidate
            edge is added to the graph as well.
        include_self_loops: If *False*, unary predicates (self-loops such
            as ``is_person(0).``) are omitted from the graph.

    Returns:
        A ``networkx.MultiDiGraph`` with string node ids and edge attribute
        ``relation``.

    Examples:
        >>> G = build_graph("father_of(1,3).\\nliving_in(3,4).")
        >>> G.number_of_nodes()
        3
        >>> G = build_graph("father_of(1,3).", "uncle_of(1,5).", "son_of(3,1).")
        >>> sorted(G.nodes())
        ['1', '3', '5']
    """
    G = nx.MultiDiGraph()
    all_text = facts_program
    if entailed_facts:
        all_text += "\n" + entailed_facts
    if cand_fact:
        all_text += "\n" + cand_fact
    for src, tgt, rel in text2edges(all_text):
        if not include_self_loops and src == tgt:
            continue
        G.add_edge(src, tgt, relation=rel)
    return G


def build_simple_graph(
    facts_program: str,
    entailed_facts: str = "",
    cand_fact: str = "",
    include_self_loops: bool = False,
) -> nx.DiGraph:
    """Build a simple directed graph (at most one edge per node pair).

    Unlike :func:`build_graph`, duplicate edges between the same nodes are
    collapsed.  This is useful for path-counting and connectivity queries
    where edge multiplicity is irrelevant.

    Args:
        facts_program: Explicit graph edges.
        entailed_facts: Optional entailed edges.
        cand_fact: Optional single candidate edge atom to include.
        include_self_loops: Whether to include self-loop edges.

    Returns:
        A ``networkx.DiGraph`` with string node ids.

    Examples:
        >>> G = build_simple_graph("father_of(1,3).\\nmother_of(1,3).")
        >>> G.number_of_edges()
        1
        >>> G2 = build_simple_graph("father_of(1,3).", cand_fact="son_of(3,1).")
        >>> sorted(G2.nodes())
        ['1', '3']
    """
    G = nx.DiGraph()
    all_text = facts_program
    if entailed_facts:
        all_text += "\n" + entailed_facts
    if cand_fact:
        all_text += "\n" + cand_fact
    for src, tgt, rel in text2edges(all_text):
        if not include_self_loops and src == tgt:
            continue
        G.add_edge(src, tgt)
    return G
