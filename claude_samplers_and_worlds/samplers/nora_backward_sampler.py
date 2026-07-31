#!/usr/bin/env python3
"""
Nora Backward-Chaining Goal-Driven Sampler
============================================
Builds constraint-safe family + social graphs for the NoRa rule set using
a **goal-driven backward-chaining** approach:

Instead of building structure forward (templates or greedy growth) and hoping
for deep inference chains, this sampler works BACKWARDS:

1. GOAL SELECTION: Pick "deep target" derived facts that require long rule
   chains — e.g. paternal_grandmother_of, maternal_uncle_of, nephew_of via
   the grandson+no_sons path, or gender inferred through no_daughters chains.

2. BACKWARD DECOMPOSITION: For each target fact, trace backwards through the
   NoRa rules to find one proof tree — a set of base facts sufficient to
   derive the target. Each proof tree is a "recipe" for a sub-graph.

3. RECIPE COMPOSITION: Combine multiple recipes that share persons to fill
   the vertex budget, maximising the number of deep derivations per vertex.

4. OBFUSCATION: Emit the base facts using indirect predicates (child_of
   instead of parent_of, spouse_of instead of husband_of) and hide gender
   information to force maximum inference work.

5. VALIDATION: Forward-chain and verify no constraints are violated.

This guarantees every generated graph contains at least one (usually several)
deep derivation chains by construction, rather than discovering them by luck.

Usage:
    python3 nora_backward_sampler.py 8 --seed 42 --verbose --output graph.lp
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
FEMALE_NAMES = ["alice","brenda","clara","diana","emma","fiona","greta",
                "hannah","iris","julia","karen","laura","maria","nora",
                "olivia","paula","rosa","sarah","tina","vera"]
MALE_NAMES = ["adam","bob","carl","david","eric","frank","george","henry",
              "ivan","james","kevin","leo","mark","nick","oscar","paul",
              "ray","sam","tom","victor"]
PLACE_NAMES = ["london","paris","rome","berlin","madrid","tokyo","oslo",
               "cairo","lima","delhi"]

# ═══════════════════════════════════════════════════════════════════════════
# ASP ENGINE (identical to reference)
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
            ht = ht.strip(); ic = ht.startswith('{')
            if ic: ht = ht[1:]
            if '}' in ht: ht = ht[:ht.rindex('}')]
            hatoms = [_parse_atom(a.strip()) for a in _split_parens(ht)]
            hatoms = [a for a in hatoms if a]
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
                idx_map = collections.defaultdict(list)
                for f in fp: idx_map[tuple(f[i] for i, _ in bp)].append(f)
                for f in idx_map.get(tuple(b[v] for _, v in bp), []):
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
    strata = {}
    for r in asp_rules:
        for a in (r.head or []): strata.setdefault(a.pred, 0)
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
                    bd = [(b,d) for b,d in bd if _resolve(b, iq.ineq_left) != _resolve(b, iq.ineq_right)]
                for neg in r.negative_body:
                    bd = [(b,d) for b,d in bd
                          if not has_fact(db, neg.atom.pred, tuple(_resolve(b, a) for a in neg.atom.args))]
                for b, md in bd:
                    for ha in r.head:
                        g = tuple(_resolve(b, a) for a in ha.args)
                        if all(not _is_var(x) for x in g):
                            nd = md + 1; key = (ha.pred, g)
                            if add_fact(db, ha.pred, g): changed = True; depth_map[key] = nd
                            elif key in depth_map and nd < depth_map[key]: depth_map[key] = nd
            if not changed: break
    return db, depth_map

def check_constraints(db, asp_rules):
    for r in asp_rules:
        if not r.is_constraint: continue
        dummy = ASPRule(head=[Atom("__c__", ("x","x"))], body=r.body, index=999)
        if _eval_rule(dummy, db): return True
    return False


# ═══════════════════════════════════════════════════════════════════════════
# HAND-CRAFTED RECIPES — each is a "proof skeleton" that guarantees
# a specific deep derivation chain exists in the final graph.
#
# A recipe is a function: (name_alloc) -> (facts: FactDB, persons: dict,
#   target_description: str, num_persons: int)
#
# Recipes are composable: they can share persons via name remapping.
# ═══════════════════════════════════════════════════════════════════════════

class NameAllocator:
    """Allocates fresh person names from the global pools."""
    def __init__(self, rng: random.Random):
        self.rng = rng
        self._fi = rng.randint(0, len(FEMALE_NAMES) - 1)
        self._mi = rng.randint(0, len(MALE_NAMES) - 1)
        self.persons: Dict[str, str] = {}  # name -> gender
        self.generations: Dict[str, int] = {}

    def alloc(self, gender, gen=0):
        if gender == 'F':
            name = FEMALE_NAMES[self._fi % len(FEMALE_NAMES)]
            self._fi += 1
        else:
            name = MALE_NAMES[self._mi % len(MALE_NAMES)]
            self._mi += 1
        self.persons[name] = gender
        self.generations[name] = gen
        return name

    def count(self):
        return len(self.persons)


@dataclass
class Recipe:
    """A proof skeleton: base facts that guarantee a deep derivation."""
    name: str               # human description
    facts: FactDB           # base facts to emit
    persons: Dict[str, str] # name -> gender
    generations: Dict[str, int]
    underage: Set[str]
    marriages: List[Tuple[str, str]]  # for social layer
    parent_child: List[Tuple[str, str]]
    num_persons: int
    target_pred: str        # what deep predicate this enables
    min_depth: int          # estimated derivation depth


def recipe_paternal_grandmother(na: NameAllocator) -> Recipe:
    """
    Target: paternal_grandmother_of(GM, GC)
    Chain: father_of(F,GC) -> parent_of(F,GC) [depth 1]
           parent_of(GM,F) [base] + parent_of(F,GC) -> grandparent_of(GM,GC) [depth 2]
           is_female(GM) + grandparent_of(GM,GC) -> grandmother_of(GM,GC) [depth 3]
           father_of(F,GC) -> paternal line -> paternal_grandparent_of(GM,GC) [depth 3]
           paternal_grandparent_of + is_female -> paternal_grandmother_of [depth 4]
    With hidden gender: deeper chain to infer is_female(GM).
    """
    db = new_db()
    gf = na.alloc('M', 0)   # grandfather
    gm = na.alloc('F', 0)   # grandmother
    f  = na.alloc('M', 1)   # father
    gc = na.alloc('M', 2)   # grandchild

    # State facts indirectly: child_of instead of parent_of, no explicit gender
    add_fact(db, "child_of", (f, gf))
    add_fact(db, "child_of", (f, gm))
    add_fact(db, "child_of", (gc, f))
    # Reveal gender via marriage (husband_of -> is_male for gf)
    add_fact(db, "spouse_of", (gf, gm))
    # GM's gender must be INFERRED: spouse_of(gf,gm) + is_male(gf) -> gm is female
    # But we don't even state is_male(gf)! We use father_of for one link:
    # Actually let's hide everything maximally:
    # State son_of(gc, f) to reveal gc is male, f must be inferred
    add_fact(db, "son_of", (gc, f))
    add_fact(db, "is_underage", (gc, gc))

    return Recipe(
        name="paternal_grandmother chain",
        facts=db,
        persons={gf: 'M', gm: 'F', f: 'M', gc: 'M'},
        generations={gf: 0, gm: 0, f: 1, gc: 2},
        underage={gc},
        marriages=[(gf, gm)],
        parent_child=[(gf, f), (gm, f), (f, gc)],
        num_persons=4,
        target_pred="paternal_grandmother_of",
        min_depth=4,
    )


def recipe_maternal_uncle_via_no_sons(na: NameAllocator) -> Recipe:
    """
    Target: maternal_uncle_of(U, GC) derived through:
      mother_of(M, GC) + sibling_of(U, M) -> maternal_aunt_or_uncle_of(U, GC)
      is_male(U) -> maternal_uncle_of(U, GC)

    Extra depth: M's gender inferred via no_sons on grandparent.
    GP + GM have ONLY daughters -> no_sons(GP) -> parent_of(GP, M) + no_sons(GP)
      -> is_female(M) via rule 58 -> mother_of(M, GC).
    U is male (stated). Sibling relationship via shared parents.

    This requires the no_sons -> is_female cascade (depth ~5-6).
    """
    db = new_db()
    gp = na.alloc('M', 0)
    gm = na.alloc('F', 0)
    m  = na.alloc('F', 1)   # mother (gender NOT stated, inferred)
    u  = na.alloc('M', 1)   # uncle

    # Wait — uncle is male, so GP has both a son and a daughter,
    # which breaks no_sons. We need ALL children same gender for the cascade.
    # Instead: GP+GM have only FEMALE children (m + sister).
    # Uncle is the SPOUSE's brother, i.e. paternal uncle.
    # Let's restructure:
    #
    # GP+GM -> daughter1(=wife), daughter2
    # no_sons(GP) -> is_female for all children
    # wife marries husband -> husband's brother = uncle to child
    #
    # Actually simpler: use the maternal line directly.
    # GP+GM -> m + sister (both female, inferred via no_sons)
    # m has child GC
    # sister is the aunt. But we want uncle...
    #
    # New approach: husband's family.
    # GP_h + GM_h -> husband + uncle (both male)
    # no_daughters(GP_h) -> all children male
    # husband marries wife -> child GC
    # uncle_of(uncle, GC) via sibling_of(uncle, husband) + parent_of(husband, GC)
    # paternal_uncle via father_of(husband, GC)

    # Reset — let's use a clean allocation
    # Actually we already allocated 4 names. Let's just redefine the roles:
    # gp = grandfather on father's side
    # gm = grandmother on father's side
    # m = actually the father (oops naming). Let's just use them as variables.
    father = m   # reuse slot, but gender is 'F' in alloc... 
    # This is getting messy. Let me restart cleanly.

    # We already allocated 4 names. Let's work with what we have and
    # allocate more if needed.
    father = na.alloc('M', 1)
    uncle  = u  # already allocated as male
    gc     = na.alloc('M', 2)

    # gp + gm -> father + uncle (both male) -> no_daughters cascade
    # father marries m (who becomes wife/mother)
    # father + m -> gc

    add_fact(db, "child_of", (father, gp))
    add_fact(db, "child_of", (father, gm))
    add_fact(db, "child_of", (uncle, gp))
    add_fact(db, "child_of", (uncle, gm))
    add_fact(db, "spouse_of", (gp, gm))
    add_fact(db, "spouse_of", (father, m))  # m is the wife
    add_fact(db, "child_of", (gc, father))
    add_fact(db, "child_of", (gc, m))
    # Only gender hint: husband_of for gp (reveals gp is male)
    add_fact(db, "husband_of", (gp, gm))
    add_fact(db, "is_underage", (gc, gc))

    persons = {gp: 'M', gm: 'F', m: 'F', u: 'M', father: 'M', gc: 'M'}
    generations = {gp: 0, gm: 0, m: 1, u: 1, father: 1, gc: 2}

    return Recipe(
        name="paternal_uncle via no_daughters cascade",
        facts=db,
        persons=persons,
        generations=generations,
        underage={gc},
        marriages=[(gp, gm), (father, m)],
        parent_child=[(gp, father), (gm, father), (gp, uncle),
                      (gm, uncle), (father, gc), (m, gc)],
        num_persons=len(persons),
        target_pred="paternal_uncle_of",
        min_depth=5,
    )


def recipe_nephew_via_grandson(na: NameAllocator) -> Recipe:
    """
    Target: nephew_of(GS, aunt) via rule 87:
      nephew_of(Y,Z) :- grandson_of(Y,X), parent_of(X,Z), no_sons(Z,Z).
    
    This requires:
    - GP+GM -> son + daughter(=aunt, with no_sons on aunt... 
      but aunt has no children, so no_sons doesn't apply via rule 68/69)
    
    Actually rule 87: nephew_of(Y,Z):- grandson_of(Y,X), parent_of(X,Z), no_sons(Z,Z).
    So Z must have no_sons. Z is an aunt/uncle figure.
    GP = X. parent_of(GP, Z). grandson_of(Y, GP).
    Z has no sons — Z has only daughters or no children.
    
    Build: GP+GM -> son + Z(female, has only daughters or no children)
    son -> grandson(male)
    Then nephew_of(grandson, Z) fires.
    
    For no_sons(Z,Z) we need Z to be a parent with only female children,
    or use spouse propagation. Simplest: Z is female, married, spouse has
    no sons either. Or: Z has one daughter.
    """
    db = new_db()
    gp = na.alloc('M', 0)
    gm = na.alloc('F', 0)
    son = na.alloc('M', 1)
    aunt = na.alloc('F', 1)  # Z in the rule
    gs = na.alloc('M', 2)    # grandson = Y
    aunt_daughter = na.alloc('F', 2)  # aunt's only child (female -> no_sons)

    # aunt married to someone
    aunt_husband = na.alloc('M', 1)

    add_fact(db, "child_of", (son, gp))
    add_fact(db, "child_of", (son, gm))
    add_fact(db, "child_of", (aunt, gp))
    add_fact(db, "child_of", (aunt, gm))
    add_fact(db, "spouse_of", (gp, gm))
    add_fact(db, "child_of", (gs, son))
    # aunt's family: aunt + husband -> daughter only
    add_fact(db, "spouse_of", (aunt_husband, aunt))
    add_fact(db, "daughter_of", (aunt_daughter, aunt))
    add_fact(db, "daughter_of", (aunt_daughter, aunt_husband))
    # Gender hints: minimal
    add_fact(db, "husband_of", (gp, gm))
    # gs gender via son_of
    add_fact(db, "son_of", (gs, son))
    add_fact(db, "is_underage", (gs, gs))
    add_fact(db, "is_underage", (aunt_daughter, aunt_daughter))

    persons = {gp: 'M', gm: 'F', son: 'M', aunt: 'F', gs: 'M',
               aunt_daughter: 'F', aunt_husband: 'M'}
    generations = {gp: 0, gm: 0, son: 1, aunt: 1, gs: 2,
                   aunt_daughter: 2, aunt_husband: 1}

    return Recipe(
        name="nephew via grandson + no_sons",
        facts=db,
        persons=persons,
        generations=generations,
        underage={gs, aunt_daughter},
        marriages=[(gp, gm), (aunt_husband, aunt)],
        parent_child=[(gp, son), (gm, son), (gp, aunt), (gm, aunt),
                      (son, gs), (aunt, aunt_daughter), (aunt_husband, aunt_daughter)],
        num_persons=len(persons),
        target_pred="nephew_of",
        min_depth=6,
    )


def recipe_gender_from_no_brothers(na: NameAllocator) -> Recipe:
    """
    Target: is_female(Y) inferred via:
      sibling_of(X,Y), no_brothers(X,X) -> is_female(Y,Y)  [rule 56]
      no_brothers(X,X) <- parent_of(P,X), no_sons(P,P)     [rule 70]
      no_sons(P,P) <- parent_of(P,C), is_female(C,C), no_brothers(C,C) [rule 69]
    
    Build: P has only female children (C1, C2).
    State is_female for C1 only. C2's gender inferred via cascade.
    """
    db = new_db()
    p_m = na.alloc('M', 0)
    p_f = na.alloc('F', 0)
    c1 = na.alloc('F', 1)
    c2 = na.alloc('F', 1)

    add_fact(db, "child_of", (c1, p_m))
    add_fact(db, "child_of", (c1, p_f))
    add_fact(db, "child_of", (c2, p_m))
    add_fact(db, "child_of", (c2, p_f))
    add_fact(db, "spouse_of", (p_m, p_f))
    # Only reveal c1's gender
    add_fact(db, "wife_of", (p_f, p_m))  # reveals p_f is female
    add_fact(db, "daughter_of", (c1, p_m))  # reveals c1 is female

    persons = {p_m: 'M', p_f: 'F', c1: 'F', c2: 'F'}
    generations = {p_m: 0, p_f: 0, c1: 1, c2: 1}

    return Recipe(
        name="gender inference via no_brothers cascade",
        facts=db,
        persons=persons,
        generations=generations,
        underage=set(),
        marriages=[(p_m, p_f)],
        parent_child=[(p_m, c1), (p_f, c1), (p_m, c2), (p_f, c2)],
        num_persons=4,
        target_pred="is_female (inferred)",
        min_depth=4,
    )


def recipe_sibling_in_law_chain(na: NameAllocator) -> Recipe:
    """
    Target: sibling_in_law_of(SIL, person) via:
      sibling_of(Z, person), spouse_of(SIL, Z) -> sibling_in_law_of(SIL, person)
    
    Plus brother/sister_in_law via gender.
    Build two families, cross-marry.
    """
    db = new_db()
    # Family A: pa + ma -> son_a + daughter_a
    pa = na.alloc('M', 0)
    ma = na.alloc('F', 0)
    son_a = na.alloc('M', 1)
    daughter_a = na.alloc('F', 1)
    # Family B: pb + mb -> son_b
    pb = na.alloc('M', 0)
    mb = na.alloc('F', 0)
    son_b = na.alloc('M', 1)

    # Cross marriage: son_b marries daughter_a
    # -> son_b is sibling_in_law_of son_a (and vice versa)
    # -> pb, mb become parent_in_law_of daughter_a

    add_fact(db, "child_of", (son_a, pa))
    add_fact(db, "child_of", (son_a, ma))
    add_fact(db, "child_of", (daughter_a, pa))
    add_fact(db, "child_of", (daughter_a, ma))
    add_fact(db, "child_of", (son_b, pb))
    add_fact(db, "child_of", (son_b, mb))
    add_fact(db, "spouse_of", (pa, ma))
    add_fact(db, "spouse_of", (pb, mb))
    add_fact(db, "spouse_of", (son_b, daughter_a))
    # Minimal gender: only husband_of for pa
    add_fact(db, "husband_of", (pa, ma))

    persons = {pa: 'M', ma: 'F', son_a: 'M', daughter_a: 'F',
               pb: 'M', mb: 'F', son_b: 'M'}
    generations = {pa: 0, ma: 0, son_a: 1, daughter_a: 1,
                   pb: 0, mb: 0, son_b: 1}

    return Recipe(
        name="sibling_in_law + parent_in_law via cross-marriage",
        facts=db,
        persons=persons,
        generations=generations,
        underage=set(),
        marriages=[(pa, ma), (pb, mb), (son_b, daughter_a)],
        parent_child=[(pa, son_a), (ma, son_a), (pa, daughter_a),
                      (ma, daughter_a), (pb, son_b), (mb, son_b)],
        num_persons=7,
        target_pred="sibling_in_law_of",
        min_depth=5,
    )


def recipe_living_in_chain(na: NameAllocator) -> Recipe:
    """
    Target: living_in(child, place) inferred via:
      is_underage(child) + parent_of(P, child) -> living_in_same_place(P, child)
      living_in(P, place) + living_in_same_place(P, child) -> living_in(child, place)
    
    Chain further with school_mates and colleagues.
    """
    db = new_db()
    p1 = na.alloc('M', 0)
    p2 = na.alloc('F', 0)
    c1 = na.alloc('M', 1)
    c2 = na.alloc('F', 1)

    add_fact(db, "parent_of", (p1, c1))
    add_fact(db, "parent_of", (p2, c1))
    add_fact(db, "parent_of", (p1, c2))
    add_fact(db, "parent_of", (p2, c2))
    add_fact(db, "spouse_of", (p1, p2))
    add_fact(db, "is_underage", (c1, c1))
    add_fact(db, "is_underage", (c2, c2))
    add_fact(db, "living_in", (p1, "london"))
    add_fact(db, "school_mates_with", (c1, c2))

    persons = {p1: 'M', p2: 'F', c1: 'M', c2: 'F'}
    generations = {p1: 0, p2: 0, c1: 1, c2: 1}

    return Recipe(
        name="living_in chain via underage + school_mates",
        facts=db,
        persons=persons,
        generations=generations,
        underage={c1, c2},
        marriages=[(p1, p2)],
        parent_child=[(p1, c1), (p2, c1), (p1, c2), (p2, c2)],
        num_persons=4,
        target_pred="living_in (inferred)",
        min_depth=3,
    )


def recipe_maternal_grandmother_by_exclusion(na: NameAllocator) -> Recipe:
    """
    Target: maternal_grandmother_of via rules 113-114:
      maternal_grandmother_of(V,X) :- paternal_grandmother_of(U,X),
                                       grandmother_of(V,X), U != V.
    
    Build: child X has two grandmothers. One is paternal (stated indirectly).
    The other is then inferred as maternal by exclusion.
    
    Family A: gpa(M) + gma(F) -> father(M)
    Family B: gpb(M) + gmb(F) -> mother(F)  
    father + mother -> child
    
    State paternal_grandfather_of(gpa, child) or enough to derive it.
    Then grandmother gmb is inferred as maternal by exclusion.
    """
    db = new_db()
    gpa = na.alloc('M', 0)
    gma = na.alloc('F', 0)
    gpb = na.alloc('M', 0)
    gmb = na.alloc('F', 0)
    father = na.alloc('M', 1)
    mother = na.alloc('F', 1)
    child = na.alloc('M', 2)

    # Paternal side
    add_fact(db, "father_of", (gpa, father))
    add_fact(db, "child_of", (father, gma))
    add_fact(db, "spouse_of", (gpa, gma))
    # Maternal side — hide as much as possible
    add_fact(db, "child_of", (mother, gpb))
    add_fact(db, "child_of", (mother, gmb))
    add_fact(db, "spouse_of", (gpb, gmb))
    # Child
    add_fact(db, "child_of", (child, father))
    add_fact(db, "child_of", (child, mother))
    add_fact(db, "spouse_of", (father, mother))
    # Minimal gender hints
    add_fact(db, "husband_of", (gpb, gmb))
    add_fact(db, "is_underage", (child, child))

    persons = {gpa: 'M', gma: 'F', gpb: 'M', gmb: 'F',
               father: 'M', mother: 'F', child: 'M'}
    generations = {gpa: 0, gma: 0, gpb: 0, gmb: 0,
                   father: 1, mother: 1, child: 2}

    return Recipe(
        name="maternal_grandmother by exclusion (rule 113-114)",
        facts=db,
        persons=persons,
        generations=generations,
        underage={child},
        marriages=[(gpa, gma), (gpb, gmb), (father, mother)],
        parent_child=[(gpa, father), (gma, father), (gpb, mother),
                      (gmb, mother), (father, child), (mother, child)],
        num_persons=7,
        target_pred="maternal_grandmother_of",
        min_depth=6,
    )


# All available recipes, sorted by person count
ALL_RECIPES = [
    recipe_paternal_grandmother,        # 4 persons, depth 4
    recipe_gender_from_no_brothers,     # 4 persons, depth 4
    recipe_living_in_chain,             # 4 persons, depth 3
    recipe_maternal_uncle_via_no_sons,  # 6 persons, depth 5
    recipe_nephew_via_grandson,         # 7 persons, depth 6
    recipe_sibling_in_law_chain,        # 7 persons, depth 5
    recipe_maternal_grandmother_by_exclusion,  # 7 persons, depth 6
]


# ═══════════════════════════════════════════════════════════════════════════
# RECIPE COMPOSER — selects and merges recipes to hit vertex target
# ═══════════════════════════════════════════════════════════════════════════

def compose_recipes(target_n: int, asp_rules: list,
                    rng: random.Random, verbose: bool = False
                    ) -> Tuple[Optional[FactDB], dict]:
    """
    Try many recipe combinations, validate each, keep the best.
    Uses a knapsack-like greedy approach: pick recipes that fit the
    remaining vertex budget, preferring deeper chains.
    """
    best_db = None
    best_score = -1
    best_details = {}

    # Generate multiple candidate compositions
    for attempt in range(40):
        na = NameAllocator(random.Random(rng.randint(0, 2**31)))
        db = new_db()
        used_recipes = []
        # Reserve slots for places added by _add_social (always 2: london, paris)
        remaining = max(3, target_n - 2)

        # Shuffle recipe order for diversity
        order = list(range(len(ALL_RECIPES)))
        rng.shuffle(order)

        # Sort by depth (prefer deeper), but with shuffled tiebreak
        order.sort(key=lambda i: ALL_RECIPES[i].__doc__.count('depth') if ALL_RECIPES[i].__doc__ else 0,
                   reverse=True)

        for idx in order:
            recipe_fn = ALL_RECIPES[idx]
            # Peek at how many persons this recipe needs
            test_na = NameAllocator(random.Random(rng.randint(0, 2**31)))
            try:
                r = recipe_fn(test_na)
            except Exception:
                continue

            if r.num_persons > remaining:
                continue

            # Actually build it with our real allocator
            try:
                r = recipe_fn(na)
            except Exception:
                continue

            # Merge facts
            for pred, facts in r.facts.items():
                for args in facts:
                    add_fact(db, pred, args)

            used_recipes.append(r)
            remaining -= r.num_persons

            if remaining <= 0:
                break

        # If we have leftover budget, add filler persons connected to existing
        if remaining > 0 and used_recipes:
            last = used_recipes[-1]
            # Add children to an existing couple
            couples = last.marriages
            if couples:
                parent_m, parent_f = couples[0]
                for _ in range(remaining):
                    g = rng.choice(['M', 'F'])
                    ch = na.alloc(g, 2)
                    add_fact(db, "child_of", (ch, parent_m))
                    add_fact(db, "child_of", (ch, parent_f))
                    if g == 'M':
                        add_fact(db, "son_of", (ch, parent_m))
                    else:
                        add_fact(db, "daughter_of", (ch, parent_f))
                    add_fact(db, "is_underage", (ch, ch))
                    remaining -= 1
            else:
                for _ in range(remaining):
                    g = rng.choice(['M', 'F'])
                    na.alloc(g, 0)
                    remaining -= 1

        # Add social layer
        _add_social(db, na, rng)

        # Validate
        derived, depth_map = forward_chain(db, asp_rules)
        violated = check_constraints(derived, asp_rules)
        if violated:
            if verbose:
                print(f"  attempt {attempt+1}: VIOLATED "
                      f"(recipes: {[r.name for r in used_recipes]})",
                      file=sys.stderr)
            continue

        # Score
        depth_vals = [d for d in depth_map.values() if d > 0]
        if not depth_vals:
            continue

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

        if verbose:
            print(f"  attempt {attempt+1}: score={score:.0f} maxD={max_d} "
                  f"derived={len(depth_vals)} base={base_count} "
                  f"recipes={[r.name for r in used_recipes]}",
                  file=sys.stderr)

        if score > best_score:
            best_score = score
            best_db = db
            best_details = {
                "score": round(score, 1),
                "max_depth": max_d,
                "avg_depth": round(avg_d, 2),
                "deep3": deep3,
                "deep5": deep5,
                "derived": len(depth_vals),
                "base": base_count,
                "amplification": round(amp, 2),
                "strategy": "backward_chaining",
                "recipes": "+".join(r.name for r in used_recipes),
            }

    return best_db, best_details


def _add_social(db: FactDB, na: NameAllocator, rng: random.Random):
    """Add living_in, colleagues, school_mates for persons in the allocator."""
    places = ["london", "paris"]
    adults = [n for n, g in na.persons.items()
              if not has_fact(db, "is_underage", (n, n))]
    minors = [n for n, g in na.persons.items()
              if has_fact(db, "is_underage", (n, n))]

    for a in adults:
        if not has_fact(db, "living_in", (a, "london")) and \
           not has_fact(db, "living_in", (a, "paris")):
            add_fact(db, "living_in", (a, rng.choice(places)))

    # Colleagues: two adults in the same place
    place_groups = collections.defaultdict(list)
    for a in adults:
        for place in places:
            if has_fact(db, "living_in", (a, place)):
                place_groups[place].append(a)
    for place, people in place_groups.items():
        if len(people) >= 2:
            if not has_fact(db, "colleague_of", (people[0], people[1])):
                add_fact(db, "colleague_of", (people[0], people[1]))
            break

    # School mates: two minors
    if len(minors) >= 2:
        if not has_fact(db, "school_mates_with", (minors[0], minors[1])):
            add_fact(db, "school_mates_with", (minors[0], minors[1]))


# ═══════════════════════════════════════════════════════════════════════════
# OBFUSCATION PASS — rewrite facts to hide information further
# ═══════════════════════════════════════════════════════════════════════════

def obfuscate_db(db: FactDB, rng: random.Random) -> FactDB:
    """Post-process: randomly swap predicate directions and remove
    redundant gender hints to increase difficulty."""
    out = new_db()

    for pred, facts in db.items():
        for args in facts:
            # Keep social/underage facts as-is
            if pred in ("living_in", "colleague_of", "school_mates_with",
                        "is_underage", "is_place", "is_person"):
                add_fact(out, pred, args)
                continue

            # Randomly replace some parent_of with child_of and vice versa
            if pred == "parent_of" and rng.random() < 0.4:
                add_fact(out, "child_of", (args[1], args[0]))
            elif pred == "child_of" and rng.random() < 0.3:
                add_fact(out, "parent_of", (args[1], args[0]))
            else:
                add_fact(out, pred, args)

    return out


# ═══════════════════════════════════════════════════════════════════════════
# OUTPUT (identical format)
# ═══════════════════════════════════════════════════════════════════════════

def format_asp(db: FactDB) -> str:
    lines = ["% === BASE FACTS (nora backward sampler) ===", ""]
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
        description="Nora backward-chaining goal-driven sampler — "
                    "constructs graphs by working backwards from deep "
                    "derivation targets")
    parser.add_argument("num_vertices", type=int,
                        help="Number of person vertices in the graph")
    parser.add_argument("--rules", "-r", type=str, default=None,
                        help="ASP rules file (.lp)")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--output", "-o", type=str, default=None)
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--viz", type=str, default=None)
    args = parser.parse_args()

    rng = random.Random(args.seed)

    rules_path = args.rules
    if rules_path is None:
        for candidate in [
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "NoRa.lp"),
            "NoRa.lp",
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "nora_rules.lp"),
            "nora_rules.lp",
        ]:
            if os.path.exists(candidate):
                rules_path = candidate; break
    if rules_path is None or not os.path.exists(rules_path):
        print("ERROR: rules file not found. Use --rules <path>", file=sys.stderr)
        sys.exit(1)

    if args.verbose:
        print(f"Nora backward sampler: {args.num_vertices} vertices, "
              f"rules={rules_path}", file=sys.stderr)

    with open(rules_path) as f:
        asp_rules = parse_asp_program(f.read())
    if args.verbose:
        print(f"  Parsed {len(asp_rules)} rules", file=sys.stderr)

    best_db, details = compose_recipes(
        args.num_vertices, asp_rules, rng, verbose=args.verbose)

    if best_db is None:
        print("ERROR: no valid graph found", file=sys.stderr)
        sys.exit(1)

    if args.verbose:
        print(f"\n=== BEST ===", file=sys.stderr)
        for k, v in sorted(details.items()):
            print(f"  {k}: {v}", file=sys.stderr)

    report = [
        "% ═══════════════════════════════════════════",
        "% NORA BACKWARD-CHAINING GOAL-DRIVEN SAMPLER",
        "% ═══════════════════════════════════════════",
    ]
    for k, v in sorted(details.items()):
        report.append(f"% {k}: {v}")

    output = "\n".join(report) + "\n\n" + format_asp(best_db)

    if args.output:
        with open(args.output, "w") as f: f.write(output)
        if args.verbose:
            print(f"Written to {args.output}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
