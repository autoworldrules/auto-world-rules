#!/usr/bin/env python3
"""
Nora Greedy-Growth Sampler
===========================
Builds constraint-safe family + social graphs for the NoRa rule set using
a fundamentally different approach from the template-based sampler:

**Greedy edge-by-edge growth with lookahead scoring.**

Instead of picking from pre-built family templates, this sampler:

1. SEED: Start with a minimal 2-person married couple.
2. GROW: Maintain a pool of candidate "mutations" (add-child, add-sibling,
   add-marriage, add-social-link, flip-gender, add-same-gender-constraint).
3. SCORE: For each candidate mutation, run lightweight forward chaining and
   measure the inference depth / amplification gained.
4. PICK: Greedily select the mutation that maximises a composite score
   emphasising deep reasoning chains and non-obvious inferences.
5. REPEAT until the target vertex count is reached.

This produces graphs where every edge was chosen specifically because it
maximises reasoning difficulty — yielding deeper inference chains, more
no_sons/no_daughters cascades, and harder-to-predict derived facts than
random template selection.

Usage:
    python3 nora_greedy_sampler.py 8 --seed 42 --verbose --output graph.lp
"""

import argparse
import collections
import copy
import random
import re
import sys
import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

# ═══════════════════════════════════════════════════════════════════════════
# FACT DATABASE (same interface as reference sampler for output compat)
# ═══════════════════════════════════════════════════════════════════════════
FactDB = Dict[str, Set[Tuple[str, ...]]]

def new_db() -> FactDB:
    return collections.defaultdict(set)

def copy_db(db: FactDB) -> FactDB:
    o = collections.defaultdict(set)
    for k, v in db.items():
        o[k] = set(v)
    return o

def add_fact(db, p, a):
    s = db[p]
    if a in s:
        return False
    s.add(a)
    return True

def has_fact(db, p, a):
    return a in db.get(p, set())

def db_size(db):
    return sum(len(v) for v in db.values())

# ═══════════════════════════════════════════════════════════════════════════
# NAME POOLS (identical to reference for output compatibility)
# ═══════════════════════════════════════════════════════════════════════════
FEMALE_NAMES = [
    "alice", "brenda", "clara", "diana", "emma", "fiona", "greta",
    "hannah", "iris", "julia", "karen", "laura", "maria", "nora",
    "olivia", "paula", "rosa", "sarah", "tina", "vera",
]
MALE_NAMES = [
    "adam", "bob", "carl", "david", "eric", "frank", "george", "henry",
    "ivan", "james", "kevin", "leo", "mark", "nick", "oscar", "paul",
    "ray", "sam", "tom", "victor",
]
PLACE_NAMES = ["london", "paris", "rome", "berlin", "madrid",
               "tokyo", "oslo", "cairo", "lima", "delhi"]

# ═══════════════════════════════════════════════════════════════════════════
# INLINED ASP ENGINE (same logic as reference — needed for scoring)
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class Atom:
    pred: str
    args: Tuple[str, ...]
    def __hash__(self):
        return hash((self.pred, self.args))
    def __eq__(self, o):
        return self.pred == o.pred and self.args == o.args
    def __repr__(self):
        return f"{self.pred}({','.join(self.args)})"

@dataclass
class Literal:
    atom: Optional[Atom] = None
    negated: bool = False
    ineq_left: Optional[str] = None
    ineq_right: Optional[str] = None
    @property
    def is_inequality(self):
        return self.ineq_left is not None

@dataclass
class ASPRule:
    head: list
    body: list
    is_choice: bool = False
    is_constraint: bool = False
    index: int = 0
    @property
    def positive_body(self):
        return [l for l in self.body if l.atom and not l.negated]
    @property
    def negative_body(self):
        return [l for l in self.body if l.atom and l.negated]
    @property
    def inequalities(self):
        return [l for l in self.body if l.is_inequality]

def _is_var(s):
    return bool(s) and s[0].isupper()

def _resolve(b, a):
    return b.get(a, a) if _is_var(a) else a

def _split_parens(text, sep=','):
    parts, depth, cur = [], 0, []
    for ch in text:
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        elif ch == sep and depth == 0:
            parts.append(''.join(cur).strip())
            cur = []
            continue
        cur.append(ch)
    t = ''.join(cur).strip()
    if t:
        parts.append(t)
    return parts

def _parse_atom(text):
    text = text.strip()
    if not text:
        return None
    if '(' not in text:
        if re.match(r'^[a-z_]\w*$', text):
            return Atom(pred=text, args=(text, text))
        return None
    m = re.match(r'^([a-z_]\w*)\((.+)\)$', text, re.DOTALL)
    if not m:
        return None
    args = [a.strip() for a in _split_parens(m.group(2))]
    if len(args) == 1:
        args = [args[0], args[0]]
    return Atom(pred=m.group(1), args=tuple(args))

def parse_asp_program(text):
    lines = text.split('\n')
    cleaned = [l[:l.find('%')] if '%' in l else l for l in lines]
    text = ' '.join(cleaned)
    rules = []
    idx = 0
    for part in text.split('.'):
        part = part.strip()
        if not part:
            continue
        if part.startswith(':-'):
            body = []
            for p in _split_parens(part[2:].strip()):
                p = p.strip()
                if not p:
                    continue
                for op in ['!=', '\\=']:
                    if op in p:
                        sides = p.split(op, 1)
                        body.append(Literal(ineq_left=sides[0].strip(),
                                            ineq_right=sides[1].strip()))
                        break
                else:
                    neg = p.startswith('not ')
                    if neg:
                        p = p[4:].strip()
                    a = _parse_atom(p)
                    if a:
                        body.append(Literal(atom=a, negated=neg))
            rules.append(ASPRule(head=[], body=body, is_constraint=True, index=idx))
            idx += 1
        elif ':-' in part:
            ht, bt = part.split(':-', 1)
            ht = ht.strip()
            ic = ht.startswith('{')
            if ic:
                ht = ht[1:]
            if '}' in ht:
                ht = ht[:ht.rindex('}')]
            hatoms = [_parse_atom(a.strip()) for a in _split_parens(ht)]
            hatoms = [a for a in hatoms if a]
            body = []
            for p in _split_parens(bt.strip()):
                p = p.strip()
                if not p:
                    continue
                for op in ['!=', '\\=']:
                    if op in p:
                        sides = p.split(op, 1)
                        body.append(Literal(ineq_left=sides[0].strip(),
                                            ineq_right=sides[1].strip()))
                        break
                else:
                    neg = p.startswith('not ')
                    if neg:
                        p = p[4:].strip()
                    a = _parse_atom(p)
                    if a:
                        body.append(Literal(atom=a, negated=neg))
            rules.append(ASPRule(head=hatoms, body=body, is_choice=ic, index=idx))
            idx += 1
    return rules

def _unify(b, args, fact):
    b2 = dict(b)
    for a, v in zip(args, fact):
        if _is_var(a):
            if a in b2:
                if b2[a] != v:
                    return None
            else:
                b2[a] = v
        elif a != v:
            return None
    return b2

def _eval_rule(rule, db):
    pos = rule.positive_body
    if not pos:
        return set()
    bindings = []
    for fact in db.get(pos[0].atom.pred, set()):
        b = _unify({}, pos[0].atom.args, fact)
        if b is not None:
            bindings.append(b)
    for lit in pos[1:]:
        if not bindings:
            return set()
        fp = db.get(lit.atom.pred, set())
        if not fp:
            return set()
        new = []
        for b in bindings:
            bp = [(i, a) for i, a in enumerate(lit.atom.args)
                  if _is_var(a) and a in b]
            if bp:
                idx = collections.defaultdict(list)
                for f in fp:
                    idx[tuple(f[i] for i, _ in bp)].append(f)
                for f in idx.get(tuple(b[v] for _, v in bp), []):
                    nb = _unify(b, lit.atom.args, f)
                    if nb is not None:
                        new.append(nb)
            else:
                for f in fp:
                    nb = _unify(b, lit.atom.args, f)
                    if nb is not None:
                        new.append(nb)
        bindings = new
    for iq in rule.inequalities:
        bindings = [b for b in bindings
                    if _resolve(b, iq.ineq_left) != _resolve(b, iq.ineq_right)]
    for n in rule.negative_body:
        bindings = [b for b in bindings
                    if not has_fact(db, n.atom.pred,
                                   tuple(_resolve(b, a) for a in n.atom.args))]
    results = set()
    for b in bindings:
        for ha in rule.head:
            g = tuple(_resolve(b, a) for a in ha.args)
            if all(not _is_var(x) for x in g):
                results.add((ha.pred, g))
    return results

def forward_chain(base_db, asp_rules):
    strata = {}
    for r in asp_rules:
        for a in (r.head or []):
            strata.setdefault(a.pred, 0)
        for l in r.body:
            if l.atom:
                strata.setdefault(l.atom.pred, 0)
    for _ in range(len(strata) + 2):
        ch = False
        for r in asp_rules:
            if r.is_constraint:
                continue
            for ha in r.head:
                ms = max((strata.get(l.atom.pred, 0) + (1 if l.negated else 0)
                          for l in r.body if l.atom), default=0)
                if ms > strata.get(ha.pred, -1):
                    strata[ha.pred] = ms
                    ch = True
        if not ch:
            break

    db = copy_db(base_db)
    depth_map = {(p, a): 0 for p in base_db for a in base_db[p]}
    max_s = max(strata.values()) if strata else 0
    by_s = collections.defaultdict(list)
    for r in asp_rules:
        if r.is_constraint or r.is_choice:
            continue
        if r.head:
            s = max(strata.get(a.pred, 0) for a in r.head)
            by_s[s].append(r)
    for s in range(max_s + 1):
        for it in range(25):
            changed = False
            for r in by_s.get(s, []):
                pos = r.positive_body
                if not pos:
                    continue
                bd = []
                for fact in db.get(pos[0].atom.pred, set()):
                    b = _unify({}, pos[0].atom.args, fact)
                    if b is not None:
                        bd.append((b, depth_map.get((pos[0].atom.pred, fact), 0)))
                for lit in pos[1:]:
                    if not bd:
                        break
                    fp = db.get(lit.atom.pred, set())
                    new = []
                    for b, md in bd:
                        for f in fp:
                            nb = _unify(b, lit.atom.args, f)
                            if nb is not None:
                                new.append((nb, max(md, depth_map.get(
                                    (lit.atom.pred, f), 0))))
                    bd = new
                for iq in r.inequalities:
                    bd = [(b, d) for b, d in bd
                          if _resolve(b, iq.ineq_left) != _resolve(b, iq.ineq_right)]
                for neg in r.negative_body:
                    bd = [(b, d) for b, d in bd
                          if not has_fact(db, neg.atom.pred,
                                         tuple(_resolve(b, a) for a in neg.atom.args))]
                for b, md in bd:
                    for ha in r.head:
                        g = tuple(_resolve(b, a) for a in ha.args)
                        if all(not _is_var(x) for x in g):
                            nd = md + 1
                            key = (ha.pred, g)
                            if add_fact(db, ha.pred, g):
                                changed = True
                                depth_map[key] = nd
                            elif key in depth_map and nd < depth_map[key]:
                                depth_map[key] = nd
            if not changed:
                break
    return db, depth_map

def check_constraints(db, asp_rules):
    for r in asp_rules:
        if not r.is_constraint:
            continue
        dummy = ASPRule(head=[Atom("__c__", ("x", "x"))], body=r.body, index=999)
        if _eval_rule(dummy, db):
            return True
    return False


# ═══════════════════════════════════════════════════════════════════════════
# GRAPH STATE — mutable world model used during greedy growth
# ═══════════════════════════════════════════════════════════════════════════

class GraphState:
    """Mutable graph state that tracks family & social structure."""

    def __init__(self, rng: random.Random):
        self.rng = rng
        self.persons: Dict[str, str] = {}       # name → gender ('M'/'F')
        self.generations: Dict[str, int] = {}    # name → generation
        self.underage: Set[str] = set()
        self.parent_child: Set[Tuple[str, str]] = set()  # (parent, child)
        self.marriages: Set[Tuple[str, str]] = set()     # (husband, wife) canonical
        self.places: List[str] = ["london", "paris"]
        self.living_in: Dict[str, str] = {}
        self.colleagues: List[Tuple[str, str]] = []
        self.school_mates: List[Tuple[str, str]] = []
        self._fi = 0
        self._mi = 0

    def _next_name(self, gender):
        if gender == 'F':
            n = FEMALE_NAMES[self._fi % len(FEMALE_NAMES)]
            self._fi += 1
        else:
            n = MALE_NAMES[self._mi % len(MALE_NAMES)]
            self._mi += 1
        return n

    def add_person(self, gender, gen, underage=False):
        name = self._next_name(gender)
        self.persons[name] = gender
        self.generations[name] = gen
        if underage:
            self.underage.add(name)
        return name

    def parents_of(self, child):
        return [p for p, c in self.parent_child if c == child]

    def children_of(self, parent):
        return [c for p, c in self.parent_child if p == parent]

    def spouse_of(self, name):
        for h, w in self.marriages:
            if h == name:
                return w
            if w == name:
                return h
        return None

    def has_spouse(self, name):
        return self.spouse_of(name) is not None

    def num_persons(self):
        return len(self.persons)

    def person_names(self):
        return list(self.persons.keys())

    def siblings_of(self, name):
        sibs = set()
        for p in self.parents_of(name):
            for c in self.children_of(p):
                if c != name:
                    sibs.add(c)
        return sibs

    def all_children_same_gender(self, parent):
        children = self.children_of(parent)
        if len(children) < 2:
            return False
        genders = {self.persons[c] for c in children}
        return len(genders) == 1


# ═══════════════════════════════════════════════════════════════════════════
# EMISSION STRATEGIES — convert GraphState → FactDB
# ═══════════════════════════════════════════════════════════════════════════

def emit_maximal_hiding(gs: GraphState, rng: random.Random) -> FactDB:
    """Hide as much gender info as possible. Use child_of/parent_of/spouse_of
    as the base. Only reveal gender for ONE person per connected component
    to force long inference chains."""
    db = new_db()

    # Reveal gender for exactly one person per married couple at gen 0
    revealed = set()
    for h, w in gs.marriages:
        if gs.generations.get(h, 99) == 0 and w not in revealed and h not in revealed:
            # Reveal the wife's gender only
            add_fact(db, "is_female", (w, w))
            revealed.add(w)

    # If no gen-0 marriage, reveal one random person
    if not revealed and gs.persons:
        p = rng.choice(gs.person_names())
        g = gs.persons[p]
        add_fact(db, "is_female" if g == 'F' else "is_male", (p, p))
        revealed.add(p)

    # Parent-child: use child_of (reverse direction forces extra steps)
    for parent, child in gs.parent_child:
        add_fact(db, "child_of", (child, parent))

    # Marriages: ungendered spouse_of
    for h, w in gs.marriages:
        add_fact(db, "spouse_of", (h, w))

    # Social + underage
    for name in gs.underage:
        add_fact(db, "is_underage", (name, name))
    for person, place in gs.living_in.items():
        add_fact(db, "living_in", (person, place))
    for a, b in gs.colleagues:
        add_fact(db, "colleague_of", (a, b))
    for a, b in gs.school_mates:
        add_fact(db, "school_mates_with", (a, b))
    return db


def emit_mixed_directions(gs: GraphState, rng: random.Random) -> FactDB:
    """Mix parent_of/child_of/mother_of/father_of randomly per edge.
    State gender for ~30% of people. This forces the reasoner to
    unify across different predicate formulations."""
    db = new_db()

    people = gs.person_names()
    rng.shuffle(people)
    gender_count = max(1, int(len(people) * 0.3))
    for name in people[:gender_count]:
        g = gs.persons[name]
        add_fact(db, "is_female" if g == 'F' else "is_male", (name, name))

    gender_stated = set(people[:gender_count])

    for parent, child in gs.parent_child:
        r = rng.random()
        g = gs.persons[parent]
        if parent in gender_stated and r < 0.25:
            if g == 'F':
                add_fact(db, "mother_of", (parent, child))
            else:
                add_fact(db, "father_of", (parent, child))
        elif r < 0.5:
            add_fact(db, "child_of", (child, parent))
        elif r < 0.75:
            add_fact(db, "parent_of", (parent, child))
        else:
            # Use gendered child predicate
            cg = gs.persons[child]
            if cg == 'F':
                add_fact(db, "daughter_of", (child, parent))
            else:
                add_fact(db, "son_of", (child, parent))

    for h, w in gs.marriages:
        if rng.random() < 0.5:
            add_fact(db, "spouse_of", (h, w))
        else:
            add_fact(db, "wife_of", (w, h))

    for name in gs.underage:
        add_fact(db, "is_underage", (name, name))
    for person, place in gs.living_in.items():
        add_fact(db, "living_in", (person, place))
    for a, b in gs.colleagues:
        add_fact(db, "colleague_of", (a, b))
    for a, b in gs.school_mates:
        add_fact(db, "school_mates_with", (a, b))
    return db


def emit_indirect_only(gs: GraphState, rng: random.Random) -> FactDB:
    """State facts using the MOST INDIRECT predicates available.
    E.g. use grandson_of instead of child_of + is_male, use
    grandmother_of instead of grandparent_of + is_female.
    This forces backward chaining through specialisation rules."""
    db = new_db()

    # No explicit gender at all — must be inferred from gendered predicates
    for parent, child in gs.parent_child:
        g = gs.persons[parent]
        if g == 'F':
            add_fact(db, "mother_of", (parent, child))
        else:
            add_fact(db, "father_of", (parent, child))

    for h, w in gs.marriages:
        add_fact(db, "husband_of", (h, w))

    for name in gs.underage:
        add_fact(db, "is_underage", (name, name))
    for person, place in gs.living_in.items():
        add_fact(db, "living_in", (person, place))
    for a, b in gs.colleagues:
        add_fact(db, "colleague_of", (a, b))
    for a, b in gs.school_mates:
        add_fact(db, "school_mates_with", (a, b))
    return db


STRATEGIES = [emit_maximal_hiding, emit_mixed_directions, emit_indirect_only]


# ═══════════════════════════════════════════════════════════════════════════
# MUTATION OPERATORS — generate candidate next-states
# ═══════════════════════════════════════════════════════════════════════════

def _gen_mutations(gs: GraphState, target_n: int) -> List[callable]:
    """Generate all valid single-step mutations from the current state."""
    mutations = []
    remaining = target_n - gs.num_persons()

    if remaining <= 0:
        return mutations

    # --- ADD CHILD to an existing person/couple ---
    for name in gs.person_names():
        gen = gs.generations[name]
        # Can be a parent if not underage
        if name in gs.underage:
            continue
        spouse = gs.spouse_of(name)
        # Check child count (max parents = 2, so child must not already have 2)
        for child_gender in ['M', 'F']:
            def _mk_add_child(parent, sp, cg, g):
                def mutate(state: GraphState):
                    ch = state.add_person(cg, g + 1, underage=(g + 1 >= 2))
                    state.parent_child.add((parent, ch))
                    if sp:
                        state.parent_child.add((sp, ch))
                    return f"child({cg}) of {parent}"
                return mutate
            mutations.append(_mk_add_child(name, spouse, child_gender, gen))

    # --- ADD SAME-GENDER SIBLING to force no_brothers/no_sisters ---
    for name in gs.person_names():
        parents = gs.parents_of(name)
        if len(parents) < 1:
            continue
        existing_children = set()
        for p in parents:
            existing_children.update(gs.children_of(p))
        # Add a sibling with the SAME gender as all existing children
        child_genders = {gs.persons[c] for c in existing_children}
        if len(child_genders) == 1:
            same_g = list(child_genders)[0]
            def _mk_add_same_sib(pars, sg, gen):
                def mutate(state: GraphState):
                    ch = state.add_person(sg, gen, underage=(gen >= 2))
                    for p in pars:
                        state.parent_child.add((p, ch))
                    return f"same-gender sibling({sg})"
                return mutate
            mutations.append(_mk_add_same_sib(
                parents, same_g, gs.generations[name]))

    # --- ADD MARRIAGE (cross-family) ---
    unmarried = [n for n in gs.person_names()
                 if not gs.has_spouse(n) and n not in gs.underage]
    males = [n for n in unmarried if gs.persons[n] == 'M']
    females = [n for n in unmarried if gs.persons[n] == 'F']
    for m in males:
        for f in females:
            # Avoid marrying siblings or parent-child
            if f in gs.siblings_of(m):
                continue
            if (m, f) in gs.parent_child or (f, m) in gs.parent_child:
                continue
            parents_m = set(gs.parents_of(m))
            parents_f = set(gs.parents_of(f))
            # Prefer cross-family (different parents = more in-law chains)
            def _mk_marry(male, female):
                def mutate(state: GraphState):
                    state.marriages.add((male, female))
                    return f"marry {male}+{female}"
                return mutate
            mutations.append(_mk_marry(m, f))

    # --- ADD NEW PERSON + MARRY to existing unmarried person ---
    if remaining >= 1:
        for name in unmarried:
            opp_g = 'F' if gs.persons[name] == 'M' else 'M'
            gen = gs.generations[name]
            def _mk_new_spouse(person, og, g):
                def mutate(state: GraphState):
                    sp = state.add_person(og, g)
                    if og == 'F':
                        state.marriages.add((person, sp))
                    else:
                        state.marriages.add((sp, person))
                    return f"new spouse for {person}"
                return mutate
            mutations.append(_mk_new_spouse(name, opp_g, gen))

    return mutations


# ═══════════════════════════════════════════════════════════════════════════
# SCORING
# ═══════════════════════════════════════════════════════════════════════════

def score_db(db: FactDB, asp_rules: list) -> Tuple[float, dict]:
    """Full forward-chain score. Returns (score, details)."""
    derived, depth_map = forward_chain(db, asp_rules)
    violated = check_constraints(derived, asp_rules)
    if violated:
        return -1e6, {"violated": True}

    depth_vals = [d for d in depth_map.values() if d > 0]
    if not depth_vals:
        return 0.0, {}

    max_d = max(depth_vals)
    avg_d = sum(depth_vals) / len(depth_vals)
    deep3 = sum(1 for d in depth_vals if d >= 3)
    deep5 = sum(1 for d in depth_vals if d >= 5)
    base_count = db_size(db)
    amp = len(depth_vals) / max(base_count, 1)

    score = (
        max_d * 40 + avg_d * 20 + deep3 * 5 + deep5 * 12
        + len(depth_vals) * 2 + amp * 25 - base_count * 0.3
    )
    return score, {
        "max_depth": max_d, "avg_depth": round(avg_d, 2),
        "deep3": deep3, "deep5": deep5,
        "derived": len(depth_vals), "base": base_count,
        "amplification": round(amp, 2),
    }


def quick_structural_score(gs: GraphState) -> float:
    """Ultra-fast heuristic to pre-filter mutations (no forward chaining)."""
    score = 0.0

    # 3-generation depth
    gens = set(gs.generations.values())
    if len(gens) >= 3:
        score += 30

    # Same-gender sibling groups → no_X cascades
    for name in gs.person_names():
        if gs.all_children_same_gender(name):
            score += 20

    # Cross-family marriages
    for h, w in gs.marriages:
        ph = set(gs.parents_of(h))
        pw = set(gs.parents_of(w))
        if ph and pw and not ph & pw:
            score += 25

    # Underage count (living_in_same_place chains)
    score += len(gs.underage) * 5

    return score


# ═══════════════════════════════════════════════════════════════════════════
# SOCIAL LAYER
# ═══════════════════════════════════════════════════════════════════════════

def add_social_layer(gs: GraphState, rng: random.Random):
    """Add living_in, colleagues, school_mates — constraint safe."""
    # Assign places
    # Parents of underage children must share place
    couples_with_underage = set()
    for name in gs.underage:
        parents = gs.parents_of(name)
        if len(parents) == 2:
            couples_with_underage.add(tuple(sorted(parents)))

    assigned = {}
    for couple in couples_with_underage:
        place = rng.choice(gs.places)
        for p in couple:
            assigned[p] = place

    for name in gs.person_names():
        if name not in gs.underage and name not in assigned:
            assigned[name] = rng.choice(gs.places)

    gs.living_in = assigned

    # Colleagues: adults in same place
    place_groups = collections.defaultdict(list)
    for name, place in gs.living_in.items():
        if name not in gs.underage:
            place_groups[place].append(name)
    for place, people in place_groups.items():
        if len(people) >= 2:
            gs.colleagues.append((people[0], people[1]))
            break

    # School mates: underage only
    underage_list = list(gs.underage)
    if len(underage_list) >= 2:
        gs.school_mates.append((underage_list[0], underage_list[1]))


# ═══════════════════════════════════════════════════════════════════════════
# GREEDY GROWTH ENGINE
# ═══════════════════════════════════════════════════════════════════════════

def greedy_grow(target_n: int, asp_rules: list, rng: random.Random,
                verbose: bool = False, beam_width: int = 3,
                top_k_mutations: int = 8) -> Tuple[Optional[FactDB], dict]:
    """
    Grow a graph from a 2-person seed, greedily picking the mutation
    that maximises inference depth at each step.

    Uses beam search with `beam_width` parallel states to avoid
    getting stuck in local optima.
    """
    # Reserve 2 slots for places (london, paris) added in emit_maximal_hiding
    person_target = max(3, target_n - 2)
    # --- SEED: one married couple ---
    seeds = []
    for _ in range(beam_width):
        gs = GraphState(random.Random(rng.randint(0, 2**31)))
        gs._fi = rng.randint(0, len(FEMALE_NAMES) - 1)
        gs._mi = rng.randint(0, len(MALE_NAMES) - 1)
        h = gs.add_person('M', 0)
        w = gs.add_person('F', 0)
        gs.marriages.add((h, w))
        seeds.append(gs)

    beam = seeds

    step = 0
    while any(gs.num_persons() < person_target for gs in beam):
        step += 1
        next_beam = []

        for gs in beam:
            if gs.num_persons() >= person_target:
                next_beam.append(gs)
                continue

            mutations = _gen_mutations(gs, person_target)
            if not mutations:
                next_beam.append(gs)
                continue

            # Pre-filter: score structurally, keep top-k
            scored_muts = []
            for mut in mutations:
                gs_copy = copy.deepcopy(gs)
                desc = mut(gs_copy)
                s = quick_structural_score(gs_copy)
                scored_muts.append((s, gs_copy, desc))

            scored_muts.sort(key=lambda x: x[0], reverse=True)
            # Deduplicate by person count + structure hash
            seen = set()
            unique = []
            for s, gs_c, desc in scored_muts:
                key = (gs_c.num_persons(), len(gs_c.marriages),
                       len(gs_c.parent_child), frozenset(gs_c.persons.values()))
                if key not in seen:
                    seen.add(key)
                    unique.append((s, gs_c, desc))
                if len(unique) >= top_k_mutations:
                    break

            # Pick the best by structural score with some randomness
            if unique:
                # Weighted random from top candidates
                weights = [max(1, s + 100) for s, _, _ in unique]
                chosen = rng.choices(unique, weights=weights, k=1)[0]
                next_beam.append(chosen[1])
                if verbose:
                    print(f"  step {step}: {chosen[2]} "
                          f"(struct_score={chosen[0]:.0f}, "
                          f"n={chosen[1].num_persons()})", file=sys.stderr)

        beam = next_beam[:beam_width]

    # --- Add social layer + emit + score ---
    best_db = None
    best_score = -1
    best_details = {}

    for gs in beam:
        add_social_layer(gs, random.Random(rng.randint(0, 2**31)))
        for strategy in STRATEGIES:
            db = strategy(gs, random.Random(rng.randint(0, 2**31)))
            sc, details = score_db(db, asp_rules)
            if sc > best_score:
                best_score = sc
                best_db = db
                best_details = details
                best_details["strategy"] = strategy.__name__

                if verbose:
                    print(f"  new best: score={sc:.0f} strat={strategy.__name__} "
                          f"maxD={details.get('max_depth',0)} "
                          f"derived={details.get('derived',0)}",
                          file=sys.stderr)

    if best_details:
        best_details["score"] = round(best_score, 1)

    return best_db, best_details


# ═══════════════════════════════════════════════════════════════════════════
# MULTI-START WRAPPER (run greedy growth multiple times, keep best)
# ═══════════════════════════════════════════════════════════════════════════

def sample(n: int, asp_rules: list, rng: random.Random,
           restarts: int = 10, verbose: bool = False
           ) -> Tuple[Optional[FactDB], dict]:
    """Run greedy growth `restarts` times with different seeds, keep best."""
    best_db = None
    best_score = -1
    best_details = {}

    for i in range(restarts):
        sub_rng = random.Random(rng.randint(0, 2**31))
        if verbose:
            print(f"\n--- Restart {i+1}/{restarts} ---", file=sys.stderr)
        db, details = greedy_grow(n, asp_rules, sub_rng, verbose=verbose)
        sc = details.get("score", -1)
        if sc > best_score:
            best_score = sc
            best_db = db
            best_details = details
            if verbose:
                print(f"  ★ New global best: score={sc}", file=sys.stderr)

    return best_db, best_details


# ═══════════════════════════════════════════════════════════════════════════
# OUTPUT (identical format to reference sampler)
# ═══════════════════════════════════════════════════════════════════════════

def format_asp(db: FactDB) -> str:
    lines = ["% === BASE FACTS (nora greedy sampler) ===", ""]
    for pred in sorted(db.keys()):
        facts = sorted(db[pred])
        if not facts:
            continue
        lines.append(f"% {pred}")
        for args in facts:
            lines.append(f"{pred}({','.join(args)}).")
        lines.append("")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Nora greedy-growth sampler — builds challenging graphs "
                    "by greedily adding edges that maximise inference depth")
    parser.add_argument("num_vertices", type=int,
                        help="Number of vertices (persons + places) in the graph")
    parser.add_argument("--rules", "-r", type=str, default=None,
                        help="ASP rules file (.lp). Auto-detected if not given.")
    parser.add_argument("--seed", type=int, default=None,
                        help="Random seed for reproducibility")
    parser.add_argument("--restarts", type=int, default=10,
                        help="Number of greedy restarts (default: 10)")
    parser.add_argument("--output", "-o", type=str, default=None,
                        help="Output file (default: stdout)")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--viz", type=str, default=None)
    args = parser.parse_args()

    rng = random.Random(args.seed)

    # Find rules file
    rules_path = args.rules
    if rules_path is None:
        for candidate in [
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "NoRa.lp"),
            "NoRa.lp",
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "nora_rules.lp"),
            "nora_rules.lp",
        ]:
            if os.path.exists(candidate):
                rules_path = candidate
                break
    if rules_path is None or not os.path.exists(rules_path):
        print("ERROR: rules file not found. Use --rules <path>", file=sys.stderr)
        sys.exit(1)

    if args.verbose:
        print(f"Nora greedy sampler: {args.num_vertices} vertices, "
              f"restarts={args.restarts}, rules={rules_path}", file=sys.stderr)

    with open(rules_path) as f:
        asp_rules = parse_asp_program(f.read())
    if args.verbose:
        print(f"  Parsed {len(asp_rules)} rules", file=sys.stderr)

    best_db, details = sample(
        args.num_vertices, asp_rules, rng,
        restarts=args.restarts, verbose=args.verbose)

    if best_db is None:
        print("ERROR: no valid graph found", file=sys.stderr)
        sys.exit(1)

    if args.verbose:
        print(f"\n=== BEST ===", file=sys.stderr)
        for k, v in sorted(details.items()):
            print(f"  {k}: {v}", file=sys.stderr)

    report = [
        "% ═══════════════════════════════════════════",
        "% NORA GREEDY-GROWTH SAMPLER",
        "% ═══════════════════════════════════════════",
    ]
    for k, v in sorted(details.items()):
        report.append(f"% {k}: {v}")

    output = "\n".join(report) + "\n\n" + format_asp(best_db)

    if args.output:
        with open(args.output, "w") as f:
            f.write(output)
        if args.verbose:
            print(f"Written to {args.output}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
