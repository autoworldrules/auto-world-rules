import re, os, sys
from typing import Dict, Any, List, Tuple, Optional
import logging
this_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(this_dir, '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
from Funsearch.Collaterals.PrioStoryGeneratorNoRa1_1 import PrioStoryGeneratorNoRa1_1
from Funsearch.utils.calculate_difficulty import calculate_difficulty_metrics
import pandas as pd
import os
import pickle 

class StoryQueryGeneratorNoRa1_1:
    """
    Converts a single story produced by PrioStoryGeneratorNoRa1_1 into a
    query DataFrame.

    Input
    -----
    story_info : dict
        Expected to be the output of PrioStoryGeneratorNoRa1_1.generate_story_from_rules.
        It must at least contain:
          - 'story_facts'   : List[str]
                All explicit story facts (base entity/property facts + random facts),
                each as a string with trailing '.' (e.g., "parent_of(1,0).").
          - 'entailed_facts': List[str]
                Facts entailed by the world rules, also as strings with trailing '.'.
          - 'entities'      : List[int]
                All entity IDs (not used directly here, but useful for sanity).

    Output
    ------
    A pandas DataFrame where each row is a query, with columns:
      - 'edges'       : List[(int, int)]
            List of all edges in the story graph, built from explicit story_facts.
            Unary facts r(E) are represented as (E, E).
      - 'edge_labels' : List[str]
            Predicate names aligned with 'edges'. Same for every row (single story).
      - 'query_edge'  : (int, int)
            A specific ordered entity pair (source, target).
      - 'query_label' : List[str]
            All relations that hold between query_edge[0] and query_edge[1],
            including both explicit story facts and entailed facts.
            A row is included only if there is at least one relation between
            this pair that appears *only* in entailed_facts and not explicitly
            in story_facts.
    """

    def __init__(self):
        pass

    # ------------------------------------------------------------------
    # PUBLIC ENTRY POINT
    # ------------------------------------------------------------------
    def build_query_dataframe(
        self, 
        story_info: Dict[str, Any],
        calculate_difficulty: bool = False,
        logger: Optional[logging.Logger] = None
    ) -> pd.DataFrame:
        """
        Build a query dataframe from a single story.

        Parameters
        ----------
        story_info : dict
            Output of PrioStoryGeneratorNoRa1_1.generate_story_from_rules.
            Must contain keys 'story_facts' and 'entailed_facts'.
        calculate_difficulty : bool, default=False
            If True, calculate difficulty metrics for each query.
        logger : logging.Logger, optional
            Logger for difficulty calculation.

        Returns
        -------
        df_queries : pandas.DataFrame
            Each row corresponds to one query edge (src, dst) for which at least
            one relation is *only* entailed, not explicit. Columns:
              - 'edges'
              - 'edge_labels'
              - 'query_edge'
              - 'query_label'
            If calculate_difficulty=True, additional columns:
              - 'derivation_chain'
              - 'chain_len'
              - 'num_facts_required'
              - 'sum_facts_world_rules'
              - 'ReasoningDepth_only_pos_derivations'
              - 'ReasoningWidth' (always 1 for non-ambiguous stories)
              - 'BL_no_contradiction'
              - 'BL'
              - 'OPEC'
              - 'OPEC_pos_refn'
        
        Note
        ----
        Since PrioStoryGeneratorNoRa1_1 does not support ambiguous facts,
        ReasoningWidth is always 1 (only one variant/branch exists).
        ReasoningDepth represents the longest derivation chain across all
        query labels for this entity pair.
        """
        story_facts: List[str] = story_info.get("story_facts", [])
        entailed_facts: List[str] = story_info.get("entailed_facts", [])

        # 1) Build story graph (edges + labels) and map from (src,dst)->[relations]
        edges, edge_labels, story_pair_to_rels = \
            self._build_story_graph(story_facts)
        edge_labels = self._normalize_edge_labels(edge_labels)

        # 2) Build mapping from (src,dst) -> [relations] for entailed facts
        ent_pair_to_rels = self._build_pair_to_relations_map(entailed_facts)

        # 3) For each pair that has entailed relations, create a query row if
        #    at least one entailed relation is not in the explicit story facts.
        excluded_preds = {"is_place", "is_person"}
        rows = []
        for pair, ent_rels in ent_pair_to_rels.items():
            story_rels = story_pair_to_rels.get(pair, [])

            # Filter out excluded predicates from both story and entailed lists
            story_rels_filtered = [r for r in story_rels if r not in excluded_preds]
            ent_rels_filtered = [r for r in ent_rels if r not in excluded_preds]
            # ---- Relationship name normalization ----
            def normalize_rel(rel: str) -> str:
                if rel == "not_living_in":
                    return "Not_living_in"
                return rel

            story_rels_filtered = [normalize_rel(r) for r in story_rels_filtered]
            ent_rels_filtered   = [normalize_rel(r) for r in ent_rels_filtered]
            # Relations that are only entailed (non-excluded), not explicitly in the story
            ent_only = [r for r in ent_rels_filtered if r not in story_rels_filtered]
            if not ent_only:
                # Requirement: query must have at least one new entailed relation
                # that is not 'is_person' or 'is_place'
                continue

            # All relations that hold between the two entities (explicit + entailed),
            # excluding 'is_person' and 'is_place'
            all_rels = list(dict.fromkeys(story_rels_filtered + ent_rels_filtered))

            row = {
                "edges": edges.copy(),
                "edge_labels": edge_labels.copy(),
                "query_edge": pair,
                "query_label": all_rels,  # guaranteed to contain no is_place/is_person
            }
            rows.append(row)

        df = pd.DataFrame(rows, columns=["edges", "edge_labels", "query_edge", "query_label"])
        
        # Calculate difficulty metrics if requested
        if calculate_difficulty and not df.empty:
            if logger is None:
                logger = logging.getLogger(__name__)
            
            logger.info(f"Calculating difficulty metrics for {len(df)} queries...")
            
            # Initialize difficulty columns
            df['derivation_chain'] = None
            df['chain_len'] = None
            df['num_facts_required'] = None
            df['sum_facts_world_rules'] = None
            df['ReasoningDepth_only_pos_derivations'] = None
            df['ReasoningWidth'] = None
            df['BL_no_contradiction'] = None
            df['BL'] = None
            df['OPEC'] = None
            df['OPEC_pos_refn'] = None
            
            # Calculate difficulty for each query
            for idx, row in df.iterrows():
                try:
                    difficulty_metrics = calculate_difficulty_metrics(
                        story_info=story_info,
                        query_edge=row['query_edge'],
                        query_labels=row['query_label'],
                        logger=logger
                    )
                    
                    # Update row with metrics
                    for metric_key, metric_value in difficulty_metrics.items():
                        df.at[idx, metric_key] = metric_value
                        
                except Exception as e:
                    logger.error(f"Error calculating difficulty for query {row['query_edge']}: {e}")
                    # Leave as None for failed calculations
            
            logger.info("Difficulty calculation complete.")
        
        return df

    # ------------------------------------------------------------------
    # LABEL NORMALIZATION
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_edge_labels(edge_labels: List[str]) -> List[str]:
        """Normalise edge label names from Clingo form to ET form.

        Clingo emits 'not_living_in'; the EdgeTransformer expects 'Not_living_in'.
        Extend this method if other casing mismatches are discovered.
        """
        return ["Not_living_in" if lbl == "not_living_in" else lbl for lbl in edge_labels]

    # ------------------------------------------------------------------
    # STORY GRAPH BUILDING
    # ------------------------------------------------------------------
    def _build_story_graph(
        self,
        story_facts: List[str],
    ) -> Tuple[List[Tuple[int, int]], List[str], Dict[Tuple[int, int], List[str]]]:
        """
        Build the story graph from explicit story facts.

        For each fact of the form:
          - rel(E)          -> edge (E, E)
          - rel(E1, E2)     -> edge (E1, E2)
          - rel(...) with more args is ignored.

        Parameters
        ----------
        story_facts : List[str]
            Explicit story facts as strings with trailing '.'.

        Returns
        -------
        edges : List[(int, int)]
            All edges in the story graph.
        edge_labels : List[str]
            Predicate names aligned with 'edges'.
        pair_to_rels : Dict[(int,int), List[str]]
            Mapping from ordered entity pair to list of predicate names that
            hold explicitly in the story.
        """
        edges: List[Tuple[int, int]] = []
        edge_labels: List[str] = []
        pair_to_rels: Dict[Tuple[int, int], List[str]] = {}

        for fact in story_facts:
            pred, args = self._parse_fact(fact)
            if pred is None or not args:
                continue

            if len(args) == 1:
                e = args[0]
                pair = (e, e)
            elif len(args) == 2:
                pair = (args[0], args[1])
            else:
                # For 0-ary or >2-ary predicates we do not add graph edges.
                continue

            edges.append(pair)
            edge_labels.append(pred)

            rel_list = pair_to_rels.setdefault(pair, [])
            rel_list.append(pred)

        return edges, edge_labels, pair_to_rels

    # ------------------------------------------------------------------
    # ENTAILED FACT MAP
    # ------------------------------------------------------------------
    def _build_pair_to_relations_map(
        self,
        facts: List[str],
    ) -> Dict[Tuple[int, int], List[str]]:
        """
        Build a mapping (src, dst) -> [relations] for a list of facts.

        Unary facts rel(E) are mapped to (E, E).
        Binary facts rel(E1, E2) are mapped to (E1, E2).
        All other arities are ignored.

        Parameters
        ----------
        facts : List[str]
            Facts as strings with trailing '.'.

        Returns
        -------
        pair_to_rels : Dict[(int,int), List[str]]
            Mapping from ordered entity pair to predicate names.
        """
        pair_to_rels: Dict[Tuple[int, int], List[str]] = {}

        for fact in facts:
            pred, args = self._parse_fact(fact)
            if pred is None or not args:
                continue

            if len(args) == 1:
                e = args[0]
                pair = (e, e)
            elif len(args) == 2:
                pair = (args[0], args[1])
            else:
                continue

            rel_list = pair_to_rels.setdefault(pair, [])
            rel_list.append(pred)

        return pair_to_rels

    # ------------------------------------------------------------------
    # FACT PARSING
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_fact(fact: str) -> Tuple[Optional[str], List[int]]:
        """
        Parse a fact string of the form:
            "rel(1,2)."
            "rel(3)."
            "rel."
        into (predicate_name, [int_args]).

        Parameters
        ----------
        fact : str
            Fact string with trailing '.'.

        Returns
        -------
        pred : str or None
            Predicate name, or None if parsing fails.
        args : List[int]
            Parsed integer arguments. Can be empty for 0-ary predicates.
        """
        fact = fact.strip()
        if fact.endswith("."):
            fact = fact[:-1].strip()

        if "(" not in fact:
            # 0-ary predicate like "some_fact"
            pred = fact
            return pred, []

        # rel(arglist)
        m = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*)\((.*)\)$", fact)
        if not m:
            return None, []

        pred = m.group(1)
        arg_str = m.group(2).strip()
        if not arg_str:
            return pred, []

        arg_tokens = [a.strip() for a in arg_str.split(",") if a.strip()]
        try:
            args = [int(a) for a in arg_tokens]
        except ValueError:
            # In this pipeline we expect integer entity IDs
            return None, []

        return pred, args


if __name__ == "__main__":
    # ================Example test: Generate one story and calculate difficulty ================
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s - %(name)s - %(message)s'
    )
    logger = logging.getLogger(__name__)
    
    # Simple priority function (returns 0.0 for all candidates)
    def priority(cand_fact: str, definite_rules_program: str, entailed_facts: str, facts_program: str) -> float:
        """Simple priority function that treats all candidates equally."""
        return 0.0
    
    # Setup paths
    this_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(this_dir, '..', '..'))
    rules_path = os.path.join(this_dir, "NoRa1.1.txt")
    scrap_dir = os.path.join(project_root, "scrap")
    
    # Create scrap directory if it doesn't exist
    os.makedirs(scrap_dir, exist_ok=True)
    
    # Initialize generators
    generator_queries = StoryQueryGeneratorNoRa1_1()
    generator_story = PrioStoryGeneratorNoRa1_1(
        priority_fn=priority,
        seed=42,
        min_entities=7,
        max_entities=8,
        min_story_facts_mult=3,
        max_story_facts_mult=4.5
    )
    
    print("="*70)
    print("Generating story and calculating query difficulties...")
    print("="*70)
    
    # Generate a story
    story_info = generator_story.generate_story_from_rules(rules_path)
    
    print("\n=== BASIC STORY INFO ===")
    print(f"Entities: {story_info['entities']}")
    print(f"People: {story_info['people']}")
    print(f"Places: {story_info['places']}")
    print(f"Story facts: {len(story_info['story_facts'])}")
    print(f"Entailed facts: {len(story_info['entailed_facts'])}")
    
    # Build queries WITH difficulty calculation
    print("\n=== BUILDING QUERIES WITH DIFFICULTY METRICS ===")
    df_queries = generator_queries.build_query_dataframe(
        story_info, 
        calculate_difficulty=True,
        logger=logger
    )
    
    print(f"\nGenerated {len(df_queries)} queries.")
    
    # Display sample results
    if not df_queries.empty:
        print("\n=== SAMPLE QUERY (first row) ===")
        pd.set_option('display.max_columns', None)
        pd.set_option('display.width', None)
        pd.set_option('display.max_colwidth', 100)
        
        # Display key columns
        sample = df_queries.iloc[0]
        print(f"Query Edge: {sample['query_edge']}")
        print(f"Query Labels: {sample['query_label']}")
        print(f"Chain Length (unique rules): {sample['chain_len']}")
        print(f"Facts Required: {sample['num_facts_required']}")
        print(f"Reasoning Depth (longest chain): {sample['ReasoningDepth_only_pos_derivations']}")
        print(f"Reasoning Width (variants): {sample['ReasoningWidth']}")
        print(f"BL (max rule-to-node ratio): {sample['BL']}")
        print(f"BL_no_contradiction: {sample['BL_no_contradiction']}")
        print(f"OPEC (non-path atoms): {sample['OPEC']}")
        print(f"OPEC_pos_refn: {sample['OPEC_pos_refn']}")
        print(f"Derivation Chain (truncated): {str(sample['derivation_chain'])[:200]}...")
    
    # Save to scrap directory
    output_path = os.path.join(scrap_dir, "test_queries_with_difficulty.csv")
    df_queries.to_csv(output_path, index=False)
    print(f"\n✓ Saved queries DataFrame to: {output_path}")
    
    # Also save as pickle for full preservation
    pickle_path = os.path.join(scrap_dir, "test_queries_with_difficulty.pkl")
    df_queries.to_pickle(pickle_path)
    print(f"✓ Saved queries DataFrame (pickle) to: {pickle_path}")
    
    print("\n" + "="*70)
    print("Test complete!")
    print("="*70)

