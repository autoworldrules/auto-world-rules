#!/usr/bin/env python3
"""
General ASP Graph Sampler v2
=============================
Improved sampler addressing key weaknesses of v1:

1. PROVENANCE-AWARE SCORING — directly measures proof depth distribution,
   not just derived fact count. Optimizes for DEEP derivations.
2. FACT MINIMIZATION — penalizes bloated base fact sets; fewer stated facts
   = more inference work = harder queries.
3. SYMMETRY DETECTION — identifies symmetric rules (r(Y,X) :- r(X,Y)) and
   avoids generating both orientations as base facts.
4. BETTER TYPE INFERENCE — role-based merging preserves meaningful type
   distinctions while avoiding over-fragmentation.
5. RULE-PATTERN MOTIFS — analyzes rule join patterns to generate targeted
   connected subgraphs that trigger multi-step chains.
6. CONSTRAINT PRE-SCREENING — avoids generating facts in constraint-
   conflicting predicates.
7. DERIVABILITY-MAXIMIZING REMOVAL — during hill climbing, tries removing
   facts that can instead be derived (increases inference work).

Usage:
    python3 general_sampler_v2.py rules.lp <num_vertices> [options]
"""

import argparse
import collections
import copy
import itertools
import math
import random
import re
import sys
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

# ═══════════════════════════════════════════════════════════════════════════
# 1.  DATA STRUCTURES  (unchanged from v1)
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class Atom:
    pred: str; args: Tuple[str, ...]
    def __hash__(self): return hash((self.pred, self.args))
    def __eq__(self, other): return self.pred == other.pred and self.args == other.args
    def __repr__(self): return f"{self.pred}({','.join(self.args)})"

@dataclass
class Literal:
    atom: Optional[Atom] = None; negated: bool = False
    ineq_left: Optional[str] = None; ineq_right: Optional[str] = None
    @property
    def is_inequality(self): return self.ineq_left is not None

@dataclass
class Rule:
    head: List[Atom]; body: List[Literal]
    is_choice: bool = False; is_constraint: bool = False; index: int = 0
    @property
    def is_fact(self): return not self.body and len(self.head) == 1 and not self.is_choice
    @property
    def positive_body(self): return [l for l in self.body if l.atom and not l.negated]
    @property
    def negative_body(self): return [l for l in self.body if l.atom and l.negated]
    @property
    def inequalities(self): return [l for l in self.body if l.is_inequality]

FactDB = Dict[str, Set[Tuple[str, ...]]]
def new_db() -> FactDB: return collections.defaultdict(set)
def copy_db(db):
    out = collections.defaultdict(set)
    for k, v in db.items(): out[k] = set(v)
    return out
def add_fact(db, pred, args):
    s = db[pred]
    if args in s: return False
    s.add(args); return True
def has_fact(db, pred, args): return args in db.get(pred, set())
def db_size(db): return sum(len(v) for v in db.values())

# ═══════════════════════════════════════════════════════════════════════════
# 2.  PARSER  (unchanged)
# ═══════════════════════════════════════════════════════════════════════════

def is_variable(s): return bool(s) and s[0].isupper()

def split_outside_parens(text, sep=','):
    parts, depth, cur = [], 0, []
    for ch in text:
        if ch == '(': depth += 1
        elif ch == ')': depth -= 1
        elif ch == sep and depth == 0: parts.append(''.join(cur).strip()); cur = []; continue
        cur.append(ch)
    t = ''.join(cur).strip()
    if t: parts.append(t)
    return parts

def parse_atom(text):
    text = text.strip()
    if not text: return None
    if '(' not in text:
        if re.match(r'^[a-z_]\w*$', text): return Atom(pred=text, args=(text, text))
        return None
    m = re.match(r'^([a-z_]\w*)\((.+)\)$', text, re.DOTALL)
    if not m: return None
    args = [a.strip() for a in split_outside_parens(m.group(2))]
    if len(args) == 1: args = [args[0], args[0]]
    return Atom(pred=m.group(1), args=tuple(args))

def parse_body(text):
    parts = split_outside_parens(text); lits = []
    for p in parts:
        p = p.strip()
        if not p: continue
        for op in ['!=', '\\=']:
            if op in p:
                sides = p.split(op, 1)
                lits.append(Literal(ineq_left=sides[0].strip(), ineq_right=sides[1].strip())); break
        else:
            neg = p.startswith('not ')
            if neg: p = p[4:].strip()
            a = parse_atom(p)
            if a: lits.append(Literal(atom=a, negated=neg))
    return lits

def parse_head(text):
    text = text.strip(); ic = text.startswith('{')
    if ic: text = text[1:]
    if '}' in text: text = text[:text.rindex('}')]
    atoms = [parse_atom(a.strip()) for a in split_outside_parens(text)]
    return [a for a in atoms if a], ic

def parse_program(text):
    lines = text.split('\n')
    cleaned = [l[:l.find('%')] if '%' in l else l for l in lines]
    text = ' '.join(cleaned); rules = []; facts = []; idx = 0
    rules = []; facts = []
    for part in text.split('.'):
        part = part.strip()
        if not part: continue
        if part.startswith(':-'):
            rules.append(Rule(head=[], body=parse_body(part[2:].strip()), is_constraint=True, index=idx)); idx += 1
        elif ':-' in part:
            ht, bt = part.split(':-', 1); atoms, ic = parse_head(ht.strip())
            rules.append(Rule(head=atoms, body=parse_body(bt.strip()), is_choice=ic, index=idx)); idx += 1
        else:
            a = parse_atom(part)
            if a: facts.append(Rule(head=[a], body=[], index=idx)); idx += 1
    return rules, facts

# ═══════════════════════════════════════════════════════════════════════════
# 3.  IMPROVED RULE ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════

class UnionFind:
    def __init__(self): self.parent = {}
    def find(self, x):
        if x not in self.parent: self.parent[x] = x
        if self.parent[x] != x: self.parent[x] = self.find(self.parent[x])
        return self.parent[x]
    def union(self, x, y):
        px, py = self.find(x), self.find(y)
        if px != py: self.parent[px] = py
    def classes(self):
        groups = collections.defaultdict(set)
        for k in self.parent: groups[self.find(k)].add(k)
        return dict(groups)

@dataclass
class RuleAnalysis:
    base_preds: Set[str]
    derived_preds: Set[str]
    pure_base: Set[str]           # in body, never in head
    seedable: Set[str]            # usable as base facts (includes pure_base)
    pred_arity: Dict[str, int]
    slot_to_class: Dict[Tuple, int]
    type_classes: Dict[int, Set]
    strata: Dict[str, int]
    dep_graph: Dict[str, Set[str]]
    neg_dep_graph: Dict[str, Set[str]]
    symmetric_preds: Set[str]
    constraint_preds: Set[str]
    join_patterns: List[Tuple]
    rule_constants: Set[str]      # ground constants from rule facts (e.g. senior, junior)
    rc_slots: Set[Tuple]          # (pred, arg_index) slots that must use rule_constants
    self_ref: Set[str] = field(default_factory=set)  # binary preds always used as p(X,X)


def analyze_rules(rules, facts):
    pred_arity = {}; head_preds = set(); body_preds = set()
    for r in rules:
        for a in r.head: head_preds.add(a.pred); pred_arity[a.pred] = len(a.args)
        for l in r.body:
            if l.atom: body_preds.add(l.atom.pred); pred_arity[l.atom.pred] = len(l.atom.args)
    for f in facts: pred_arity[f.head[0].pred] = len(f.head[0].args)
    fact_preds = {f.head[0].pred for f in facts}

    base_preds = body_preds | fact_preds
    derived_preds = head_preds
    pure_base = base_preds - derived_preds

    # Detect predicates that are "symmetric base": they appear in head_preds
    # ONLY because of symmetry rules like p(Y,X) :- p(X,Y). These are
    # really base facts and should be seedable.
    symmetric_base = set()
    for p in (body_preds & head_preds):
        rules_for_p = [r for r in rules if not r.is_constraint and r.head
                        and r.head[0].pred == p]
        if not rules_for_p: continue
        all_sym = True
        for r in rules_for_p:
            pb = r.positive_body
            if (len(pb) != 1 or not pb[0].atom or pb[0].atom.pred != p
                    or len(r.head[0].args) != 2 or len(pb[0].atom.args) != 2):
                all_sym = False; break
            if r.head[0].args != (pb[0].atom.args[1], pb[0].atom.args[0]):
                all_sym = False; break
        if all_sym:
            symmetric_base.add(p)

    # ── Seedable: when pure_base is empty, use SCC analysis ──
    if pure_base or symmetric_base:
        seedable = (set(pure_base) | symmetric_base) - fact_preds
    else:
        # Build dep graph for SCC
        dep_raw = collections.defaultdict(set)
        for r in rules:
            if r.is_constraint: continue
            for ha in r.head:
                for l in r.positive_body:
                    if l.atom: dep_raw[ha.pred].add(l.atom.pred)
        # Body fan-out
        fanout = collections.Counter()
        for r in rules:
            if r.is_constraint: continue
            for l in r.positive_body:
                if l.atom: fanout[l.atom.pred] += 1
        # SCC detection
        all_p = set(dep_raw.keys())
        for vs in dep_raw.values(): all_p |= vs
        idx_c = [0]; stack = []; on_stack = set()
        index = {}; lowlink = {}; sccs = []
        old_limit = sys.getrecursionlimit()
        sys.setrecursionlimit(max(5000, len(all_p) * 3))
        def _sc(v):
            index[v] = lowlink[v] = idx_c[0]; idx_c[0] += 1
            stack.append(v); on_stack.add(v)
            for w in dep_raw.get(v, set()):
                if w not in index: _sc(w); lowlink[v] = min(lowlink[v], lowlink[w])
                elif w in on_stack: lowlink[v] = min(lowlink[v], index[w])
            if lowlink[v] == index[v]:
                scc = set()
                while True:
                    w = stack.pop(); on_stack.discard(w); scc.add(w)
                    if w == v: break
                sccs.append(scc)
        for v in all_p:
            if v not in index: _sc(v)
        sys.setrecursionlimit(old_limit)

        # Identify predicates with simple (1-body) derivation rules
        has_simple_rule = set()
        for r in rules:
            if r.is_constraint: continue
            pb = [l for l in r.body if l.atom and not l.negated]
            if len(pb) == 1 and len(r.head) == 1:
                has_simple_rule.add(r.head[0].pred)
                has_simple_rule.add(pb[0].atom.pred)

        # Seedable: only predicates safe to state as base facts
        seedable = set()
        for scc in sccs:
            body_m = [(p, fanout[p]) for p in scc
                      if fanout[p] > 0 and p in has_simple_rule]
            if not body_m: continue
            body_m.sort(key=lambda x: -x[1])
            take = max(2, len(scc) // 8)
            for p, _ in body_m[:take]: seedable.add(p)

        # Filter out closed-world and derived-only predicates
        unsafe_prefixes = ('no_', 'not_')
        unsafe_preds = {'is_person', 'is_place', 'living_in_same_place'}
        seedable = {p for p in seedable
                    if not any(p.startswith(pfx) for pfx in unsafe_prefixes)
                    and p not in unsafe_preds}
        # Exclude predicates fully defined by ground facts in the rules
        seedable -= fact_preds

    # ── Type inference via Union-Find ──
    uf = UnionFind()
    for r in rules:
        var_pos = collections.defaultdict(list)
        for a in list(r.head) + [l.atom for l in r.body if l.atom]:
            for i, arg in enumerate(a.args):
                if is_variable(arg): var_pos[arg].append((a.pred, i))
        for var, positions in var_pos.items():
            for p1, p2 in zip(positions, positions[1:]): uf.union(p1, p2)
    for f in facts:
        a = f.head[0]
        for i in range(len(a.args)): uf.find((a.pred, i))
    for p, ar in pred_arity.items():
        for i in range(ar): uf.find((p, i))

    raw = uf.classes()
    type_classes = {}; slot_to_class = {}
    for cid, (rep, members) in enumerate(raw.items()):
        type_classes[cid] = members
        for m in members: slot_to_class[m] = cid

    # ── Post-process: split places from persons when collapsed ──
    # Detect place-typed slots: predicates like is_place, living_in[1], not_living_in[1]
    place_slots = set()
    for r in rules:
        if r.is_constraint: continue
        for a in r.head:
            if a.pred in ("is_place",):
                for i in range(len(a.args)):
                    place_slots.add((a.pred, i))
        # If head is is_place(Z) :- living_in(X,Z), then living_in[1] is a place slot
        if len(r.head) == 1 and r.head[0].pred == "is_place":
            for l in r.positive_body:
                if l.atom:
                    # Find which arg position maps to the place variable
                    place_var = r.head[0].args[0] if len(r.head[0].args) >= 1 else None
                    if place_var and is_variable(place_var):
                        for i, arg in enumerate(l.atom.args):
                            if arg == place_var:
                                place_slots.add((l.atom.pred, i))

    if place_slots and len(type_classes) <= 2:
        # Split: move place slots to their own class
        place_cid = max(type_classes.keys()) + 1
        moved = set()
        for slot in place_slots:
            if slot in slot_to_class:
                old_cid = slot_to_class[slot]
                if old_cid in type_classes and slot in type_classes[old_cid]:
                    type_classes[old_cid].discard(slot)
                    moved.add(slot)
                    slot_to_class[slot] = place_cid
        if moved:
            type_classes[place_cid] = moved

    # Merge tiny classes (size 1) into largest
    if len(type_classes) > 6:
        largest_cid = max(type_classes, key=lambda c: len(type_classes[c]))
        tiny = [c for c in type_classes if c != largest_cid and len(type_classes[c]) <= 1]
        for tc in tiny:
            type_classes[largest_cid] |= type_classes[tc]
            for slot in type_classes[tc]: slot_to_class[slot] = largest_cid
            del type_classes[tc]

    # ── Dependency graph ──
    dep_graph = collections.defaultdict(set)
    neg_dep_graph = collections.defaultdict(set)
    for r in rules:
        if r.is_constraint: continue
        for ha in r.head:
            for l in r.body:
                if l.atom:
                    (neg_dep_graph if l.negated else dep_graph)[ha.pred].add(l.atom.pred)

    # ── Stratification ──
    strata = {p: 0 for p in base_preds | fact_preds}
    for _ in range(len(pred_arity) + 2):
        ch = False
        for r in rules:
            if r.is_constraint: continue
            for ha in r.head:
                ms = max((strata.get(l.atom.pred, 0) + (1 if l.negated else 0)
                          for l in r.body if l.atom), default=0)
                if ms > strata.get(ha.pred, -1): strata[ha.pred] = ms; ch = True
        if not ch: break

    # ── Symmetry detection ──
    symmetric_preds = set()
    for r in rules:
        if r.is_constraint: continue
        pb = r.positive_body
        if (len(pb) == 1 and len(r.head) == 1
                and pb[0].atom.pred == r.head[0].pred
                and len(r.head[0].args) == 2 and len(pb[0].atom.args) == 2):
            ha, ba = r.head[0].args, pb[0].atom.args
            if ha[0] == ba[1] and ha[1] == ba[0]:
                symmetric_preds.add(r.head[0].pred)

    # ── Constraint predicate detection ──
    constraint_preds = set()
    for r in rules:
        if r.is_constraint:
            for l in r.body:
                if l.atom: constraint_preds.add(l.atom.pred)

    # ── Join pattern extraction (use seedable preds for body matching) ──
    join_patterns = []
    for r in rules:
        if r.is_constraint or r.is_fact: continue
        pb = r.positive_body
        if len(pb) >= 2:
            pattern = []
            for lit in pb:
                if lit.atom and lit.atom.pred in (base_preds | seedable):
                    pattern.append((lit.atom.pred, lit.atom.args))
            if len(pattern) >= 2:
                join_patterns.append((r.index, pattern))

    # ── Rule constant detection ──
    # Ground facts in the rules file (e.g. outranks(senior,junior)) define
    # structural constants that must be preserved. We detect which predicate
    # slots must use these constants via variable-sharing propagation.
    rule_constants = set()
    rc_slots = set()
    for f in facts:
        a = f.head[0]
        for i, arg in enumerate(a.args):
            if not is_variable(arg):
                rc_slots.add((a.pred, i))
                rule_constants.add(arg)

    # Propagate: if a variable V appears in both an rc_slot and another slot,
    # that other slot must also use rule constants.
    for _ in range(10):
        ch2 = False
        for r in rules:
            if r.is_constraint: continue
            var_pos = collections.defaultdict(set)
            all_atoms = list(r.head) + [l.atom for l in r.body if l.atom]
            for a in all_atoms:
                for i, arg in enumerate(a.args):
                    if is_variable(arg):
                        var_pos[arg].add((a.pred, i))
            for var, positions in var_pos.items():
                if any(p in rc_slots for p in positions):
                    for p in positions:
                        if p not in rc_slots:
                            rc_slots.add(p); ch2 = True
        if not ch2: break

    # Self-referential binary predicates (unary semantic: always p(X,X))
    self_ref = set()
    for p, ar in pred_arity.items():
        if ar != 2: continue
        always_same = True; seen = False
        for r in rules:
            for a in list(r.head) + [l.atom for l in r.body if l.atom]:
                if a.pred == p and len(a.args) == 2:
                    seen = True
                    if a.args[0] != a.args[1]:
                        always_same = False; break
            if not always_same: break
        for f in facts:
            a = f.head[0]
            if a.pred == p and len(a.args) == 2 and a.args[0] != a.args[1]:
                always_same = False
        if seen and always_same:
            self_ref.add(p)

    return RuleAnalysis(
        base_preds=base_preds, derived_preds=derived_preds,
        pure_base=pure_base, seedable=seedable,
        pred_arity=pred_arity, slot_to_class=slot_to_class,
        type_classes=type_classes, strata=strata,
        dep_graph=dict(dep_graph), neg_dep_graph=dict(neg_dep_graph),
        symmetric_preds=symmetric_preds, constraint_preds=constraint_preds,
        join_patterns=join_patterns,
        rule_constants=rule_constants, rc_slots=rc_slots,
        self_ref=self_ref)


# ═══════════════════════════════════════════════════════════════════════════
# 4.  FORWARD CHAINER  (with indexed joins + change tracking)
# ═══════════════════════════════════════════════════════════════════════════

def resolve(b, arg): return b.get(arg, arg) if is_variable(arg) else arg

def unify(b, args, fact):
    b2 = dict(b)
    for a, v in zip(args, fact):
        if is_variable(a):
            if a in b2:
                if b2[a] != v: return None
            else: b2[a] = v
        elif a != v: return None
    return b2

def evaluate_rule(rule, db):
    pos = rule.positive_body; neg = rule.negative_body; ineqs = rule.inequalities
    if not pos: return set()
    bindings = []
    for fact in db.get(pos[0].atom.pred, set()):
        b = unify({}, pos[0].atom.args, fact)
        if b is not None: bindings.append(b)
    for lit in pos[1:]:
        if not bindings: return set()
        fp = db.get(lit.atom.pred, set())
        if not fp: return set()
        bp = [(i, a) for i, a in enumerate(lit.atom.args) if is_variable(a) and a in bindings[0]]
        if bp:
            idx = collections.defaultdict(list)
            for f in fp: idx[tuple(f[i] for i, _ in bp)].append(f)
            new = []
            for b in bindings:
                for f in idx.get(tuple(b[v] for _, v in bp), []):
                    nb = unify(b, lit.atom.args, f)
                    if nb is not None: new.append(nb)
        else:
            new = []
            for b in bindings:
                for f in fp:
                    nb = unify(b, lit.atom.args, f)
                    if nb is not None: new.append(nb)
        bindings = new
    for iq in ineqs:
        bindings = [b for b in bindings if resolve(b, iq.ineq_left) != resolve(b, iq.ineq_right)]
    for n in neg:
        bindings = [b for b in bindings
                    if not has_fact(db, n.atom.pred, tuple(resolve(b, a) for a in n.atom.args))]
    results = set()
    for b in bindings:
        for ha in rule.head:
            g = tuple(resolve(b, a) for a in ha.args)
            if all(not is_variable(x) for x in g): results.add((ha.pred, g))
    return results


def forward_chain(db, rules, analysis):
    out = copy_db(db)
    max_s = max(analysis.strata.values()) if analysis.strata else 0
    by_s = collections.defaultdict(list)
    for r in rules:
        if r.is_constraint: continue
        if r.head:
            s = max(analysis.strata.get(a.pred, 0) for a in r.head)
            by_s[s].append(r)
    for s in range(max_s + 1):
        sr = by_s.get(s, [])
        if not sr: continue
        changed_preds = {l.atom.pred for r in sr for l in r.positive_body if l.atom}
        for it in range(20):
            ch = False; nxt = set()
            for r in sr:
                bps = {l.atom.pred for l in r.positive_body if l.atom}
                if it > 0 and not bps & changed_preds: continue
                for pred, args in evaluate_rule(r, out):
                    if add_fact(out, pred, args): ch = True; nxt.add(pred)
            changed_preds = nxt
            if not ch: break
    return out


def check_constraints(db, rules):
    for r in rules:
        if not r.is_constraint: continue
        dummy = Rule(head=[Atom("__c__", ("x","x"))], body=r.body)
        if evaluate_rule(dummy, db): return True
    return False


# ═══════════════════════════════════════════════════════════════════════════
# 5.  PROVENANCE-LITE DEPTH TRACKER
# ═══════════════════════════════════════════════════════════════════════════

def compute_depth_distribution(base_db, rules, analysis):
    """Forward-chain while tracking derivation depth of each new fact.
    Returns (derived_db, depth_map, active_rules_count)."""
    db = copy_db(base_db)
    depth_map = {}
    for p in base_db:
        for args in base_db[p]:
            depth_map[(p, args)] = 0

    max_s = max(analysis.strata.values()) if analysis.strata else 0
    by_s = collections.defaultdict(list)
    for r in rules:
        if r.is_constraint: continue
        if r.head:
            s = max(analysis.strata.get(a.pred, 0) for a in r.head)
            by_s[s].append(r)

    active_rules = set()

    for s in range(max_s + 1):
        sr = by_s.get(s, [])
        for it in range(20):
            ch = False
            for r in sr:
                pos = r.positive_body
                if not pos: continue
                # evaluate with depth tracking
                bindings_depth = []
                for fact in db.get(pos[0].atom.pred, set()):
                    b = unify({}, pos[0].atom.args, fact)
                    if b is not None:
                        bindings_depth.append((b, depth_map.get((pos[0].atom.pred, fact), 0)))
                for lit in pos[1:]:
                    if not bindings_depth: break
                    fp = db.get(lit.atom.pred, set())
                    if not fp: bindings_depth = []; break
                    new = []
                    for b, max_d in bindings_depth:
                        for f in fp:
                            nb = unify(b, lit.atom.args, f)
                            if nb is not None:
                                fd = depth_map.get((lit.atom.pred, f), 0)
                                new.append((nb, max(max_d, fd)))
                    bindings_depth = new
                for iq in r.inequalities:
                    bindings_depth = [(b, d) for b, d in bindings_depth
                                      if resolve(b, iq.ineq_left) != resolve(b, iq.ineq_right)]
                for n in r.negative_body:
                    bindings_depth = [(b, d) for b, d in bindings_depth
                                      if not has_fact(db, n.atom.pred,
                                                      tuple(resolve(b, a) for a in n.atom.args))]
                for b, max_d in bindings_depth:
                    for ha in r.head:
                        g = tuple(resolve(b, a) for a in ha.args)
                        if all(not is_variable(x) for x in g):
                            new_depth = max_d + 1
                            key = (ha.pred, g)
                            if add_fact(db, ha.pred, g):
                                ch = True
                                depth_map[key] = new_depth
                                active_rules.add(r.index)
                            elif key in depth_map and new_depth < depth_map[key]:
                                depth_map[key] = new_depth
            if not ch: break

    return db, depth_map, len(active_rules)


# ═══════════════════════════════════════════════════════════════════════════
# 6.  UNIVERSE GENERATION  (improved)
# ═══════════════════════════════════════════════════════════════════════════

def generate_universe(n, analysis, existing_facts):
    existing = collections.defaultdict(set)
    for f in existing_facts:
        a = f.head[0]
        for i, arg in enumerate(a.args):
            if not is_variable(arg):
                cls = analysis.slot_to_class.get((a.pred, i), 0)
                existing[cls].add(arg)

    ranked = sorted(analysis.type_classes.keys(),
                    key=lambda c: len(analysis.type_classes[c]), reverse=True)

    # Distribute N entities across type classes proportionally by slot count
    total_slots = max(1, sum(len(analysis.type_classes[c]) for c in ranked))
    budgets = {}
    remaining = n
    for i, cid in enumerate(ranked):
        slots_left = max(1, sum(len(analysis.type_classes[c]) for c in ranked[i:]))
        share = max(1, round(remaining * len(analysis.type_classes[cid]) / slots_left))
        share = min(share, remaining - (len(ranked) - i - 1))  # leave ≥1 for each remaining class
        share = max(1, share)
        budgets[cid] = share
        remaining -= share

    universe = {}
    for cid in ranked:
        pool = sorted(existing.get(cid, set()))
        pool = [p for p in pool if p not in analysis.rule_constants]
        target = budgets[cid]
        prefix = chr(ord('a') + (cid % 26))
        idx = 0
        while len(pool) < target:
            name = f"{prefix}{idx}"
            if name not in pool and name not in analysis.rule_constants:
                pool.append(name)
            idx += 1
        pool = pool[:target]  # cap to budget
        universe[cid] = pool
    return universe


# ═══════════════════════════════════════════════════════════════════════════
# 7.  IMPROVED SCORING
# ═══════════════════════════════════════════════════════════════════════════

def score_graph(base_db, rules, analysis):
    """Score with depth distribution, fact minimality, and active rules."""
    derived_db, depth_map, active_rules = compute_depth_distribution(
        base_db, rules, analysis)

    if check_constraints(derived_db, rules):
        return -1000.0, {}

    base_count = db_size(base_db)
    derived_only = sum(1 for k, d in depth_map.items() if d > 0)

    if derived_only == 0:
        return 0.0, {}

    # Depth distribution
    depths = [d for d in depth_map.values() if d > 0]
    max_depth = max(depths) if depths else 0
    avg_depth = sum(depths) / len(depths) if depths else 0
    deep_facts = sum(1 for d in depths if d >= 3)
    very_deep = sum(1 for d in depths if d >= 5)

    # Active derived predicates
    active_preds = set()
    for (p, _), d in depth_map.items():
        if d > 0: active_preds.add(p)

    # Amplification: derived / base (higher = more inference work per base fact)
    amplification = derived_only / max(base_count, 1)

    # Minimality bonus: fewer base facts → higher score
    # Use a gentle curve: score increases as base_count decreases
    # but don't go below a minimum needed for any derivation
    minimality = 1.0 / (1.0 + base_count / 20.0)

    score = (
        derived_only * 2.0
        + active_rules * 8.0
        + len(active_preds) * 12.0
        + max_depth * 25.0
        + avg_depth * 15.0
        + deep_facts * 8.0
        + very_deep * 15.0
        + amplification * 30.0
        + minimality * 50.0
    )

    details = {
        "base": base_count, "derived": derived_only, "active_rules": active_rules,
        "active_preds": len(active_preds), "max_depth": max_depth,
        "avg_depth": avg_depth, "deep_facts": deep_facts, "very_deep": very_deep,
        "amplification": amplification,
    }
    return score, details


# ═══════════════════════════════════════════════════════════════════════════
# 8.  SYMMETRY-AWARE FACT GENERATION
# ═══════════════════════════════════════════════════════════════════════════

def gen_random_fact(pred, analysis, universe, rng):
    """Generate a random ground fact, using rule constants for RC slots."""
    arity = analysis.pred_arity.get(pred, 2)
    # Self-referential predicate: both args must be same entity
    if pred in analysis.self_ref and arity == 2:
        if (pred, 0) in analysis.rc_slots and analysis.rule_constants:
            c = rng.choice(sorted(analysis.rule_constants))
        else:
            cls = analysis.slot_to_class.get((pred, 0), 0)
            pool = universe.get(cls, ["x"])
            c = rng.choice(pool)
        return (c, c)
    args = []
    for i in range(arity):
        if (pred, i) in analysis.rc_slots and analysis.rule_constants:
            args.append(rng.choice(sorted(analysis.rule_constants)))
        else:
            cls = analysis.slot_to_class.get((pred, i), 0)
            pool = universe.get(cls, ["x"])
            args.append(rng.choice(pool))
    return tuple(args)


def add_random_edge(db, analysis, universe, rng):
    """Add a random base fact, preferring seedable preds."""
    candidates = []
    for p in analysis.seedable:
        if p in analysis.pred_arity: candidates.extend([p] * 5)
    for p in analysis.base_preds - analysis.seedable:
        if p in analysis.pred_arity: candidates.append(p)
    if not candidates: return None

    for _ in range(20):
        pred = rng.choice(candidates)
        args = gen_random_fact(pred, analysis, universe, rng)
        if has_fact(db, pred, args): continue

        # Symmetry check: if pred is symmetric and reverse already exists, skip
        if pred in analysis.symmetric_preds and len(args) == 2:
            rev = (args[1], args[0])
            if has_fact(db, pred, rev): continue

        return (pred, args)
    return None


def remove_random_edge(db, analysis, rng):
    removable = []
    for pred in (analysis.seedable or analysis.base_preds):
        for args in db.get(pred, set()):
            removable.append((pred, args))
    if not removable:
        for pred in db:
            for args in db[pred]:
                removable.append((pred, args))
    return rng.choice(removable) if removable else None


# ═══════════════════════════════════════════════════════════════════════════
# 9.  RULE-PATTERN MOTIF INJECTION
# ═══════════════════════════════════════════════════════════════════════════

def inject_join_motif(db, rules, analysis, universe, rng, safe_add_fn=None):
    """Create connected facts that satisfy a multi-body rule's join pattern."""
    if not analysis.join_patterns: return

    rule_idx, pattern = rng.choice(analysis.join_patterns)
    adder = safe_add_fn if safe_add_fn else lambda p, a: add_fact(db, p, a)

    rule_idx, pattern = rng.choice(analysis.join_patterns)

    # Build a consistent variable binding
    binding = {}
    # Collect all variables from the pattern
    all_vars = set()
    for pred, args in pattern:
        for a in args:
            if is_variable(a): all_vars.add(a)

    # Assign constants to variables
    for var in all_vars:
        # Check if this variable is in an RC slot
        is_rc = False
        for pred, args in pattern:
            for i, a in enumerate(args):
                if a == var and (pred, i) in analysis.rc_slots:
                    is_rc = True; break
            if is_rc: break

        if is_rc and analysis.rule_constants:
            binding[var] = rng.choice(sorted(analysis.rule_constants))
        else:
            # Find what type class this variable maps to
            classes = set()
            for pred, args in pattern:
                for i, a in enumerate(args):
                    if a == var:
                        classes.add(analysis.slot_to_class.get((pred, i), 0))
            cls = min(classes) if classes else 0
            pool = universe.get(cls, ["x"])
            binding[var] = rng.choice(pool)

    # Ensure inequality satisfaction
    rule = rules[rule_idx] if rule_idx < len(rules) else None
    if rule:
        for iq in rule.inequalities:
            left = resolve(binding, iq.ineq_left)
            right = resolve(binding, iq.ineq_right)
            if left == right:
                # Re-assign one variable
                for var in [iq.ineq_left, iq.ineq_right]:
                    if is_variable(var):
                        cls_set = set()
                        for pred, args in pattern:
                            for i, a in enumerate(args):
                                if a == var: cls_set.add(analysis.slot_to_class.get((pred, i), 0))
                        cls = min(cls_set) if cls_set else 0
                        pool = universe.get(cls, ["x"])
                        for _ in range(10):
                            new_val = rng.choice(pool)
                            if new_val != binding.get(var):
                                binding[var] = new_val; break
                        break

    # Generate grounded facts (only for seedable predicates)
    for pred, args in pattern:
        if pred not in analysis.seedable: continue
        grounded = tuple(resolve(binding, a) for a in args)
        if all(not is_variable(g) for g in grounded):
            # Don't add if symmetric reverse exists
            if pred in analysis.symmetric_preds and len(grounded) == 2:
                if has_fact(db, pred, (grounded[1], grounded[0])): continue
            adder(pred, grounded)


def inject_chain(db, analysis, universe, rng):
    """Create a chain of facts for a seedable predicate that participates in transitivity."""
    trans_preds = set()
    for p in analysis.seedable:
        if analysis.pred_arity.get(p) == 2:
            if p in analysis.dep_graph.get(p, set()):
                trans_preds.add(p)

    if not trans_preds: return
    pred = rng.choice(sorted(trans_preds))
    cls0 = analysis.slot_to_class.get((pred, 0), 0)
    cls1 = analysis.slot_to_class.get((pred, 1), 0)

    if cls0 == cls1:
        pool = universe.get(cls0, ["x"])
        if len(pool) >= 3:
            chain = rng.sample(pool, min(4, len(pool)))
            for i in range(len(chain) - 1):
                if pred in analysis.symmetric_preds:
                    if not has_fact(db, pred, (chain[i+1], chain[i])):
                        add_fact(db, pred, (chain[i], chain[i+1]))
                else:
                    add_fact(db, pred, (chain[i], chain[i+1]))


# ═══════════════════════════════════════════════════════════════════════════
# 10. DERIVABILITY-MAXIMIZING REMOVAL
# ═══════════════════════════════════════════════════════════════════════════

def try_remove_derivable(db, rules, analysis, rng):
    """Try to remove a base fact that can be derived from the remaining facts.
    This increases the amount of inference work needed."""
    # Pick a random base fact
    candidates = []
    for pred in analysis.base_preds:
        if pred in analysis.derived_preds:  # only facts that COULD be derived
            for args in db.get(pred, set()):
                candidates.append((pred, args))

    if not candidates: return None

    rng.shuffle(candidates)
    for pred, args in candidates[:10]:  # try up to 10
        # Temporarily remove it
        trial = copy_db(db)
        trial[pred].discard(args)

        # Check if it's still derivable
        derived = forward_chain(trial, rules, analysis)
        if has_fact(derived, pred, args):
            # Great — removing it means it must be derived instead
            return (pred, args)

    return None


# ═══════════════════════════════════════════════════════════════════════════
# 11. SEED & HILL-CLIMB
# ═══════════════════════════════════════════════════════════════════════════

def seed_base_facts(analysis, rules, universe, n, rng):
    db = new_db()

    # Identify uniqueness constraints: preds where each X maps to at most one Y
    # (from constraints like :- p(X,Y), p(X,Z), Y!=Z)
    unique_preds = set()   # pred where first arg is a functional key
    self_loop_banned = set()  # preds with :- p(X,X)
    for r in rules:
        if not r.is_constraint: continue
        pos = [l for l in r.body if l.atom and not l.negated]
        ineqs = r.inequalities
        if len(pos) == 2 and pos[0].atom.pred == pos[1].atom.pred and ineqs:
            unique_preds.add(pos[0].atom.pred)
        if len(pos) == 1:
            a = pos[0].atom
            if len(a.args) == 2 and a.args[0] == a.args[1]:
                self_loop_banned.add(a.pred)

    def safe_add(pred, args):
        """Add a fact only if it doesn't violate obvious constraints."""
        if len(args) == 2 and args[0] == args[1] and pred in self_loop_banned:
            return False
        if pred in unique_preds and len(args) == 2:
            # Check if args[0] already has a mapping
            for existing in db.get(pred, set()):
                if existing[0] == args[0] and existing[1] != args[1]:
                    return False
        if pred in analysis.symmetric_preds and len(args) == 2:
            if has_fact(db, pred, (args[1], args[0])): return False
        return add_fact(db, pred, args)

    seedable_preds = analysis.seedable if analysis.seedable else analysis.pure_base
    is_complex = len(rules) > 100 or not analysis.pure_base

    if is_complex:
        # ── INCREMENTAL SEEDING for constraint-dense rule sets ──
        # Add facts one at a time, validate after each addition.
        # This avoids the cascade problem where bulk insertion creates
        # unfixable constraint violations.
        target = max(n, n * 2)
        pred_list = sorted(seedable_preds & set(analysis.pred_arity.keys()))
        if not pred_list:
            pred_list = sorted(set(analysis.pred_arity.keys()) & analysis.base_preds)

        attempts = 0; max_attempts = target * 15
        while db_size(db) < target and attempts < max_attempts:
            pred = rng.choice(pred_list)
            args = gen_random_fact(pred, analysis, universe, rng)
            if not safe_add(pred, args):
                attempts += 1; continue

            # Constraint check after each addition
            derived = forward_chain(db, rules, analysis)
            if check_constraints(derived, rules):
                db[pred].discard(args)  # revert
            attempts += 1

        # Try a few join motifs (with rollback)
        for _ in range(min(3, len(analysis.join_patterns))):
            snapshot = copy_db(db)
            inject_join_motif(db, rules, analysis, universe, rng, safe_add)
            derived = forward_chain(db, rules, analysis)
            if check_constraints(derived, rules):
                for p in list(db.keys()): db[p] = snapshot.get(p, set())

    else:
        # ── STANDARD SEEDING for simple rule sets (fast path) ──
        facts_per_pred = max(2, min(n, n * 2 // max(len(seedable_preds), 1)))
        for pred in seedable_preds:
            if pred not in analysis.pred_arity: continue
            for _ in range(facts_per_pred * 2):
                safe_add(pred, gen_random_fact(pred, analysis, universe, rng))

        for pred in analysis.base_preds - seedable_preds:
            if pred not in analysis.pred_arity: continue
            for _ in range(max(1, n // 4)):
                safe_add(pred, gen_random_fact(pred, analysis, universe, rng))

        for _ in range(min(6, len(analysis.join_patterns) * 2)):
            inject_join_motif(db, rules, analysis, universe, rng, safe_add)
        for _ in range(2):
            inject_chain(db, analysis, universe, rng)

        # Post-seed repair
        derived = forward_chain(db, rules, analysis)
        for _ in range(50):
            if not check_constraints(derived, rules): break
            removable = [(p, a) for p in seedable_preds for a in db.get(p, set())]
            if not removable: break
            p, a = rng.choice(removable)
            db[p].discard(a)
            derived = forward_chain(db, rules, analysis)

    return db


def hill_climb(base_db, rules, analysis, universe, iterations, rng, verbose=False):
    best = copy_db(base_db)
    best_score, best_details = score_graph(best, rules, analysis)
    is_complex = len(rules) > 100 or not analysis.pure_base

    if verbose:
        print(f"  Initial score: {best_score:.1f} {best_details}", file=sys.stderr)

    # Repair violations
    if best_score < 0:
        if verbose: print("  Repairing constraints...", file=sys.stderr)
        repair_limit = 30 if is_complex else 200
        for _ in range(repair_limit):
            c = copy_db(best)
            e = remove_random_edge(c, analysis, rng)
            if e: c[e[0]].discard(e[1])
            s, d = score_graph(c, rules, analysis)
            if s > best_score:
                best, best_score, best_details = c, s, d
                if best_score >= 0: break
        if verbose: print(f"  After repair: {best_score:.1f}", file=sys.stderr)

    # Choose mutation weights based on complexity
    if is_complex:
        # Skip minimize (too slow), more adds and swaps
        actions = ["add", "remove", "swap", "motif", "chain"]
        weights = [4, 3, 3, 2, 1]
    else:
        actions = ["add", "remove", "swap", "motif", "chain", "minimize"]
        weights = [3, 3, 2, 3, 2, 2]

    stagnant = 0
    for it in range(iterations):
        c = copy_db(best)

        if best_score < 0:
            action = "remove"
        else:
            action = rng.choices(actions, weights=weights)[0]

        if action == "add":
            e = add_random_edge(c, analysis, universe, rng)
            if e: add_fact(c, e[0], e[1])
        elif action == "remove":
            e = remove_random_edge(c, analysis, rng)
            if e: c[e[0]].discard(e[1])
        elif action == "swap":
            e = remove_random_edge(c, analysis, rng)
            if e: c[e[0]].discard(e[1])
            e = add_random_edge(c, analysis, universe, rng)
            if e: add_fact(c, e[0], e[1])
        elif action == "motif":
            inject_join_motif(c, rules, analysis, universe, rng)
        elif action == "chain":
            inject_chain(c, analysis, universe, rng)
        elif action == "minimize":
            # Try removing a fact that can be derived instead
            removal = try_remove_derivable(c, rules, analysis, rng)
            if removal:
                c[removal[0]].discard(removal[1])

        s, d = score_graph(c, rules, analysis)
        if s > best_score or (s == best_score and rng.random() < 0.05):
            best, best_score, best_details = c, s, d
            stagnant = 0
            if verbose and it % 25 == 0:
                print(f"  Iter {it}: score {best_score:.1f} "
                      f"base={d.get('base',0)} derived={d.get('derived',0)} "
                      f"maxD={d.get('max_depth',0)} amp={d.get('amplification',0):.1f}",
                      file=sys.stderr)
        else:
            stagnant += 1

        if stagnant > 30 and best_score >= 0:
            inject_join_motif(best, rules, analysis, universe, rng)
            inject_chain(best, analysis, universe, rng)
            stagnant = 0
            best_score, best_details = score_graph(best, rules, analysis)

    return best, best_score, best_details


# ═══════════════════════════════════════════════════════════════════════════
# 12. OUTPUT
# ═══════════════════════════════════════════════════════════════════════════

def format_asp(db, analysis):
    lines = ["% === BASE FACTS (sampled) ===", ""]
    output_preds = analysis.seedable if analysis.seedable else set(db.keys())
    for pred in sorted(output_preds):
        facts = sorted(db.get(pred, set()))
        if not facts: continue
        lines.append(f"% {pred}")
        for args in facts: lines.append(f"{pred}({','.join(args)}).")
        lines.append("")
    return "\n".join(lines)


def format_analysis(rs_score, rs_features, graph_details, analysis):
    lines = ["% ═══════════════════════════════════════════",
             "% RULE SET ANALYSIS",
             "% ═══════════════════════════════════════════"]
    lines.append(f"% Rule set difficulty score: {rs_score:.1f}")
    for k, v in sorted(rs_features.items()): lines.append(f"%   {k}: {v}")
    lines.append(f"% Symmetric predicates: {sorted(analysis.symmetric_preds)}")
    lines.append(f"% Join patterns: {len(analysis.join_patterns)}")
    lines.append("%")
    lines.append("% ═══════════════════════════════════════════")
    lines.append("% SAMPLED GRAPH ANALYSIS")
    lines.append("% ═══════════════════════════════════════════")
    for k, v in sorted(graph_details.items()):
        lines.append(f"%   {k}: {v}")
    return "\n".join(lines)


def score_ruleset(rules, analysis):
    non_fact = [r for r in rules if not r.is_fact]
    # Longest acyclic path (BFS-based, safe for cyclic graphs)
    max_chain = 0
    for start in list(analysis.derived_preds)[:15]:
        visited = set(); queue = [(start, 0)]
        while queue:
            node, depth = queue.pop(0)
            if node in visited: continue
            visited.add(node)
            max_chain = max(max_chain, depth)
            if depth < 10:  # hard cap
                for nb in analysis.dep_graph.get(node, set()):
                    if nb not in visited: queue.append((nb, depth + 1))
    avg_joins = (sum(max(0, len(r.positive_body)-1) for r in non_fact) / max(len(non_fact),1)) if non_fact else 0
    features = {
        "num_rules": len(non_fact), "num_base_preds": len(analysis.base_preds),
        "num_derived_preds": len(analysis.derived_preds),
        "num_symmetric_preds": len(analysis.symmetric_preds),
        "num_join_patterns": len(analysis.join_patterns),
        "num_choice_rules": sum(1 for r in rules if r.is_choice),
        "num_constraints": sum(1 for r in rules if r.is_constraint),
        "has_negation": any(l.negated for r in rules for l in r.body),
        "num_strata": len(set(analysis.strata.values())),
        "max_dep_chain": max_chain, "avg_joins": avg_joins,
    }
    score = (features["num_rules"]*2 + max_chain*12 + features["num_choice_rules"]*20
             + features["num_constraints"]*12 + features["has_negation"]*18
             + features["num_strata"]*15 + len(analysis.symmetric_preds)*5
             + len(analysis.join_patterns)*8 + avg_joins*10)
    return score, features


# ═══════════════════════════════════════════════════════════════════════════
# 13. MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="General ASP graph sampler v2")
    parser.add_argument("rules_file")
    parser.add_argument("num_vertices", type=int)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--iterations", type=int, default=300)
    parser.add_argument("--output", type=str, default=None)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--score-only", action="store_true")
    parser.add_argument("--viz", type=str, default=None)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    with open(args.rules_file) as f: program_text = f.read()

    if args.verbose: print(f"Parsing {args.rules_file}...", file=sys.stderr)
    rules, facts = parse_program(program_text)
    analysis = analyze_rules(rules, facts)

    if args.verbose:
        print(f"  {len(rules)} rules, {len(facts)} facts", file=sys.stderr)
        print(f"  Pure base: {sorted(analysis.pure_base)[:6]}", file=sys.stderr)
        print(f"  Seedable: {sorted(analysis.seedable)[:8]}{'...' if len(analysis.seedable) > 8 else ''}",
              file=sys.stderr)
        print(f"  Symmetric: {sorted(analysis.symmetric_preds)}", file=sys.stderr)
        print(f"  Join patterns: {len(analysis.join_patterns)}", file=sys.stderr)
        print(f"  Type classes: {len(analysis.type_classes)}", file=sys.stderr)

    rs_score, rs_features = score_ruleset(rules, analysis)
    if args.verbose: print(f"  Rule set score: {rs_score:.1f}", file=sys.stderr)
    if args.score_only: return

    # Auto-adapt iterations for large rule sets (forward chain is slow)
    effective_iterations = args.iterations
    if len(rules) > 100 and args.iterations > 50:
        effective_iterations = min(args.iterations, 40)
        if args.verbose:
            print(f"  Large rule set ({len(rules)} rules): "
                  f"reducing iterations to {effective_iterations}", file=sys.stderr)

    universe = generate_universe(args.num_vertices, analysis, facts)
    if args.verbose:
        for cid, pool in sorted(universe.items()):
            preds = {f"{p}[{pos}]" for (p,pos), c in analysis.slot_to_class.items() if c == cid}
            print(f"  Class {cid} ({len(pool)}): {sorted(preds)[:4]}", file=sys.stderr)

    base_db = new_db()
    for f in facts: add_fact(base_db, f.head[0].pred, f.head[0].args)
    seeded = seed_base_facts(analysis, rules, universe, args.num_vertices, rng)
    for p, fs in seeded.items():
        for a in fs: add_fact(base_db, p, a)

    if args.verbose:
        print(f"  Seeded: {db_size(base_db)} base facts", file=sys.stderr)
        print(f"Hill-climbing {effective_iterations} iterations...", file=sys.stderr)

    optimized, final_score, final_details = hill_climb(
        base_db, rules, analysis, universe, effective_iterations, rng, verbose=args.verbose)

    if args.verbose:
        print(f"\nFinal: score={final_score:.1f} {final_details}", file=sys.stderr)

    output = "\n".join([
        format_analysis(rs_score, rs_features, final_details, analysis), "",
        format_asp(optimized, analysis)])

    if args.output:
        with open(args.output, "w") as f: f.write(output)
        if args.verbose: print(f"Written to {args.output}", file=sys.stderr)
    else:
        print(output)

    if args.viz:
        import asp_viz
        derived = forward_chain(optimized, rules, analysis)
        asp_viz.visualize_db(derived, args.viz, title=f"ASP Graph v2 — {args.rules_file}",
                             base_preds=analysis.base_preds, derived_preds=analysis.derived_preds,
                             stats=final_details)
        if args.verbose: print(f"Viz written to {args.viz}", file=sys.stderr)

if __name__ == "__main__":
    main()
