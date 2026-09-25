from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd


class StoryQueryGeneratorNoRa1_1:
    """Convert a single story dict into a query DataFrame.

    This is the minimal, ET-training-relevant subset of the historical
    `Funsearch/Collaterals/story_query_generator_nora1_1.py`.
    """

    def build_query_dataframe(
        self,
        story_info: Dict[str, Any],
        *,
        calculate_difficulty: bool = False,
        logger=None,
    ) -> pd.DataFrame:
        if calculate_difficulty:
            raise NotImplementedError(
                "Difficulty metrics are intentionally not included in auto-research."
            )

        story_facts: List[str] = story_info.get("story_facts", [])
        entailed_facts: List[str] = story_info.get("entailed_facts", [])

        edges, edge_labels, story_pair_to_rels = self._build_story_graph(story_facts)
        ent_pair_to_rels = self._build_pair_to_relations_map(entailed_facts)

        excluded_preds = {"is_place", "is_person"}
        rows = []
        for pair, ent_rels in ent_pair_to_rels.items():
            story_rels = story_pair_to_rels.get(pair, [])

            story_rels_filtered = [r for r in story_rels if r not in excluded_preds]
            ent_rels_filtered = [r for r in ent_rels if r not in excluded_preds]

            def normalize_rel(rel: str) -> str:
                if rel == "not_living_in":
                    return "Not_living_in"
                return rel

            story_rels_filtered = [normalize_rel(r) for r in story_rels_filtered]
            ent_rels_filtered = [normalize_rel(r) for r in ent_rels_filtered]

            ent_only = [r for r in ent_rels_filtered if r not in story_rels_filtered]
            if not ent_only:
                continue

            all_rels = list(dict.fromkeys(story_rels_filtered + ent_rels_filtered))
            rows.append(
                {
                    "edges": edges.copy(),
                    "edge_labels": edge_labels.copy(),
                    "query_edge": pair,
                    "query_label": all_rels,
                }
            )

        return pd.DataFrame(rows, columns=["edges", "edge_labels", "query_edge", "query_label"])

    def _build_story_graph(
        self, story_facts: List[str]
    ) -> Tuple[List[Tuple[int, int]], List[str], Dict[Tuple[int, int], List[str]]]:
        edges: List[Tuple[int, int]] = []
        edge_labels: List[str] = []
        pair_to_rels: Dict[Tuple[int, int], List[str]] = {}

        for fact in story_facts:
            pred, args = self._parse_fact(fact)
            if pred is None:
                continue

            if len(args) == 1:
                e = args[0]
                pair = (e, e)
            elif len(args) == 2:
                pair = (args[0], args[1])
            else:
                continue

            edges.append(pair)
            edge_labels.append(pred)
            pair_to_rels.setdefault(pair, []).append(pred)

        return edges, edge_labels, pair_to_rels

    def _build_pair_to_relations_map(
        self, facts: List[str]
    ) -> Dict[Tuple[int, int], List[str]]:
        pair_to_rels: Dict[Tuple[int, int], List[str]] = {}
        for fact in facts:
            pred, args = self._parse_fact(fact)
            if pred is None:
                continue

            if len(args) == 1:
                e = args[0]
                pair = (e, e)
            elif len(args) == 2:
                pair = (args[0], args[1])
            else:
                continue

            pair_to_rels.setdefault(pair, []).append(pred)

        return pair_to_rels

    @staticmethod
    def _parse_fact(fact: str) -> Tuple[Optional[str], List[int]]:
        fact = fact.strip()
        if fact.endswith("."):
            fact = fact[:-1].strip()

        if "(" not in fact:
            # 0-ary predicate
            return fact, []

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
            return None, []

        return pred, args

