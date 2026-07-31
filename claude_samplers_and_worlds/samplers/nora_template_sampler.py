#!/usr/bin/env python3
"""
Nora Domain-Specific Sampler
=============================
Builds constraint-safe family + social graphs for the nora rule set.

The nora rules have ~170 rules and ~70 constraints, making random/general
sampling extremely fragile. This sampler builds valid graphs by construction:

1. FAMILY SKELETON: Create a multi-generation family tree with controlled
   gender assignments, respecting all cardinality constraints (max 2 parents,
   1 spouse, gender exclusivity).

2. SINGLE-GENDER TRIGGERS: Deliberately create families where all children
   are the same gender, enabling the no_sons/no_daughters/no_brothers/
   no_sisters cascade → maternal/paternal disambiguation chains.

3. CROSS-FAMILY MARRIAGES: Marry members from different founding families
   to create in-law derivation chains.

4. SOCIAL LAYER: Add living_in, school_mates_with, colleague_of, is_underage
   on top of the family structure.

5. STRATEGIC OMISSION: State some facts via gendered predicates (mother_of,
   father_of) and others via ungendered (parent_of), forcing gender
   inference through chains.

6. POPULATION SAMPLING: Generate multiple configurations and keep the best.

Usage:
    python3 nora_sampler.py 6 --seed 42 --verbose --output graph.lp
"""

import argparse
import collections
import copy
import json
import os
import random
import re
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

# ═══════════════════════════════════════════════════════════════════════════
FactDB = Dict[str, Set[Tuple[str, ...]]]
def new_db() -> FactDB: return collections.defaultdict(set)
def copy_db(db):
    o = collections.defaultdict(set)
    for k, v in db.items(): o[k] = set(v)
    return o
def add_fact(db, p, a):
    s = db[p]
    if a in s: return False
    s.add(a); return True
def has_fact(db, p, a): return a in db.get(p, set())
def db_size(db): return sum(len(v) for v in db.values())

# ═══════════════════════════════════════════════════════════════════════════
# NAME POOLS
# ═══════════════════════════════════════════════════════════════════════════
FEMALE_NAMES = ["alice","brenda","clara","diana","emma","fiona","greta",
                "hannah","iris","julia","karen","laura","maria","nora",
                "olivia","paula","rosa","sarah","tina","vera"]
MALE_NAMES = ["adam","bob","carl","david","eric","frank","george","henry",
              "ivan","james","kevin","leo","mark","nick","oscar","paul",
              "ray","sam","tom","victor"]
PLACE_NAMES = ["london","paris","rome","berlin","madrid","tokyo","oslo",
               "cairo","lima","delhi"]

# ═══════════════════════════════════════════════════════════════════════════
# FAMILY TREE BUILDER
# ═══════════════════════════════════════════════════════════════════════════

class Person:
    __slots__ = ("name","gender","generation","is_underage")
    def __init__(self, name, gender, gen, underage=False):
        self.name = name; self.gender = gender
        self.generation = gen; self.is_underage = underage

class FamilyGraph:
    """Builds a constraint-safe family + social graph."""

    def __init__(self, rng):
        self.rng = rng
        self.persons: Dict[str, Person] = {}
        self.marriages: List[Tuple[str, str]] = []   # (husband, wife)
        self.parent_child: List[Tuple[str, str]] = [] # (parent, child)
        self.places: List[str] = []
        self.living_in: Dict[str, str] = {}  # person → place
        self.colleagues: List[Tuple[str, str]] = []
        self.school_mates: List[Tuple[str, str]] = []
        self._fi = 0; self._mi = 0

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
        self.persons[name] = Person(name, gender, gen, underage)
        return name

    def add_marriage(self, husband, wife):
        self.marriages.append((husband, wife))

    def add_parent_child(self, parent, child):
        self.parent_child.append((parent, child))

    def parents_of(self, child):
        return [p for p, c in self.parent_child if c == child]

    def children_of(self, parent):
        return [c for p, c in self.parent_child if p == parent]

    def siblings_of(self, name):
        sibs = set()
        for p in self.parents_of(name):
            for c in self.children_of(p):
                if c != name: sibs.add(c)
        return sibs

    def spouse_of(self, name):
        for h, w in self.marriages:
            if h == name: return w
            if w == name: return h
        return None

    def all_children_same_gender(self, parent):
        """Check if all children of parent are the same gender."""
        children = self.children_of(parent)
        if len(children) < 2: return False
        genders = {self.persons[c].gender for c in children}
        return len(genders) == 1


def build_family(n: int, rng: random.Random) -> FamilyGraph:
    """Build a family tree using diverse structural templates."""
    fg = FamilyGraph(rng)
    # Shuffle name pools for variety (without mutating globals)
    fg._fi = rng.randint(0, len(FEMALE_NAMES) - 1)
    fg._mi = rng.randint(0, len(MALE_NAMES) - 1)

    if n <= 4:
        return _template_nuclear(fg, n, rng)
    elif n <= 5:
        return rng.choice([_template_nuclear, _template_extended])(fg, n, rng)
    elif n <= 7:
        templates = [
            _template_extended,
            _template_3gen_son_marries,
            _template_3gen_daughter_marries,
            _template_all_sons,
            _template_all_daughters,
            _template_two_couples,
        ]
        return rng.choice(templates)(fg, n, rng)
    else:
        return _template_multigenerational(fg, n, rng)


def _social_layer(fg, rng):
    """Add living_in, colleagues, school_mates — constraint-safe."""
    fg.places = ["london", "paris"]

    # Parents of underage children MUST share same place
    couples_with_underage = set()
    for name, p in fg.persons.items():
        if p.is_underage:
            parents = fg.parents_of(name)
            if len(parents) == 2:
                couples_with_underage.add(tuple(sorted(parents)))

    assigned = {}
    for couple in couples_with_underage:
        place = rng.choice(fg.places)
        for p in couple:
            assigned[p] = place

    for name, p in fg.persons.items():
        if not p.is_underage and name not in assigned:
            assigned[name] = rng.choice(fg.places)

    fg.living_in = assigned

    # Colleagues: adults in same place, not underage
    place_groups = collections.defaultdict(list)
    for name, place in fg.living_in.items():
        if not fg.persons[name].is_underage:
            place_groups[place].append(name)
    for place, people in place_groups.items():
        if len(people) >= 2:
            fg.colleagues.append((people[0], people[1]))
            break

    # School mates: underage only
    underage = [p for p in fg.persons if fg.persons[p].is_underage]
    if len(underage) >= 2:
        fg.school_mates.append((underage[0], underage[1]))


def _template_nuclear(fg, n, rng):
    """2 parents + children."""
    fa = fg.add_person('M', 0)
    mo = fg.add_person('F', 0)
    fg.add_marriage(fa, mo)
    for i in range(n - 2):
        g = rng.choice(['M','F'])
        ch = fg.add_person(g, 1, underage=(rng.random() < 0.5))
        fg.add_parent_child(fa, ch)
        fg.add_parent_child(mo, ch)
    fg.places = ["london"]
    fg.living_in = {p: "london" for p in fg.persons if not fg.persons[p].is_underage}
    return fg


def _template_extended(fg, n, rng):
    """Grandparents + parent + aunt/uncle + spouse + grandchild."""
    gp = fg.add_person('M', 0)
    gm = fg.add_person('F', 0)
    fg.add_marriage(gp, gm)
    parent = fg.add_person('M', 1)
    sibling = fg.add_person('F', 1)
    fg.add_parent_child(gp, parent); fg.add_parent_child(gm, parent)
    fg.add_parent_child(gp, sibling); fg.add_parent_child(gm, sibling)
    used = 4
    if used < n:
        spouse = fg.add_person('F', 1)
        fg.add_marriage(parent, spouse); used += 1
    if used < n:
        gc = fg.add_person(rng.choice(['M','F']), 2, underage=True)
        fg.add_parent_child(parent, gc)
        sp = fg.spouse_of(parent)
        if sp: fg.add_parent_child(sp, gc)
        used += 1
    while used < n:
        gc2 = fg.add_person(rng.choice(['M','F']), 2, underage=True)
        fg.add_parent_child(parent, gc2)
        sp = fg.spouse_of(parent)
        if sp: fg.add_parent_child(sp, gc2)
        used += 1
    _social_layer(fg, rng)
    return fg


def _template_3gen_son_marries(fg, n, rng):
    """GP+GM → son + daughter; son marries outsider → grandchild.
    Son inherits the paternal line → triggers paternal_grandparent."""
    gp = fg.add_person('M', 0)
    gm = fg.add_person('F', 0)
    fg.add_marriage(gp, gm)
    son = fg.add_person('M', 1)
    daughter = fg.add_person('F', 1)
    fg.add_parent_child(gp, son); fg.add_parent_child(gm, son)
    fg.add_parent_child(gp, daughter); fg.add_parent_child(gm, daughter)
    used = 4
    if used < n:
        wife = fg.add_person('F', 1)
        fg.add_marriage(son, wife); used += 1
    if used < n:
        gc = fg.add_person(rng.choice(['M','F']), 2, underage=True)
        fg.add_parent_child(son, gc)
        w = fg.spouse_of(son)
        if w: fg.add_parent_child(w, gc)
        used += 1
    while used < n:
        gc2 = fg.add_person(rng.choice(['M','F']), 2, underage=True)
        fg.add_parent_child(son, gc2)
        w = fg.spouse_of(son)
        if w: fg.add_parent_child(w, gc2)
        used += 1
    _social_layer(fg, rng)
    return fg


def _template_3gen_daughter_marries(fg, n, rng):
    """GP+GM → son + daughter; DAUGHTER marries outsider → grandchild.
    Daughter's husband becomes son_in_law; maternal grandparent chain."""
    gp = fg.add_person('M', 0)
    gm = fg.add_person('F', 0)
    fg.add_marriage(gp, gm)
    son = fg.add_person('M', 1)
    daughter = fg.add_person('F', 1)
    fg.add_parent_child(gp, son); fg.add_parent_child(gm, son)
    fg.add_parent_child(gp, daughter); fg.add_parent_child(gm, daughter)
    used = 4
    if used < n:
        husband = fg.add_person('M', 1)
        fg.add_marriage(husband, daughter); used += 1
    if used < n:
        gc = fg.add_person(rng.choice(['M','F']), 2, underage=True)
        fg.add_parent_child(daughter, gc)
        h = fg.spouse_of(daughter)
        if h: fg.add_parent_child(h, gc)
        used += 1
    while used < n:
        gc2 = fg.add_person(rng.choice(['M','F']), 2, underage=True)
        fg.add_parent_child(daughter, gc2)
        h = fg.spouse_of(daughter)
        if h: fg.add_parent_child(h, gc2)
        used += 1
    _social_layer(fg, rng)
    return fg


def _template_all_sons(fg, n, rng):
    """GP+GM → ALL MALE children → triggers no_daughters, no_sisters cascade.
    One son marries → grandchild."""
    gp = fg.add_person('M', 0)
    gm = fg.add_person('F', 0)
    fg.add_marriage(gp, gm)
    sons = []
    for _ in range(min(2, n - 2)):
        s = fg.add_person('M', 1)
        fg.add_parent_child(gp, s); fg.add_parent_child(gm, s)
        sons.append(s)
    used = 2 + len(sons)
    if used < n and sons:
        wife = fg.add_person('F', 1)
        fg.add_marriage(sons[0], wife); used += 1
    if used < n and sons:
        gc = fg.add_person(rng.choice(['M','F']), 2, underage=True)
        fg.add_parent_child(sons[0], gc)
        w = fg.spouse_of(sons[0])
        if w: fg.add_parent_child(w, gc)
        used += 1
    while used < n:
        gc2 = fg.add_person('M', 2, underage=True)  # more sons!
        fg.add_parent_child(sons[0], gc2)
        w = fg.spouse_of(sons[0])
        if w: fg.add_parent_child(w, gc2)
        used += 1
    _social_layer(fg, rng)
    return fg


def _template_all_daughters(fg, n, rng):
    """GP+GM → ALL FEMALE children → triggers no_sons, no_brothers cascade."""
    gp = fg.add_person('M', 0)
    gm = fg.add_person('F', 0)
    fg.add_marriage(gp, gm)
    daughters = []
    for _ in range(min(2, n - 2)):
        d = fg.add_person('F', 1)
        fg.add_parent_child(gp, d); fg.add_parent_child(gm, d)
        daughters.append(d)
    used = 2 + len(daughters)
    if used < n and daughters:
        husband = fg.add_person('M', 1)
        fg.add_marriage(husband, daughters[0]); used += 1
    if used < n and daughters:
        gc = fg.add_person(rng.choice(['M','F']), 2, underage=True)
        fg.add_parent_child(daughters[0], gc)
        h = fg.spouse_of(daughters[0])
        if h: fg.add_parent_child(h, gc)
        used += 1
    while used < n:
        gc2 = fg.add_person('F', 2, underage=True)  # more daughters!
        fg.add_parent_child(daughters[0], gc2)
        h = fg.spouse_of(daughters[0])
        if h: fg.add_parent_child(h, gc2)
        used += 1
    _social_layer(fg, rng)
    return fg


def _template_two_couples(fg, n, rng):
    """Two unrelated couples + children. Focuses on in-law derivations
    when children from different families marry each other."""
    fa1 = fg.add_person('M', 0); mo1 = fg.add_person('F', 0)
    fg.add_marriage(fa1, mo1)
    son1 = fg.add_person('M', 1)
    fg.add_parent_child(fa1, son1); fg.add_parent_child(mo1, son1)
    used = 3
    if used < n:
        fa2 = fg.add_person('M', 0); mo2 = fg.add_person('F', 0)
        fg.add_marriage(fa2, mo2)
        used += 2
    else:
        _social_layer(fg, rng); return fg
    if used < n:
        daughter2 = fg.add_person('F', 1)
        fg.add_parent_child(fa2, daughter2); fg.add_parent_child(mo2, daughter2)
        # Cross-family marriage!
        fg.add_marriage(son1, daughter2)
        used += 1
    while used < n:
        gc = fg.add_person(rng.choice(['M','F']), 2, underage=True)
        fg.add_parent_child(son1, gc)
        w = fg.spouse_of(son1)
        if w: fg.add_parent_child(w, gc)
        used += 1
    _social_layer(fg, rng)
    return fg


def _template_multigenerational(fg, n, rng):
    """Two founding families → cross-marriage → grandchildren.
    
    Family A: grandpa_a + grandma_a -> son_a + daughter_a
    Family B: grandpa_b + grandma_b -> son_b
    Marriage: son_a + wife (new person) OR daughter_a + son_b
    Children of married couple
    """
    # Family A
    gpa = fg.add_person('M', 0)
    gma = fg.add_person('F', 0)
    fg.add_marriage(gpa, gma)
    son_a = fg.add_person('M', 1)
    daughter_a = fg.add_person('F', 1)
    fg.add_parent_child(gpa, son_a)
    fg.add_parent_child(gma, son_a)
    fg.add_parent_child(gpa, daughter_a)
    fg.add_parent_child(gma, daughter_a)
    used = 4

    if used < n:
        # Wife for son_a (from outside, or family B)
        wife_a = fg.add_person('F', 1)
        fg.add_marriage(son_a, wife_a)
        used += 1

    if used < n:
        # Grandchild (child of son_a + wife_a)
        g = rng.choice(['M', 'F'])
        gc = fg.add_person(g, 2, underage=True)
        fg.add_parent_child(son_a, gc)
        if fg.spouse_of(son_a):
            fg.add_parent_child(fg.spouse_of(son_a), gc)
        used += 1

    # Fill remaining with more grandchildren or family B
    while used < n:
        # Add another child to an existing couple
        gen1_married = [(p, fg.spouse_of(p)) for p in fg.persons
                        if fg.persons[p].generation == 1
                        and fg.spouse_of(p) is not None
                        and fg.persons[p].gender == 'M']
        if gen1_married:
            par, sp = rng.choice(gen1_married)
            g = rng.choice(['M', 'F'])
            ch = fg.add_person(g, 2, underage=True)
            fg.add_parent_child(par, ch)
            fg.add_parent_child(sp, ch)
        else:
            # Just add a person
            fg.add_person(rng.choice(['M','F']), 1)
        used += 1

    # Social layer
    _social_layer(fg, rng)

    return fg


# ═══════════════════════════════════════════════════════════════════════════
# FACT SELECTION STRATEGIES
# ═══════════════════════════════════════════════════════════════════════════

def emit_full_gendered(fg: FamilyGraph, rng: random.Random) -> FactDB:
    """Emit facts using gendered predicates where possible — baseline."""
    db = new_db()
    for name, p in fg.persons.items():
        if p.gender == 'F': add_fact(db, "is_female", (name, name))
        else: add_fact(db, "is_male", (name, name))
        if p.is_underage: add_fact(db, "is_underage", (name, name))

    for parent, child in fg.parent_child:
        p = fg.persons[parent]
        if p.gender == 'F':
            add_fact(db, "mother_of", (parent, child))
        else:
            add_fact(db, "father_of", (parent, child))

    for h, w in fg.marriages:
        add_fact(db, "husband_of", (h, w))

    for person, place in fg.living_in.items():
        add_fact(db, "living_in", (person, place))

    for a, b in fg.colleagues:
        add_fact(db, "colleague_of", (a, b))

    for a, b in fg.school_mates:
        add_fact(db, "school_mates_with", (a, b))

    return db


def emit_sparse_challenging(fg: FamilyGraph, rng: random.Random) -> FactDB:
    """Strategic omission: force gender inference chains.
    
    Safe approach: always state parent-child links correctly (gendered
    or ungendered), but omit SOME gender facts to force inference.
    """
    db = new_db()

    # Gender: state for ~50% of people
    people_list = list(fg.persons.keys())
    rng.shuffle(people_list)
    gender_stated = set(people_list[:int(len(people_list) * 0.5)])

    for name in gender_stated:
        p = fg.persons[name]
        if p.gender == 'F': add_fact(db, "is_female", (name, name))
        else: add_fact(db, "is_male", (name, name))

    for name, p in fg.persons.items():
        if p.is_underage: add_fact(db, "is_underage", (name, name))

    # Parent-child: mix gendered and ungendered,
    # but ensure both parents are stated for each child
    for parent, child in fg.parent_child:
        p = fg.persons[parent]
        if parent in gender_stated and rng.random() < 0.5:
            if p.gender == 'F': add_fact(db, "mother_of", (parent, child))
            else: add_fact(db, "father_of", (parent, child))
        else:
            add_fact(db, "parent_of", (parent, child))

    # Marriages: ungendered
    for h, w in fg.marriages:
        add_fact(db, "spouse_of", (h, w))

    # Social
    for person, place in fg.living_in.items():
        add_fact(db, "living_in", (person, place))
    for a, b in fg.colleagues:
        add_fact(db, "colleague_of", (a, b))
    for a, b in fg.school_mates:
        add_fact(db, "school_mates_with", (a, b))

    return db


def emit_minimal_deep(fg: FamilyGraph, rng: random.Random) -> FactDB:
    """Maximum inference: state child_of + spouse_of + ONE gender seed.
    Everything else must be derived."""
    db = new_db()

    # Only child_of (ungendered)
    for parent, child in fg.parent_child:
        add_fact(db, "child_of", (child, parent))

    # Spouse: ungendered
    for h, w in fg.marriages:
        add_fact(db, "spouse_of", (h, w))

    # Gender: ONE seed per family (forces maximum inference)
    stated = set()
    for h, w in fg.marriages:
        if fg.persons[h].generation == 0 and w not in stated:
            add_fact(db, "is_female", (w, w))
            stated.add(w)

    # Underage + social
    for name, p in fg.persons.items():
        if p.is_underage: add_fact(db, "is_underage", (name, name))
    for person, place in fg.living_in.items():
        add_fact(db, "living_in", (person, place))
    for a, b in fg.colleagues:
        add_fact(db, "colleague_of", (a, b))
    for a, b in fg.school_mates:
        add_fact(db, "school_mates_with", (a, b))

    return db


STRATEGIES = [emit_full_gendered, emit_sparse_challenging, emit_minimal_deep]


# ═══════════════════════════════════════════════════════════════════════════
# INLINED ASP ENGINE (no external dependencies)
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class Atom:
    pred: str; args: Tuple[str, ...]
    def __hash__(self): return hash((self.pred, self.args))
    def __eq__(self, o): return self.pred == o.pred and self.args == o.args
    def __repr__(self): return f"{self.pred}({','.join(self.args)})"

@dataclass
class Literal:
    atom: Optional[Atom] = None; negated: bool = False
    ineq_left: Optional[str] = None; ineq_right: Optional[str] = None
    @property
    def is_inequality(self): return self.ineq_left is not None

@dataclass
class ASPRule:
    head: list; body: list
    is_choice: bool = False; is_constraint: bool = False; index: int = 0
    @property
    def positive_body(self): return [l for l in self.body if l.atom and not l.negated]
    @property
    def negative_body(self): return [l for l in self.body if l.atom and l.negated]
    @property
    def inequalities(self): return [l for l in self.body if l.is_inequality]

def _is_var(s): return bool(s) and s[0].isupper()
def _resolve(b, a): return b.get(a, a) if _is_var(a) else a

def _split_parens(text, sep=','):
    parts, depth, cur = [], 0, []
    for ch in text:
        if ch == '(': depth += 1
        elif ch == ')': depth -= 1
        elif ch == sep and depth == 0: parts.append(''.join(cur).strip()); cur = []; continue
        cur.append(ch)
    t = ''.join(cur).strip()
    if t: parts.append(t)
    return parts

def _parse_atom(text):
    text = text.strip()
    if not text: return None
    if '(' not in text:
        if re.match(r'^[a-z_]\w*$', text): return Atom(pred=text, args=(text, text))
        return None
    m = re.match(r'^([a-z_]\w*)\((.+)\)$', text, re.DOTALL)
    if not m: return None
    args = [a.strip() for a in _split_parens(m.group(2))]
    if len(args) == 1: args = [args[0], args[0]]
    return Atom(pred=m.group(1), args=tuple(args))

def parse_asp_program(text):
    lines = text.split('\n')
    cleaned = [l[:l.find('%')] if '%' in l else l for l in lines]
    text = ' '.join(cleaned); rules = []; idx = 0
    for part in text.split('.'):
        part = part.strip()
        if not part: continue
        if part.startswith(':-'):
            body = []
            for p in _split_parens(part[2:].strip()):
                p = p.strip()
                if not p: continue
                for op in ['!=', '\\=']:
                    if op in p:
                        sides = p.split(op, 1)
                        body.append(Literal(ineq_left=sides[0].strip(), ineq_right=sides[1].strip())); break
                else:
                    neg = p.startswith('not ')
                    if neg: p = p[4:].strip()
                    a = _parse_atom(p)
                    if a: body.append(Literal(atom=a, negated=neg))
            rules.append(ASPRule(head=[], body=body, is_constraint=True, index=idx)); idx += 1
        elif ':-' in part:
            ht, bt = part.split(':-', 1)
            # Parse head
            ht = ht.strip(); ic = ht.startswith('{')
            if ic: ht = ht[1:]
            if '}' in ht: ht = ht[:ht.rindex('}')]
            hatoms = [_parse_atom(a.strip()) for a in _split_parens(ht)]
            hatoms = [a for a in hatoms if a]
            # Parse body
            body = []
            for p in _split_parens(bt.strip()):
                p = p.strip()
                if not p: continue
                for op in ['!=', '\\=']:
                    if op in p:
                        sides = p.split(op, 1)
                        body.append(Literal(ineq_left=sides[0].strip(), ineq_right=sides[1].strip())); break
                else:
                    neg = p.startswith('not ')
                    if neg: p = p[4:].strip()
                    a = _parse_atom(p)
                    if a: body.append(Literal(atom=a, negated=neg))
            rules.append(ASPRule(head=hatoms, body=body, is_choice=ic, index=idx)); idx += 1
    return rules

def _unify(b, args, fact):
    b2 = dict(b)
    for a, v in zip(args, fact):
        if _is_var(a):
            if a in b2:
                if b2[a] != v: return None
            else: b2[a] = v
        elif a != v: return None
    return b2

def _eval_rule(rule, db):
    pos = rule.positive_body
    if not pos: return set()
    bindings = []
    for fact in db.get(pos[0].atom.pred, set()):
        b = _unify({}, pos[0].atom.args, fact)
        if b is not None: bindings.append(b)
    for lit in pos[1:]:
        if not bindings: return set()
        fp = db.get(lit.atom.pred, set())
        if not fp: return set()
        new = []
        for b in bindings:
            bp = [(i, a) for i, a in enumerate(lit.atom.args) if _is_var(a) and a in b]
            if bp:
                idx = collections.defaultdict(list)
                for f in fp: idx[tuple(f[i] for i, _ in bp)].append(f)
                for f in idx.get(tuple(b[v] for _, v in bp), []):
                    nb = _unify(b, lit.atom.args, f)
                    if nb is not None: new.append(nb)
            else:
                for f in fp:
                    nb = _unify(b, lit.atom.args, f)
                    if nb is not None: new.append(nb)
        bindings = new
    for iq in rule.inequalities:
        bindings = [b for b in bindings if _resolve(b, iq.ineq_left) != _resolve(b, iq.ineq_right)]
    for n in rule.negative_body:
        bindings = [b for b in bindings
                    if not has_fact(db, n.atom.pred, tuple(_resolve(b, a) for a in n.atom.args))]
    results = set()
    for b in bindings:
        for ha in rule.head:
            g = tuple(_resolve(b, a) for a in ha.args)
            if all(not _is_var(x) for x in g): results.add((ha.pred, g))
    return results

def forward_chain(base_db, asp_rules):
    """Inlined forward chainer. Returns (derived_db, depth_map)."""
    # Stratify
    strata = {}
    for r in asp_rules:
        for a in (r.head or []):
            strata.setdefault(a.pred, 0)
        for l in r.body:
            if l.atom: strata.setdefault(l.atom.pred, 0)
    for _ in range(len(strata) + 2):
        ch = False
        for r in asp_rules:
            if r.is_constraint: continue
            for ha in r.head:
                ms = max((strata.get(l.atom.pred, 0) + (1 if l.negated else 0)
                          for l in r.body if l.atom), default=0)
                if ms > strata.get(ha.pred, -1): strata[ha.pred] = ms; ch = True
        if not ch: break

    db = copy_db(base_db)
    depth_map = {(p, a): 0 for p in base_db for a in base_db[p]}
    max_s = max(strata.values()) if strata else 0
    by_s = collections.defaultdict(list)
    for r in asp_rules:
        if r.is_constraint or r.is_choice: continue
        if r.head:
            s = max(strata.get(a.pred, 0) for a in r.head)
            by_s[s].append(r)
    for s in range(max_s + 1):
        for it in range(25):
            changed = False
            for r in by_s.get(s, []):
                pos = r.positive_body
                if not pos: continue
                bd = []
                for fact in db.get(pos[0].atom.pred, set()):
                    b = _unify({}, pos[0].atom.args, fact)
                    if b is not None: bd.append((b, depth_map.get((pos[0].atom.pred, fact), 0)))
                for lit in pos[1:]:
                    if not bd: break
                    fp = db.get(lit.atom.pred, set())
                    new = []
                    for b, md in bd:
                        for f in fp:
                            nb = _unify(b, lit.atom.args, f)
                            if nb is not None:
                                new.append((nb, max(md, depth_map.get((lit.atom.pred, f), 0))))
                    bd = new
                for iq in r.inequalities:
                    bd = [(b,d) for b,d in bd
                          if _resolve(b, iq.ineq_left) != _resolve(b, iq.ineq_right)]
                for neg in r.negative_body:
                    bd = [(b,d) for b,d in bd
                          if not has_fact(db, neg.atom.pred,
                                         tuple(_resolve(b, a) for a in neg.atom.args))]
                for b, md in bd:
                    for ha in r.head:
                        g = tuple(_resolve(b, a) for a in ha.args)
                        if all(not _is_var(x) for x in g):
                            nd = md + 1; key = (ha.pred, g)
                            if add_fact(db, ha.pred, g):
                                changed = True; depth_map[key] = nd
                            elif key in depth_map and nd < depth_map[key]:
                                depth_map[key] = nd
            if not changed: break
    return db, depth_map

def check_constraints(db, asp_rules):
    for r in asp_rules:
        if not r.is_constraint: continue
        dummy = ASPRule(head=[Atom("__c__", ("x","x"))], body=r.body, index=999)
        if _eval_rule(dummy, db): return True
    return False


def _db_to_lp(db):
    """Convert FactDB to ASP text."""
    lines = []
    for pred, facts in db.items():
        for args in facts:
            lines.append(f"{pred}({','.join(args)}).")
    return '\n'.join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# LIGHTWEIGHT EVALUATOR (no subprocess, just structural proxy)
# ═══════════════════════════════════════════════════════════════════════════

def quick_score(db: FactDB, fg: FamilyGraph) -> float:
    """Fast structural proxy score (no forward chaining).
    Estimates reasoning complexity from graph topology."""
    base = db_size(db)

    # Count relationship types present
    preds = set(db.keys())
    family_preds = {"parent_of","child_of","mother_of","father_of","spouse_of",
                    "husband_of","wife_of","sibling_of","sister_of","brother_of",
                    "daughter_of","son_of"}
    social_preds = {"living_in","colleague_of","school_mates_with","is_underage"}
    gender_preds = {"is_male","is_female"}

    family_present = len(preds & family_preds)
    social_present = len(preds & social_preds)

    # Count people without explicit gender (forces inference)
    explicit_gender = set()
    for p in ["is_male","is_female","mother_of","father_of","husband_of",
              "wife_of","sister_of","brother_of","daughter_of","son_of"]:
        for args in db.get(p, set()):
            explicit_gender.add(args[0])

    num_people = len(fg.persons)
    gender_hidden = num_people - len(explicit_gender & set(fg.persons.keys()))

    # Count same-gender families (triggers no_X chains)
    same_gender_families = 0
    for name in fg.persons:
        if fg.all_children_same_gender(name):
            same_gender_families += 1

    # Cross-family marriages (triggers in-law chains)
    cross_marriages = 0
    for h, w in fg.marriages:
        parents_h = set(fg.parents_of(h))
        parents_w = set(fg.parents_of(w))
        if parents_h and parents_w and not parents_h & parents_w:
            cross_marriages += 1

    # Grandparent potential (3 generations)
    has_3_gen = len(set(fg.persons[p].generation for p in fg.persons)) >= 3

    # Underage children (triggers living_in_same_place)
    num_underage = sum(1 for p in fg.persons.values() if p.is_underage)

    score = (
        - base * 0.3                    # penalise bloat
        + family_present * 5
        + social_present * 8
        + gender_hidden * 12             # hidden genders = inference work
        + same_gender_families * 15      # no_X cascade triggers
        + cross_marriages * 20           # in-law chains
        + has_3_gen * 25                 # grandparent depth
        + num_underage * 10              # living_in_same_place chains
    )
    return score


# ═══════════════════════════════════════════════════════════════════════════
# POPULATION SAMPLER
# ═══════════════════════════════════════════════════════════════════════════

def sample_population(n: int, pop_size: int, rng: random.Random,
                      asp_rules: list,
                      verbose: bool = False):
    """Generate diverse candidates and pick the best."""

    candidates = []

    for i in range(pop_size):
        sub_rng = random.Random(rng.randint(0, 2**31))
        # Templates add 1-2 places (nuclear=1, extended=2).
        # Reserve 1 place for small N, 2 for larger N.
        n_reserve = 1 if n <= 5 else 2
        n_persons = max(3, n - n_reserve)
        fg = build_family(n_persons, sub_rng)

        # Generate ALL strategies for this family graph
        for strategy in STRATEGIES:
            db = strategy(fg, random.Random(sub_rng.randint(0, 2**31)))
            score = quick_score(db, fg)
            candidates.append((db, fg, score, strategy.__name__))

    # Sort by proxy score
    candidates.sort(key=lambda x: x[2], reverse=True)

    if verbose:
        print(f"  {len(candidates)} candidates generated", file=sys.stderr)
        for db, fg, sc, strat in candidates[:5]:
            print(f"    proxy={sc:.0f} base={db_size(db)} strat={strat}",
                  file=sys.stderr)

    # Ensure we evaluate at least some from EACH strategy
    by_strategy = collections.defaultdict(list)
    for item in candidates:
        by_strategy[item[3]].append(item)

    eval_list = []
    # Take top candidates from each strategy
    for strat in STRATEGIES:
        strat_items = by_strategy.get(strat.__name__, [])
        eval_list.extend(strat_items[:5])

    # Add remaining top candidates
    eval_set = set(id(x[0]) for x in eval_list)
    for item in candidates:
        if id(item[0]) not in eval_set and len(eval_list) < 25:
            eval_list.append(item)
            eval_set.add(id(item[0]))

    # Evaluate: try full_gendered first (most likely to be valid)
    eval_list.sort(key=lambda x: (0 if x[3] == "emit_full_gendered" else 1, -x[2]))

    best_db = None
    best_score = -1
    best_details = {}
    evaluated = 0
    valid = 0

    for db, fg, proxy_sc, strat in eval_list:
        evaluated += 1
        derived, depth_map = forward_chain(db, asp_rules)
        violated = check_constraints(derived, asp_rules)

        if violated:
            if verbose and evaluated <= 8:
                print(f"    VIOLATED: {strat} (proxy={proxy_sc:.0f})",
                      file=sys.stderr)
            continue

        valid += 1
        depth_vals = [d for d in depth_map.values() if d > 0]
        if not depth_vals:
            continue

        max_d = max(depth_vals)
        avg_d = sum(depth_vals) / len(depth_vals)
        deep3 = sum(1 for d in depth_vals if d >= 3)
        deep5 = sum(1 for d in depth_vals if d >= 5)
        base_count = db_size(db)
        amp = len(depth_vals) / max(base_count, 1)

        real_score = (
            max_d * 40 + avg_d * 20 + deep3 * 5 + deep5 * 12
            + len(depth_vals) * 2 + amp * 25 - base_count * 0.3
        )

        if verbose:
            print(f"    {strat}: real={real_score:.0f} maxD={max_d} "
                  f"avgD={avg_d:.1f} derived={len(depth_vals)} "
                  f"base={base_count}", file=sys.stderr)

        if real_score > best_score:
            best_score = real_score
            best_db = db
            best_details = {
                "strategy": strat, "score": real_score,
                "max_depth": max_d, "avg_depth": avg_d,
                "deep3": deep3, "deep5": deep5,
                "derived": len(depth_vals), "base": base_count,
                "amplification": amp,
            }

    if verbose:
        print(f"  Evaluated: {evaluated}, Valid: {valid}", file=sys.stderr)

    return best_db, best_details


# ═══════════════════════════════════════════════════════════════════════════
# OUTPUT
# ═══════════════════════════════════════════════════════════════════════════

def format_asp(db: FactDB) -> str:
    lines = ["% === BASE FACTS (nora sampler) ===", ""]
    for pred in sorted(db.keys()):
        facts = sorted(db[pred])
        if not facts: continue
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
        description="Nora domain-specific sampler")
    parser.add_argument("num_vertices", type=int)
    parser.add_argument("--rules", "-r", type=str, default=None,
                        help="ASP rules file (.lp). Auto-detected if not specified.")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--population", type=int, default=30,
                        help="Population size (default: 30)")
    parser.add_argument("--output", "-o", type=str, default=None)
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--viz", type=str, default=None)
    args = parser.parse_args()

    rng = random.Random(args.seed)

    # Find rules file
    rules_path = args.rules
    if rules_path is None:
        # Auto-detect: look for nora_rules.lp in script dir, then CWD
        for candidate in [
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "nora_rules.lp"),
            "nora_rules.lp",
        ]:
            if os.path.exists(candidate):
                rules_path = candidate; break
    if rules_path is None or not os.path.exists(rules_path):
        print("ERROR: rules file not found. Use --rules <path>", file=sys.stderr)
        sys.exit(1)

    if args.verbose:
        print(f"Nora sampler: {args.num_vertices} vertices, "
              f"pop={args.population}, rules={rules_path}", file=sys.stderr)

    # Parse rules ONCE
    with open(rules_path) as f:
        asp_rules = parse_asp_program(f.read())
    if args.verbose:
        print(f"  Parsed {len(asp_rules)} rules", file=sys.stderr)

    best_db, details = sample_population(
        args.num_vertices, args.population, rng,
        asp_rules=asp_rules, verbose=args.verbose)

    if best_db is None:
        print("ERROR: no valid graph found", file=sys.stderr)
        sys.exit(1)

    if args.verbose:
        print(f"\n=== BEST ===", file=sys.stderr)
        for k, v in sorted(details.items()):
            print(f"  {k}: {v}", file=sys.stderr)

    report = ["% ═══════════════════════════════════════════",
              "% NORA DOMAIN-SPECIFIC SAMPLER",
              "% ═══════════════════════════════════════════"]
    for k, v in sorted(details.items()):
        report.append(f"% {k}: {v}")

    output = "\n".join(report) + "\n\n" + format_asp(best_db)

    if args.output:
        with open(args.output, "w") as f: f.write(output)
        if args.verbose:
            print(f"Written to {args.output}", file=sys.stderr)
    else:
        print(output)

    if args.viz:
        import asp_viz
        # Would need forward chaining for full viz
        asp_viz.visualize_db(best_db, args.viz,
                             title="Nora — Sampled Graph")
        if args.verbose:
            print(f"Viz written to {args.viz}", file=sys.stderr)


if __name__ == "__main__":
    main()
