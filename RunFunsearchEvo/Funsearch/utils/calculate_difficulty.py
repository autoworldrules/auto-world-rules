"""
Utility module for calculating query difficulty metrics using derivation analysis.

This module computes difficulty metrics for queries in generated stories, following
the definitions from Section 3 (Problem Formulation) of the paper:
https://openreview.net/pdf?id=HZJiIog5XH

TERMINOLOGY CLARIFICATION
-------------------------
- BRANCHES/VARIANTS/REFINEMENTS: When ambiguous facts are present, multiple program 
  variants exist (e.g., "1{fact1; fact2}1." creates 2 branches). Some branches may 
  lead to contradictions. In non-ambiguous stories, there is exactly 1 branch which 
  is always positive (no contradiction). Use `get_program_variants()` to enumerate.

- RELATIONSHIPS: Multiple true relationships can hold between a source-target pair.
  `query_label` contains all such relationships. These hold in ALL positive branches
  (branches that don't lead to contradictions).

METRIC DEFINITIONS  
------------------
All metrics are computed by MAXIMIZING across:
  (1) All relationships between source and target (query_labels)
  (2) All branches/variants (only 1 for non-ambiguous stories)

- chain_len (aka ReasoningDepth): Number of rules in the derivation chain for a 
  single relationship. The final metric is MAX across all relationships and branches.

- BL (Backward Length): Ratio of rules to unique entities in a derivation.
  BL = #rules / #unique_entities. Final metric is MAX across all relationships/branches.

- OPEC (Off-Path Entity Count): Count of atoms in derivation that are not on the
  direct path between source and target entities.

SPECIAL CASE: Non-Ambiguous Stories (Single Positive Branch)
------------------------------------------------------------
When there is only 1 branch and it is positive (no contradiction):
  - chain_len = ReasoningDepth = ReasoningDepth_only_pos_derivations
  - BL = BL_no_contradiction  
  - OPEC = OPEC_pos_refn

The '_only_pos_derivations' / '_no_contradiction' / '_pos_refn' suffixes indicate
metrics computed only over positive (non-contradiction) branches.
"""

import sys
import os
import ast
import logging
import re
import pandas as pd 
from typing import Dict, Any, Tuple, List, Set, Optional
from dataclasses import dataclass

# Add WhenNoPathsLeadToRome to path for imports
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
when_no_paths_root = os.path.join(project_root, 'WhenNoPathsLeadToRome')
if when_no_paths_root not in sys.path:
    sys.path.insert(0, when_no_paths_root)

from WhenNoPathsLeadToRome.utils.FindDerivationForPositiveProgram import PositiveProgramTP
from WhenNoPathsLeadToRome.utils.wrangle_derivations import count_non_path_atoms_in_branch
from WhenNoPathsLeadToRome.utils.wrangle_derivations2 import extract_entities


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class RelationshipDerivation:
    """
    Holds derivation information for a single relationship (query_label).
    
    Attributes
    ----------
    query_atom : str
        Normalized atom string, e.g., "parent_of(1,2)"
    derivation_chain : str
        Full derivation chain string with rules and facts separated by '|'
    rules : Set[str]
        Set of rule strings in the derivation
    facts : Set[str]
        Set of fact strings in the derivation (without 'fact:' prefix)
    chain_len : int
        Number of rules in the derivation (ReasoningDepth for this relationship)
    num_facts : int
        Number of facts required for derivation
    bl : float
        BL metric for this relationship: #rules / #unique_entities
    opec : int
        OPEC metric for this relationship: count of non-path atoms
    """
    query_atom: str
    derivation_chain: str
    rules: Set[str]
    facts: Set[str]
    chain_len: int  # This IS the ReasoningDepth for this single relationship
    num_facts: int
    bl: float
    opec: int


@dataclass 
class BranchDerivations:
    """
    Holds all derivations for a single branch/variant.
    
    Attributes
    ----------
    branch_idx : int
        Branch index (0 for non-ambiguous stories)
    outcome : str
        Either "unique stable model" or "contradiction"
    relationships : Dict[str, RelationshipDerivation]
        Map from query_atom -> RelationshipDerivation
    """
    branch_idx: int
    outcome: str
    relationships: Dict[str, RelationshipDerivation]


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def build_complete_program(story_info: Dict[str, Any]) -> str:
    """
    Build complete ASP program from story_info.
    
    Parameters
    ----------
    story_info : dict
        Must contain 'world_rules' and 'story_facts'.
        
    Returns
    -------
    str
        Complete ASP program (world_rules + story_facts).
    """
    world_rules = story_info.get("world_rules", "")
    story_facts = story_info.get("story_facts", [])
    facts_str = "\n".join(story_facts)
    return world_rules + "\n" + facts_str


_UNARY_PREDS = {"is_person", "is_place"}  # only truly 1-ary preds in NoRa1.1

# Labels that appear capitalised in unique_labels.pkl / query_label but must be
# lowercased to match ASP predicates (Clingo rejects uppercase-initial atoms).
_LABEL_TO_ASP = {"Not_living_in": "not_living_in"}
# Inverse: ASP predicate name -> display label (for restoring in output)
_ASP_TO_LABEL = {v: k for k, v in _LABEL_TO_ASP.items()}


def normalize_query(query_edge: Tuple[int, int], query_relation: str) -> str:
    """
    Create normalized query atom string.
    
    Parameters
    ----------
    query_edge : tuple of (int, int)
        Source and target entity IDs.
    query_relation : str
        Relation/predicate name.
        
    Returns
    -------
    str
        Normalized query string like "parent_of(1,2)" (no spaces).
        Only truly unary predicates (is_person, is_place) are reduced
        to single-argument form; all others keep binary form even when
        both arguments are equal (e.g. is_female(4,4)).
    """
    query_relation = _LABEL_TO_ASP.get(query_relation, query_relation)
    if query_relation in _UNARY_PREDS:
        query_str = f"{query_relation}({query_edge[0]})"
    else:
        query_str = f"{query_relation}({query_edge[0]},{query_edge[1]})"
    return query_str.replace(" ", "")


def disentangle_chain(chain: str) -> Tuple[Set[str], Set[str]]:
    """
    Split derivation chain string into rules and facts.
    
    The derivation chain has format:
        "fact: atom1  |  rule1 :- body1.  |  fact: atom2  |  rule2 :- body2."
    
    Parameters
    ----------
    chain : str
        Derivation chain string with segments separated by '|'.
        
    Returns
    -------
    rules : Set[str]
        Rule segments (those containing ':-' and not starting with 'fact:')
    facts : Set[str]
        Fact segments (starting with 'fact:', prefix removed)
    """
    segments = [seg.strip() for seg in chain.split("|") if seg.strip()]
    rules = set()
    facts = set()
    
    for seg in segments:
        if seg.startswith("fact:"):
            fact = seg[len("fact:"):].strip()
            facts.add(fact)
        elif ":-" in seg:  # It's a rule
            rules.add(seg)
    
    return rules, facts


def compute_bl_for_derivation(rules: Set[str], facts: Set[str]) -> float:
    """
    Compute BL (Backward Length) metric for a single derivation.
    
    BL = #rules / #unique_entities
    
    Entities are extracted from facts, with special handling for predicates
    like 'has_property', 'belongs_to_group', 'belongs_to' where only the
    first argument counts as an entity.
    
    Parameters
    ----------
    rules : Set[str]
        Set of rule strings
    facts : Set[str]
        Set of fact strings (without 'fact:' prefix)
        
    Returns
    -------
    float
        BL metric (0.0 if no entities found)
    """
    if not facts:
        return 0.0
    
    entities = extract_entities(facts)
    num_entities = len(entities) if entities else 1
    return len(rules) / num_entities


def compute_opec_for_derivation(
    derivation_dict: Dict[str, str], 
    query_edge: Tuple[int, int]
) -> int:
    """
    Compute OPEC (Off-Path Entity Count) for a derivation.
    
    OPEC counts atoms in the derivation that are not on the direct path
    between source and target entities.
    
    Parameters
    ----------
    derivation_dict : Dict[str, str]
        Map from query_atom to derivation_chain string.
        Can be a single relationship or all relationships together.
    query_edge : tuple of (int, int)
        Source and target entity IDs
        
    Returns
    -------
    int
        OPEC count
    """
    # Check if all derivations are direct facts (no rules)
    all_direct_facts = all(
        chain.startswith("fact:") and ":-" not in chain
        for chain in derivation_dict.values()
    )
    if all_direct_facts:
        return 0
    
    # Use the reference implementation directly - no exception catching!
    return count_non_path_atoms_in_branch(derivation_dict, query_edge)


# =============================================================================
# CORE DERIVATION COMPUTATION
# =============================================================================

def compute_derivation_for_relationship(
    query_edge: Tuple[int, int],
    query_relation: str,
    deriv_df,
    logger: Optional[logging.Logger] = None
) -> RelationshipDerivation:
    """
    Compute derivation and metrics for a single relationship.
    
    Parameters
    ----------
    query_edge : tuple of (int, int)
        Source and target entity IDs
    query_relation : str  
        The relation/predicate name
    deriv_df : pandas.DataFrame
        Pre-computed derivations dataframe from PositiveProgramTP
    logger : logging.Logger, optional
        
    Returns
    -------
    RelationshipDerivation
        Complete derivation info including chain_len, BL, OPEC
    """
    query_atom = normalize_query(query_edge, query_relation)
    
    # Find derivation in dataframe
    query_deriv = deriv_df[deriv_df['derived_atom_str'] == query_atom]
    
    if query_deriv.empty:
        raise ValueError(
            f"query_atom '{query_atom}' not found in deriv_df. "
            f"deriv_df has {len(deriv_df)} rows. "
            f"Available atoms (sample): {deriv_df['derived_atom_str'].head(10).tolist()}"
        )

    row = query_deriv.iloc[0]
    derivation_chain = row['derivation_chain']
    chain_len = row['chain_len']  # Number of rules from PositiveProgramTP
    rules, facts = disentangle_chain(derivation_chain)
    
    # Compute BL for this relationship
    bl = compute_bl_for_derivation(rules, facts)
    
    # Compute OPEC for this relationship using dict format
    single_deriv_dict = {query_atom: derivation_chain}
    opec = compute_opec_for_derivation(single_deriv_dict, query_edge)
    
    return RelationshipDerivation(
        query_atom=query_atom,
        derivation_chain=derivation_chain,
        rules=rules,
        facts=facts,
        chain_len=chain_len,
        num_facts=len(facts),
        bl=bl,
        opec=opec
    )


def compute_branch_derivations(
    story_info: Dict[str, Any],
    query_edge: Tuple[int, int],
    query_labels: List[str],
    logger: Optional[logging.Logger] = None
) -> Optional[BranchDerivations]:
    """
    Compute derivations for all relationships in a single branch.
    
    For non-ambiguous stories, this is the only branch (branch_idx=0).
    
    Parameters
    ----------
    story_info : dict
        Story information with 'world_rules' and 'story_facts'
    query_edge : tuple of (int, int)
        Source and target entity IDs
    query_labels : list of str
        All relationships to compute derivations for
    logger : logging.Logger, optional
        
    Returns
    -------
    BranchDerivations or None
        Branch derivations, or None if no stable model exists
    """
    if logger is None:
        logger = logging.getLogger(__name__)
    
    # Build and run ASP solver ONCE for this branch
    complete_program = build_complete_program(story_info)
    engine = PositiveProgramTP(complete_program, logger=logger)
    engine.parse_program()
    final_model, step_count = engine.compute_least_model()
    
    if final_model is None:
        logger.warning(f"No stable model found for query edge {query_edge}")
        return None
    
    # XXXX debug - complete_program and final_model
    # print("XXXX debug | complete_program:\n", complete_program)
    # print("XXXX debug | final_model:", final_model)
    # print("XXXX debug | length of final_model:", len(final_model))

    # Build derivations dataframe ONCE
    deriv_df = engine._build_derivations_df(final_model)
    deriv_df['derived_atom_str'] = deriv_df['derived_atom'].apply(lambda x: x.replace(' ', ''))

    # XXXX debug - deriv_df summary + top-3 longest derivation_chain among chain_len<=7
    # _debug_print_deriv_df(deriv_df)

    # Compute derivation for each relationship
    relationships = {}
    for _i, query_rel in enumerate(query_labels):
        rel_deriv = compute_derivation_for_relationship(
            query_edge, query_rel, deriv_df, logger
        )
        # XXXX debug - rel_deriv (first only)
        # if _i == 0:
        #     print(f"XXXX debug | rel_deriv [{query_rel}]: {rel_deriv}")
        relationships[rel_deriv.query_atom] = rel_deriv
    
    return BranchDerivations(
        branch_idx=0,
        outcome="unique stable model",
        relationships=relationships
    )


# =============================================================================
# METRIC AGGREGATION
# =============================================================================

def aggregate_metrics_across_relationships(
    branch: BranchDerivations
) -> Dict[str, Any]:
    """
    Aggregate metrics across all relationships in a branch.
    
    Metrics are MAXIMIZED across relationships:
    - chain_len (ReasoningDepth): MAX of per-relationship chain_len
    - BL: MAX of per-relationship BL  
    - OPEC: MAX of per-relationship OPEC
    
    Parameters
    ----------
    branch : BranchDerivations
        Branch with all relationship derivations
        
    Returns
    -------
    dict
        Aggregated metrics:
        - max_chain_len: int (this IS the ReasoningDepth)
        - max_bl: float
        - max_opec: int
        - all_rules: Set[str] (union of all rules)
        - all_facts: Set[str] (union of all facts)
        - derivations_dict: Dict[str, str] (for display)
    """
    max_chain_len = 0
    max_bl = 0.0
    max_opec = 0
    all_rules = set()
    all_facts = set()
    derivations_dict = {}
    
    for query_atom, rel_deriv in branch.relationships.items():
        # MAX across relationships
        max_chain_len = max(max_chain_len, rel_deriv.chain_len)
        max_bl = max(max_bl, rel_deriv.bl)
        max_opec = max(max_opec, rel_deriv.opec)
        
        # Union for aggregates
        all_rules.update(rel_deriv.rules)
        all_facts.update(rel_deriv.facts)
        
        # Store for display
        derivations_dict[query_atom] = rel_deriv.derivation_chain
    
    return {
        'max_chain_len': max_chain_len,
        'max_bl': max_bl,
        'max_opec': max_opec,
        'all_rules': all_rules,
        'all_facts': all_facts,
        'derivations_dict': derivations_dict
    }


# =============================================================================
# MAIN API
# =============================================================================

def calculate_difficulty_metrics(
    story_info: Dict[str, Any],
    query_edge: Tuple[int, int],
    query_labels: List[str],
    logger: Optional[logging.Logger] = None
) -> Dict[str, Any]:
    """
    Calculate comprehensive difficulty metrics for a query.
    
    This is the main entry point. It computes derivations for all relationships
    and aggregates metrics by taking MAX across relationships and branches.
    
    For non-ambiguous stories (single positive branch):
        chain_len = ReasoningDepth = ReasoningDepth_only_pos_derivations
        BL = BL_no_contradiction
        OPEC = OPEC_pos_refn
    
    Parameters
    ----------
    story_info : dict
        Story information containing 'world_rules' and 'story_facts'.
    query_edge : tuple of (int, int)
        Query entity pair (source, target).
    query_labels : list of str
        All relationships that hold between source and target.
    logger : logging.Logger, optional
        Logger instance.
        
    Returns
    -------
    dict
        Dictionary with difficulty metrics:
        - derivation_chain: str (display format: {branch_idx: {atom: chain}})
        - chain_len: int (MAX rules across all relationships/branches = ReasoningDepth)
        - num_facts_required: int (total unique facts across all relationships)
        - sum_facts_world_rules: int
        - ReasoningDepth_only_pos_derivations: int (same as chain_len for positive branch)
        - ReasoningWidth: int (number of unique derivation variants, 1 for non-ambiguous)
        - BL_no_contradiction: float (same as BL for positive branch)
        - BL: float (MAX BL across all relationships/branches)
        - OPEC: int (MAX OPEC across all relationships/branches)
        - OPEC_pos_refn: int (same as OPEC for positive branch)
    """
    if logger is None:
        logger = logging.getLogger(__name__)
    
    # Compute derivations for all relationships in this branch
    branch = compute_branch_derivations(story_info, query_edge, query_labels, logger)
    
    if branch is None:
        # No stable model - return zeros
        return {
            'derivation_chain': "{}",
            'chain_len': 0,
            'num_facts_required': 0,
            'sum_facts_world_rules': 0,
            'ReasoningDepth_only_pos_derivations': 0,
            'ReasoningWidth': 0,
            'BL_no_contradiction': 0.0,
            'BL': 0.0,
            'OPEC': 0,
            'OPEC_pos_refn': 0
        }
    
    # Aggregate metrics across all relationships (MAX)
    agg = aggregate_metrics_across_relationships(branch)
    
    # For non-ambiguous stories with single positive branch:
    # chain_len = ReasoningDepth = ReasoningDepth_only_pos_derivations
    # BL = BL_no_contradiction
    # OPEC = OPEC_pos_refn
    chain_len = agg['max_chain_len']  # This IS ReasoningDepth
    bl = round(agg['max_bl'], 2)
    opec = agg['max_opec']
    
    num_facts_required = len(agg['all_facts'])
    sum_facts_world_rules = chain_len + num_facts_required
    
    # Format derivation_chain for display: {branch_idx: {atom: chain_str}}
    # Remap ASP predicate names back to display labels (e.g. not_living_in -> Not_living_in)
    display_derivations = {}
    for atom, chain in agg['derivations_dict'].items():
        display_atom = atom
        for asp_pred, display_pred in _ASP_TO_LABEL.items():
            if display_atom.startswith(asp_pred + '('):
                display_atom = display_pred + display_atom[len(asp_pred):]
                break
        display_derivations[display_atom] = chain
    combined_derivation = str({branch.branch_idx: display_derivations})
    
    return {
        'derivation_chain': combined_derivation,
        'chain_len': chain_len,
        'num_facts_required': num_facts_required,
        'sum_facts_world_rules': sum_facts_world_rules,
        'ReasoningDepth_only_pos_derivations': chain_len,  # Same as chain_len for positive branch
        'ReasoningWidth': 1,  # Only 1 variant for non-ambiguous stories
        'BL_no_contradiction': bl,  # Same as BL for positive branch
        'BL': bl,
        'OPEC': opec,
        'OPEC_pos_refn': opec  # Same as OPEC for positive branch
    }


##==============XXXX debug
import ast
pd.set_option('display.max_rows', None)
pd.set_option('display.max_columns', None)
pd.set_option('display.width', None)
pd.set_option('display.max_colwidth', None)


def _debug_print_deriv_df(deriv_df) -> None:
    """XXXX debug - print deriv_df shape, columns, and top-3 rows by
    longest derivation_chain among rows where chain_len <= 7."""
    # print("XXXX debug | deriv_df shape:", deriv_df.shape)
    # print("XXXX debug | deriv_df columns:", deriv_df.columns.tolist())
    # filtered = deriv_df[deriv_df['chain_len'] <= 7].copy()
    # filtered['_chain_str_len'] = filtered['derivation_chain'].str.len()
    # top3 = filtered.nlargest(3, '_chain_str_len').drop(columns=['_chain_str_len'])
    # with pd.option_context('display.max_colwidth', None):
    #     print("XXXX debug | top-3 longest derivation_chain (chain_len<=7):\n", top3.to_string())

def parse_list(val):
    if isinstance(val, list):
        return val
    if isinstance(val, str):
        try:
            result = ast.literal_eval(val)
            return result if isinstance(result, list) else [result]
        except (ValueError, SyntaxError):
            return [val]
    return []

def make_story_description(edges_val, edge_labels_val):
    edges = parse_list(edges_val)
    labels = parse_list(edge_labels_val)
    return [f'{label}{tuple(edge) if isinstance(edge, list) else edge}' for edge, label in zip(edges, labels)]

if __name__ == "__main__":
    ##------------------Seing examples 
    ## Example 1
    df_queries = pd.read_csv("/lus/lfs1aip2/scratch/XXXX/XXXX.XXXX/projects/auto-world-rules/Funsearch/PostDatabaseGeneration/final_train.csv", nrows=100)
    print(df_queries.columns)
    print(df_queries.shape)
    df_queries['story_description'] = df_queries.apply(lambda row: make_story_description(row['edges'], row['edge_labels']), axis=1)
    df_queries['story_description_len'] = df_queries['story_description'].apply(len)
    print(df_queries.iloc[0][['query_edge', 'query_label', 'ReasoningDepth_only_pos_derivations', 'story_description', 'story_description_len']])

    # XXXX debug - run first row through calculate_difficulty_metrics
    _row = df_queries.iloc[0]

    _edges = ast.literal_eval(str(_row['edges']))
    _edge_labels = ast.literal_eval(str(_row['edge_labels']))
    _seen_facts: set = set()
    _UNARY_PREDS = {"is_person", "is_place"}  # only truly 1-ary preds in NoRa1.1
    _story_facts = []
    for (_e1, _e2), _pred in zip(_edges, _edge_labels):
        if _pred in _UNARY_PREDS:
            _fact = f"{_pred}({_e1})."
        else:
            _fact = f"{_pred}({_e1},{_e2})."
        if _fact not in _seen_facts:
            _seen_facts.add(_fact)
            _story_facts.append(_fact)

    _query_edge_raw = ast.literal_eval(str(_row['query_edge']))
    _query_edge = (int(_query_edge_raw[0]), int(_query_edge_raw[1]))

    _query_labels_raw = ast.literal_eval(str(_row['query_label']))
    _query_labels = [str(r) for r in _query_labels_raw] if isinstance(_query_labels_raw, list) else [str(_query_labels_raw)]

    _world_rules_path = os.path.join(project_root, 'Funsearch', 'Collaterals', 'NoRa1.1.txt')
    with open(_world_rules_path, 'r') as _fh:
        _world_rules = _fh.read()

    _story_info = {'world_rules': _world_rules, 'story_facts': _story_facts}

    logging.basicConfig(level=logging.INFO)
    _metrics = calculate_difficulty_metrics(
        story_info=_story_info,
        query_edge=_query_edge,
        query_labels=_query_labels,
    )
    # print("XXXX debug | calculate_difficulty_metrics result:")
    # for _k, _v in _metrics.items():
    #     print(f"  {_k}: {_v}")

    ## Example 2
    # df_queries = pd.read_csv("/lus/lfs1aip2/scratch/XXXX/XXXX.XXXX/projects/auto-world-rules/Funsearch/Logs/RoundRuns/20260330_235552/round_2/base_train.csv")
    # print(df_queries.columns)
    # print(df_queries.shape)
    # print(df_queries.iloc[0][['query_edge', 'query_label']])