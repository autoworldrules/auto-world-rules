from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np


def run_clingo(program: str) -> list[set]:
    """Run clingo and return all stable models as sets of symbols."""
    from clingo import Control

    ctl = Control()
    ctl.configuration.solve.models = 0
    ctl.add("base", [], program)
    ctl.ground([("base", [])])

    models: list[set] = []
    with ctl.solve(yield_=True) as handle:
        for model in handle:
            models.append(set(model.symbols(shown=True)))
    return models


_FACT_RE = re.compile(r"^([a-z][a-zA-Z0-9_]*)\(([^)]*)\)\.\s*$")


def _split_program(program: str) -> tuple[list[str], list[str]]:
    """Return (definite_rules, ground_facts) as strings (one per line)."""
    rules: list[str] = []
    facts: list[str] = []

    for raw in program.splitlines():
        line = raw.strip()
        if not line or line.startswith("%"):
            continue
        if line.startswith("#"):
            continue
        if not line.endswith("."):
            continue

        # Constraints (":- ... .") are intentionally excluded from definite_rules_program.
        if line.startswith(":-"):
            continue

        if ":-" in line:
            rules.append(line)
            continue

        # Ground facts only: pred(int[,int]) .
        if _FACT_RE.match(line):
            facts.append(line)

    return rules, facts


@dataclass(frozen=True)
class _Candidate:
    fact: str
    details: list[tuple[tuple[int, int], str]]
    entailed_facts_str: str


class PrioStoryGeneratorNoRa1_1:
    """
    Priority-driven story generator (NoRa 1.1 style).

    Output shape matches the historical generator under `Funsearch/ProgramsDB/`.
    """

    def __init__(
        self,
        priority_fn: Callable[[str, str, str, str], float],
        *,
        config: Optional[Dict[str, Any]] = None,
        min_entities: int = 5,
        max_entities: int = 12,
        min_story_facts_mult: float = 2.5,
        max_story_facts_mult: float = 3,
        seed: Optional[int] = 123,
        max_consecutive_contradictions: int = 10,
        num_cands: int = 30,
    ):
        self.priority_fn = priority_fn
        self.config = config or {}

        if seed is not None:
            random.seed(seed)
            np.random.seed(seed)

        self.min_entities = min_entities
        self.max_entities = max_entities
        self.min_story_facts_mult = min_story_facts_mult
        self.max_story_facts_mult = max_story_facts_mult
        self.max_consecutive_contradictions = max_consecutive_contradictions
        self.num_cands = num_cands

        self.assign_loc_prob = self.config.get("assign_loc_prob", 0.3)
        self.prob_living_in_same_place = self.config.get(
            "prob_living_in_same_place", 0.2
        )

        property_ranges = self.config.get(
            "property_prob_ranges",
            {
                "prob__range_property_no_bros": [0.04, 0.10],
                "prob__range_property_no_sis": [0.04, 0.10],
                "prob__range_property_no_dghter": [0.04, 0.10],
                "prob__range_property_no_son": [0.04, 0.10],
            },
        )
        self.prob_property_no_bros = random.uniform(
            *property_ranges["prob__range_property_no_bros"]
        )
        self.prob_property_no_sis = random.uniform(
            *property_ranges["prob__range_property_no_sis"]
        )
        self.prob_property_no_dghter = random.uniform(
            *property_ranges["prob__range_property_no_dghter"]
        )
        self.prob_property_no_son = random.uniform(
            *property_ranges["prob__range_property_no_son"]
        )

        self.male_prob = self.config.get("male_prob", 0.5)

        self.plausible_relations: list[tuple[str, int]] = []
        self.exclude_preds_during_gen = [
            "is_person",
            "is_place",
            "living_in",
            "is_male",
            "is_female",
            "is_underage",
            "no_siblings",
            "no_children",
            "no_brothers",
            "no_sisters",
            "no_daughters",
            "no_sons",
        ]

        self.people: list[int] = []
        self.places: list[int] = []

    def generate_story_from_rules(self, world_rules_path: str) -> Dict[str, Any]:
        world_rules = self._load_world_rules(world_rules_path)
        self.plausible_relations = self.extract_plausible_relations(world_rules)

        num_entities, num_people, num_places = self._sample_entity_counts()
        entities, entity_program, base_facts, fact_details_list = (
            self._gen_entities_with_types(num_entities, num_people, num_places)
        )

        program = world_rules + "\n\n" + entity_program

        min_facts = math.floor(self.min_story_facts_mult * num_entities)
        max_facts = math.floor(self.max_story_facts_mult * num_entities)
        max_story_facts = random.randint(min_facts, max_facts)

        chosen_story_facts: list[str] = []
        added_fact_set = set(base_facts)
        fact_count = 0
        consecutive_contradictions = 0

        while fact_count < max_story_facts:
            fact, fact_details = self.generate_prio_fact(
                entities=entities, program=program, already_added=added_fact_set
            )
            if fact is None:
                break

            accepted, new_program, consecutive_contradictions, break_flag = (
                self._verify_fact(
                    fact=fact,
                    program=program,
                    consecutive_contradictions=consecutive_contradictions,
                    too_many_consecutive_contradictions=self.max_consecutive_contradictions,
                )
            )
            if break_flag:
                break
            if not accepted:
                continue

            program = new_program
            chosen_story_facts.append(fact)
            added_fact_set.add(fact)
            fact_details_list.extend(fact_details)
            fact_count += 1

        explicit_story_facts = set(base_facts) | set(chosen_story_facts)
        entailed_facts = self._compute_entailed_facts_from_program(
            program=program, explicit_story_facts=explicit_story_facts
        )

        all_story_facts = base_facts + chosen_story_facts

        return {
            "world_rules": world_rules,
            "program": program,
            "entities": entities,
            "people": self.people,
            "places": self.places,
            "story_facts": all_story_facts,
            "entailed_facts": entailed_facts,
            "fact_details": fact_details_list,
        }

    @staticmethod
    def _load_world_rules(path: str) -> str:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def extract_plausible_relations(self, universal_rules: str) -> list[tuple[str, int]]:
        pattern = r"(?<!\w)([a-z][a-zA-Z0-9_]*)\s*\(([^)]*)\)"
        standalone_pattern = r"(?<!\w)([a-z][a-zA-Z0-9_]*)(?=\s*\.)"

        relations: set[tuple[str, int]] = set()

        for match in re.finditer(pattern, universal_rules):
            pred_name = match.group(1)
            args = match.group(2)
            arity = len([arg for arg in re.split(r"\s*,\s*", args) if arg.strip()])
            relations.add((pred_name, arity))

        for match in re.finditer(standalone_pattern, universal_rules):
            pred_name = match.group(1)
            relations.add((pred_name, 0))

        exclude = {"show", "not", "sum", "count", "min", "max", "in", "rel_star"}
        plausible = {rel for rel in relations if rel[0] not in exclude}
        return sorted(plausible, key=lambda x: x[0])

    def _sample_entity_counts(self) -> tuple[int, int, int]:
        num_entities = random.randint(self.min_entities, self.max_entities)
        frac_person = random.uniform(0.8, 0.9)
        num_people = max(1, int(round(frac_person * num_entities)))
        num_people = min(num_people, num_entities - 1)
        num_places = num_entities - num_people
        return num_entities, num_people, num_places

    def _gen_entities_with_types(
        self, num_entities: int, num_people: int, num_places: int
    ) -> tuple[list[int], str, list[str], list[tuple[tuple[int, int], str]]]:
        entities = list(range(num_entities))
        self.people = entities[:num_people]
        self.places = entities[num_people : num_people + num_places]

        program_lines: list[str] = []
        added_facts: list[str] = []
        fact_details_list: list[tuple[tuple[int, int], str]] = []

        for p_num in self.people:
            p_fact = f"is_person({p_num})."
            program_lines.append(p_fact)
            added_facts.append(p_fact)
            fact_details_list.append(((p_num, p_num), "is_person"))

        for q in self.places:
            q_fact = f"is_place({q})."
            program_lines.append(q_fact)
            added_facts.append(q_fact)
            fact_details_list.append(((q, q), "is_place"))

        program = "\n".join(program_lines) + "\n"
        return entities, program, added_facts, fact_details_list

    def generate_prio_fact(
        self, *, entities: list[int], program: str, already_added: set
    ) -> tuple[Optional[str], list[tuple[tuple[int, int], str]]]:
        valid_candidates: list[_Candidate] = []
        attempts = 0
        max_attempts = max(10000, 50 * self.num_cands)

        rules_lines, facts_lines = _split_program(program)
        definite_rules_program = "\n".join(rules_lines)
        facts_program = "\n".join(facts_lines)
        explicit_story_facts = set(facts_lines)

        while len(valid_candidates) < self.num_cands and attempts < max_attempts:
            attempts += 1
            cand_fact, cand_details = self._propose_one_candidate_fact(entities)
            if cand_fact in already_added:
                continue

            temp_program = program + cand_fact + "\n"
            models = run_clingo(temp_program)
            if not models:
                continue

            entailed_facts_list = self._compute_entailed_facts_from_program(
                program=temp_program,
                explicit_story_facts=explicit_story_facts | {cand_fact},
            )
            valid_candidates.append(
                _Candidate(
                    fact=cand_fact,
                    details=cand_details,
                    entailed_facts_str="\n".join(entailed_facts_list),
                )
            )

        if not valid_candidates:
            return None, []

        best = max(
            valid_candidates,
            key=lambda c: self.priority_fn(
                c.fact, definite_rules_program, c.entailed_facts_str, facts_program
            ),
        )
        return best.fact, best.details

    def _propose_one_candidate_fact(
        self, entities: Sequence[int]
    ) -> tuple[str, list[tuple[tuple[int, int], str]]]:
        if (random.random() < self.assign_loc_prob) and self.people and self.places:
            p_pers = random.choice(self.people)
            p_place = random.choice(self.places)
            fact = f"living_in({p_pers},{p_place})."
            return fact, [((p_pers, p_place), "living_in")]

        if (random.random() < self.prob_living_in_same_place) and (len(self.people) >= 2):
            e1, e2 = random.sample(self.people, 2)
            fact = f"living_in_same_place({e1},{e2})."
            return fact, [((e1, e2), "living_in_same_place")]

        bucket = random.choice(["plausible_rel", "no_prop", "gender", "underage"])

        if bucket == "no_prop":
            p = random.choice(self.people) if self.people else random.choice(list(entities))
            no_pred = self._sample_no_property_predicate()
            fact = f"{no_pred}({p},{p})."
            return fact, [((p, p), no_pred)]

        if bucket == "gender":
            p = random.choice(self.people) if self.people else random.choice(list(entities))
            pred = "is_male" if random.random() < self.male_prob else "is_female"
            fact = f"{pred}({p},{p})."
            return fact, [((p, p), pred)]

        if bucket == "underage":
            p = random.choice(self.people) if self.people else random.choice(list(entities))
            pred = "is_underage"
            fact = f"{pred}({p},{p})."
            return fact, [((p, p), pred)]

        updated_rels = [
            rel for rel in self.plausible_relations if rel[0] not in self.exclude_preds_during_gen
        ]
        if not updated_rels:
            e1, e2 = random.sample(list(entities), 2) if len(entities) >= 2 else (0, 0)
            fact = f"rel({e1},{e2})."
            return fact, [((e1, e2), "rel")]

        relation, num_args = random.choice(updated_rels)
        num_args = int(num_args)

        if num_args == 2:
            e1, e2 = random.sample(list(entities), 2)
            fact = f"{relation}({e1},{e2})."
            return fact, [((e1, e2), relation)]
        if num_args == 1:
            e1 = random.choice(list(entities))
            fact = f"{relation}({e1})."
            return fact, [((e1, e1), relation)]
        if num_args == 0:
            fact = f"{relation}."
            return fact, [((0, 0), relation)]

        fact = f"{relation}."
        return fact, [((0, 0), relation)]

    def _sample_no_property_predicate(self) -> str:
        probs = [
            ("no_brothers", self.prob_property_no_bros),
            ("no_sisters", self.prob_property_no_sis),
            ("no_daughters", self.prob_property_no_dghter),
            ("no_sons", self.prob_property_no_son),
        ]
        total = sum(p for _, p in probs)
        if total <= 0:
            return "no_brothers"

        u = random.random() * total
        cum = 0.0
        for name, p in probs:
            cum += p
            if u <= cum:
                return name
        return probs[-1][0]

    def _verify_fact(
        self,
        *,
        fact: str,
        program: str,
        consecutive_contradictions: int,
        too_many_consecutive_contradictions: int,
    ) -> tuple[bool, str, int, bool]:
        temp_program = program + fact + "\n"
        temp_models = run_clingo(temp_program)

        if not temp_models:
            consecutive_contradictions += 1
            if consecutive_contradictions >= too_many_consecutive_contradictions:
                return False, program, consecutive_contradictions, True
            return False, program, consecutive_contradictions, False

        return True, temp_program, 0, False

    def _compute_entailed_facts_from_program(
        self, *, program: str, explicit_story_facts: set[str]
    ) -> list[str]:
        models = run_clingo(program)
        if not models:
            return []

        # Intersection across models, mirroring the historical implementation.
        model_fact_sets = [{str(atom) + "." for atom in model} for model in models]
        intersection_facts = set.intersection(*model_fact_sets) if model_fact_sets else set()
        non_trivial_entailed = intersection_facts - explicit_story_facts
        return list(non_trivial_entailed)

