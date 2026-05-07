import math
import sys,os
import os.path

# Ensure project root is on sys.path so we can import modules from sibling top-level
# packages such as `WhenNoPathsLeadToRome` regardless of current working dir.
this_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(this_dir, '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
sys.path.append('..')
import random
import re
import functools
from typing import List, Tuple, Dict, Any, Optional, Callable
import numpy as np
from WhenNoPathsLeadToRome.utils.clingo_utils import run_clingo
from WhenNoPathsLeadToRome.utils.FindDerivationForPositiveProgram import PositiveProgramTP

"""
Priority-driven story generator (NoRa 1.1 style).

Goal:
- Produce story outputs with the SAME SHAPE as ../Mocks/MockStoryGeneratorNoRa1_1:
    {
      "world_rules": str,
      "program": str,
      "entities": List[int],
      "people": List[int],
      "places": List[int],
      "story_facts": List[str],
      "entailed_facts": List[str],
      "fact_details": List[((int,int), str)],
    }

Key differences vs MockStoryGeneratorNoRa1_1:
1) Takes a `priority` function (supplied during evaluation / construction).
2) During entity generation: ONLY create entities and is_person / is_place facts.
   (Gender, underage, no_* properties become candidate facts later.)
3) Fact generation: propose many candidate facts, filter those that are clingo-valid,
   then choose the one with highest priority(cand_fact, definite_rules, constraints, facts).
"""
class PrioStoryGeneratorNoRa1_1:
    def __init__(
        self,
        priority_fn: Callable[[str, str, str, str], float],
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

        # ---- Random seeding ---------------------------------------------------
        if seed is not None:
            random.seed(seed)
            np.random.seed(seed)

        # ---- Entity / fact ranges --------------------------------------------
        self.min_entities = min_entities
        self.max_entities = max_entities
        self.min_story_facts_mult = min_story_facts_mult
        self.max_story_facts_mult = max_story_facts_mult
        self.max_consecutive_contradictions = max_consecutive_contradictions
        self.num_cands = num_cands

        # ---- Probabilities for special predicates -----------------------------
        self.assign_loc_prob = self.config.get("assign_loc_prob", 0.3)
        self.prob_living_in_same_place = self.config.get("prob_living_in_same_place", 0.2)

        # no_* properties ranges
        property_ranges = self.config.get(
            "property_prob_ranges",
            {
                "prob__range_property_no_bros": [0.04, 0.10],
                "prob__range_property_no_sis": [0.04, 0.10],
                "prob__range_property_no_dghter": [0.04, 0.10],
                "prob__range_property_no_son": [0.04, 0.10],
            },
        )
        self.prob_property_no_bros = random.uniform(*property_ranges["prob__range_property_no_bros"])
        self.prob_property_no_sis = random.uniform(*property_ranges["prob__range_property_no_sis"])
        self.prob_property_no_dghter = random.uniform(*property_ranges["prob__range_property_no_dghter"])
        self.prob_property_no_son = random.uniform(*property_ranges["prob__range_property_no_son"])

        # Gender + underage probabilities (generated as candidates later)
        self.no_gender_assign = self.config.get("no_gender_assign", 0.2)
        self.male_prob = self.config.get("male_prob", 0.5)
        self.proportion_of_underage = self.config.get("proportion_of_underage", 0.07)

        # Will be populated after reading world rules
        self.plausible_relations: List[Tuple[str, int]] = []
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

        # These will be populated in entity generation
        self.people: List[int] = []
        self.places: List[int] = []

        self.PRINT_STUFF = 3

    # ----------------------------------------------------------------------
    # PUBLIC ENTRY POINT
    # ----------------------------------------------------------------------

    def generate_story_from_rules(self, world_rules_path: str) -> Dict[str, Any]:
        # 1. Load ASP rules
        world_rules = self._load_world_rules(world_rules_path)

        # 2. Extract plausible predicates
        self.plausible_relations = self.extract_plausible_relations(world_rules)

        # 3. Sample entities and ONLY assign person/place (no gender/underage/no_* here)
        num_entities, num_people, num_places = self._sample_entity_counts()
        entities, entity_program, base_facts, fact_details_list = self._gen_entities_with_types(
            num_entities, num_people, num_places
        )

        # Start program with world rules + base entity typing
        program = world_rules + "\n\n" + entity_program

        # 4. Decide how many story facts
        min_facts = math.floor(self.min_story_facts_mult * num_entities)
        max_facts = math.floor(self.max_story_facts_mult * num_entities)
        max_story_facts = random.randint(min_facts, max_facts)

        # 5. Incrementally add contradiction-free story facts chosen by priority
        chosen_story_facts: List[str] = []
        added_fact_set = set(base_facts)  # track all explicit facts to avoid repeats
        fact_count = 0
        consecutive_contradictions = 0
        while fact_count < max_story_facts:
            # propose ONE best fact chosen from up to num_cands valid candidates
            if fact_count == max_story_facts-1:
                debug_flag = True
            else:
                debug_flag = False
            fact, fact_details = self.generate_prio_fact(
                entities=entities,
                program=program,
                already_added=added_fact_set,
                debug_flag=debug_flag
            )

            if fact is None:
                break  # couldn't find any valid candidates

            accepted, new_program, temp_models, consecutive_contradictions, break_flag = self._verify_fact(
                fact=fact,
                program=program,
                consecutive_contradictions=consecutive_contradictions,
                too_many_consecutive_contradictions=self.max_consecutive_contradictions,
            )

            if break_flag:
                break

            if not accepted:
                # generate_prio_fact tried to filter to valid facts, but keep this robust
                continue

            program = new_program
            chosen_story_facts.append(fact)
            added_fact_set.add(fact)
            fact_details_list.extend(fact_details)
            fact_count += 1

        # Explicit story facts = base typing facts + chosen story facts
        explicit_story_facts = set(base_facts) | set(chosen_story_facts)

        # 6. Compute entailed facts
        entailed_facts = self._compute_entailed_facts_from_program(
            program=program,
            explicit_story_facts=explicit_story_facts,
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

    # ----------------------------------------------------------------------
    # I/O + RULE PARSING
    # ----------------------------------------------------------------------

    @staticmethod
    def _load_world_rules(path: str) -> str:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def extract_plausible_relations(self, universal_rules: str) -> List[Tuple[str, int]]:
        pattern = r"(?<!\w)([a-z][a-zA-Z0-9_]*)\s*\(([^)]*)\)"
        standalone_pattern = r"(?<!\w)([a-z][a-zA-Z0-9_]*)(?=\s*\.)"

        relations = set()

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

    # ----------------------------------------------------------------------
    # ENTITY SAMPLING (TYPES ONLY)
    # ----------------------------------------------------------------------

    def _sample_entity_counts(self) -> Tuple[int, int, int]:
        num_entities = random.randint(self.min_entities, self.max_entities)
        frac_person = random.uniform(0.8, 0.9)
        num_people = max(1, int(round(frac_person * num_entities)))
        num_people = min(num_people, num_entities - 1)  # ensure at least 1 place
        num_places = num_entities - num_people
        return num_entities, num_people, num_places

    def _gen_entities_with_types(
        self,
        num_entities: int,
        num_people: int,
        num_places: int,
    ) -> Tuple[List[int], str, List[str], List[Tuple[Tuple[int, int], str]]]:
        entities = list(range(num_entities))
        self.people = entities[:num_people]
        self.places = entities[num_people : num_people + num_places]

        program_lines: List[str] = []
        added_facts: List[str] = []
        fact_details_list: List[Tuple[Tuple[int, int], str]] = []

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

    # ----------------------------------------------------------------------
    # CANDIDATE GENERATION (PRIORITY-BASED)
    # ----------------------------------------------------------------------

    def generate_prio_fact(
        self,
        entities: List[int],
        program: str,
        already_added: set,
        debug_flag: bool = False,
    ) -> Tuple[Optional[str], List[Tuple[Tuple[int, int], str]]]:
        """
        Generate up to `self.num_cands` *valid* candidate facts (clingo-consistent),
        then choose the one with max priority(cand_fact, definite_rules, constraints, facts).

        Returns:
            (best_fact_or_None, fact_details_for_best_fact)
        """
        valid_candidates: List[Tuple[str, List[Tuple[Tuple[int, int], str]], str]] = []
        attempts = 0
        max_attempts = max(10000, 50 * self.num_cands)
        
        # Parse the program to extract facts for computing entailed_facts
        parser = PositiveProgramTP(program)
        parser.parse_program()
        explicit_story_facts = {f"{pred}({','.join(map(str, args))})." for pred, args in parser.facts}

        while len(valid_candidates) < self.num_cands and attempts < max_attempts:
            attempts += 1
            cand_fact, cand_details = self._propose_one_candidate_fact(entities)

            if cand_fact in already_added:
                continue

            # quick validity check: must yield at least one model when appended
            temp_program = program + cand_fact + "\n"
            models = run_clingo(temp_program)
            if not models:
                continue
            
            # Compute entailed facts: facts in stable model not in story facts or candidate fact
            # Since we use definite rules, models should have length 1
            entailed_facts_list = self._compute_entailed_facts_from_program(
                temp_program, 
                explicit_story_facts | {cand_fact}
            )
            entailed_facts_str = "\n".join(entailed_facts_list)

            valid_candidates.append((cand_fact, cand_details, entailed_facts_str))

        if not valid_candidates:
            return None, []
        if self.PRINT_STUFF == 2:
            print(f'Priority function will work with candiates : {valid_candidates} and the program is :\n {program}')
        self.PRINT_STUFF += 1
        
        # Parse the program into three parts using PositiveProgramTP
        # (Re-parse for definite_rules_program and facts_program - already parsed earlier)
        definite_rules_program = "\n".join([self._rule_to_string(rule) for rule in parser.rules])
        facts_program = "\n".join([f"{pred}({','.join(map(str, args))})." for pred, args in parser.facts])
        
        # if debug_flag:
        #     print("\n" + "="*80)
        #     print("DEBUG: Last fact generation - Priority function arguments")
        #     print("="*80)
        #     print(f"\nFacts program (current story facts):\n{facts_program}")
        #     print(f"\nDefinite rules program:\n{definite_rules_program}")
        #     print(f"\nValid candidates ({len(valid_candidates)} total):")
        #     for i, (cand, details, entailed) in enumerate(valid_candidates, 1):
        #         print(f"\n  Candidate {i}: {cand}")
        #         print(f"  Entailed facts for this candidate:")
        #         if entailed:
        #             for line in entailed.split('\n'):
        #                 print(f"    {line}")
        #         else:
        #             print(f"    (none)")
        #     print("="*80 + "\n")
        
        # Choose max priority; tie broken arbitrarily by max()
        # valid_candidates now has structure: (cand_fact, cand_details, entailed_facts_str)
        best_fact, best_details, best_entailed = max(
            valid_candidates,
            key=lambda x: self.priority_fn(x[0], definite_rules_program, x[2], facts_program),
        )
        return best_fact, best_details

    def _propose_one_candidate_fact(
        self,
        entities: List[int],
    ) -> Tuple[str, List[Tuple[Tuple[int, int], str]]]:
        """
        Propose ONE candidate fact drawn from:
          - living_in(person, place)
          - living_in_same_place(person, person)
          - plausible relations (excluding exclude list)
          - no_* property facts about an entity (candidates)
          - gender assignment facts (candidates)
          - underage assignment facts (candidates)

        NOTE: This does NOT check clingo validity; caller does.
        """
        # --- Special relation candidates (same as mock) ------------------------
        if (random.random() < self.assign_loc_prob) and self.people and self.places:
            p_pers = random.choice(self.people)
            p_place = random.choice(self.places)
            fact = f"living_in({p_pers},{p_place})."
            return fact, [((p_pers, p_place), "living_in")]

        if (random.random() < self.prob_living_in_same_place) and (len(self.people) >= 2):
            e1, e2 = random.sample(self.people, 2)
            fact = f"living_in_same_place({e1},{e2})."
            return fact, [((e1, e2), "living_in_same_place")]

        # --- Candidate bucket choice ------------------------------------------
        # We include property/gender/underage candidates in the same stream.
        bucket = random.choice(["plausible_rel", "no_prop", "gender", "underage"])

        if bucket == "no_prop":
            # no_* facts about a person (binary in your mock: pred(P,P).)
            p = random.choice(self.people) if self.people else random.choice(entities)
            no_pred = self._sample_no_property_predicate()
            fact = f"{no_pred}({p},{p})."
            return fact, [((p, p), no_pred)]

        if bucket == "gender":
            # either is_male(P,P) or is_female(P,P); sometimes generate "no gender" by skipping bucket
            p = random.choice(self.people) if self.people else random.choice(entities)
            if random.random() < self.male_prob:
                pred = "is_male"
            else:
                pred = "is_female"
            fact = f"{pred}({p},{p})."
            return fact, [((p, p), pred)]

        if bucket == "underage":
            p = random.choice(self.people) if self.people else random.choice(entities)
            pred = "is_underage"
            fact = f"{pred}({p},{p})."
            return fact, [((p, p), pred)]

        # --- Default: plausible relations excluding some predicates ------------
        updated_rels = [rel for rel in self.plausible_relations if rel[0] not in self.exclude_preds_during_gen]
        if not updated_rels:
            # fallback
            e1, e2 = random.sample(entities, 2) if len(entities) >= 2 else (0, 0)
            fact = f"rel({e1},{e2})."
            return fact, [((e1, e2), "rel")]

        relation, num_args = random.choice(updated_rels)
        num_args = int(num_args)

        if num_args == 2:
            e1, e2 = random.sample(entities, 2)
            fact = f"{relation}({e1},{e2})."
            return fact, [((e1, e2), relation)]
        elif num_args == 1:
            e1 = random.choice(entities)
            fact = f"{relation}({e1})."
            return fact, [((e1, e1), relation)]
        elif num_args == 0:
            fact = f"{relation}."
            return fact, [((0, 0), relation)]

        # Fallback unexpected arity -> 0-ary
        fact = f"{relation}."
        return fact, [((0, 0), relation)]

    def _rule_to_string(self, rule: Tuple[Tuple[str, List[str]], List[Tuple[str, List[str]]]]) -> str:
        """Convert a parsed rule back to string format."""
        (head_pred, head_vars), body = rule
        head_str = f"{head_pred}({','.join(head_vars)})"
        body_strs = [f"{pred}({','.join(vars)})" for pred, vars in body]
        return f"{head_str} :- {', '.join(body_strs)}."
    
    def _constraint_to_string(self, constraint: List[Tuple[str, List[str]]]) -> str:
        """Convert a parsed constraint back to string format."""
        body_strs = [f"{pred}({','.join(vars)})" for pred, vars in constraint]
        return f":- {', '.join(body_strs)}."

    def _sample_no_property_predicate(self) -> str:
        """
        Sample which no_* property predicate to propose, using the same
        probabilities as the mock (but now as candidates).
        """
        r = random.random()
        # Convert four probabilities to a categorical distribution
        probs = [
            ("no_brothers", self.prob_property_no_bros),
            ("no_sisters", self.prob_property_no_sis),
            ("no_daughters", self.prob_property_no_dghter),
            ("no_sons", self.prob_property_no_son),
        ]
        total = sum(p for _, p in probs)
        if total <= 0:
            return "no_brothers"

        # normalize cumulative
        cum = 0.0
        u = random.random() * total
        for name, p in probs:
            cum += p
            if u <= cum:
                return name
        return probs[-1][0]

    # ----------------------------------------------------------------------
    # FACT VERIFICATION
    # ----------------------------------------------------------------------

    def _verify_fact(
        self,
        fact: str,
        program: str,
        consecutive_contradictions: int,
        too_many_consecutive_contradictions: int,
    ) -> Tuple[bool, str, List[set], int, bool]:
        # generate_prio_fact already validates every candidate with clingo,
        # so the fact is guaranteed to be consistent — skip the redundant check.
        temp_program = program + fact + "\n"
        consecutive_contradictions = 0
        return True, temp_program, [], consecutive_contradictions, False

    # ----------------------------------------------------------------------
    # ENTAILED FACTS
    # ----------------------------------------------------------------------

    def _compute_entailed_facts_from_program(
        self,
        program: str,
        explicit_story_facts: set,
    ) -> List[str]:
        models = run_clingo(program)
        if not models:
            return []

        # TODO: If your real run_clingo returns clingo.Atom objects, adjust stringification accordingly.
        model_fact_sets = [{str(atom) + "." for atom in model} for model in models]
        intersection_facts = functools.reduce(lambda a, b: a & b, model_fact_sets)
        non_trivial_entailed = intersection_facts - explicit_story_facts
        return list(non_trivial_entailed)

def priority(cand_fact: str, definite_rules_program: str, entailed_facts: str, facts_program: str) -> float:
    """
    Priority function for selecting among candidate facts.

    Inputs:
      - cand_fact: candidate fact string, e.g. "father_of(1,3)."
      - definite_rules_program: string containing all definite (Horn) rules
      - entailed_facts: string containing facts in the stable model that are not in story facts or candidate facts
      - facts_program: string containing all ground facts

    FunSearch should evolve this function.
    """
    global _priority_call_count
    try:
        _priority_call_count += 1
    except NameError:
        _priority_call_count = 1
    
    if _priority_call_count == 11:
        pass
        # print("\n=== PRIORITY FUNCTION CALL #5 ===")
        # print(f"cand_fact of type {type(cand_fact)} :\n{cand_fact}")
        # print(f"\ndefinite_rules_program of type {type(definite_rules_program)} :\n{definite_rules_program}")
        # print(f"\nentailed_facts of type {type(entailed_facts)} :\n{entailed_facts}")
        # print(f"\nfacts_program of type {type(facts_program)} :\n{facts_program}")
        # print("=" * 50 + "\n")
    
    return 0.0

if __name__ == "__main__":
    # Resolve path to world rules file relative to this file
    this_dir = os.path.dirname(os.path.abspath(__file__))
    rules_path = os.path.join(this_dir, "..", "Collaterals", "NoRa1.1.txt")

    # Instantiate priority-based generator (single story)
    generator = PrioStoryGeneratorNoRa1_1(
        priority_fn=priority,      # current dummy priority
        seed=42,                   # reproducible
        min_entities=5,
        max_entities=8,
        min_story_facts_mult=2,
        max_story_facts_mult=2.5,
        num_cands=3,
    )

    # Generate ONE story
    story_info = generator.generate_story_from_rules(rules_path)

    print("\n=== BASIC STORY INFO ===")
    print("Entities:", story_info["entities"])
    print("People  :", story_info["people"])
    print("Places  :", story_info["places"])

    print("\n=== EXPLICIT STORY FACTS ===")
    for f in story_info["story_facts"]:
        print(f)

    print("\n=== NON-TRIVIAL ENTAILED FACTS ===")
    for f in story_info["entailed_facts"]:
        print(f)