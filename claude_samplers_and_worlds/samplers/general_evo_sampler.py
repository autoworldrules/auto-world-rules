#!/usr/bin/env python3
"""
Evolutionary Population-Based ASP Graph Sampler
================================================
Based on the empirical finding that lucky initial configurations with
minimal optimization outperform heavily-optimized single runs.

Strategy:
  1. DIVERSE POPULATION: Generate many candidate graphs using different
     seeding strategies (backward skeletons, join motifs, random, hybrid).
  2. LIGHT OPTIMIZATION: Apply only 10-30 hill-climbing iterations per
     candidate (beyond this, optimization degrades quality).
  3. TRUE FITNESS: Score each candidate using provenance-tracking forward
     chaining — measure actual proof depth distribution, not a proxy.
  4. SELECTION + CROSSOVER: Take the fittest candidates, recombine their
     base facts to create offspring that inherit good structure from both.
  5. MUTATION: Light random perturbation of offspring.
  6. ITERATE: Run 3-5 generations, keeping the population diverse via
     tournament selection.
  7. FINAL MINIMIZATION: Remove derivable base facts from the winner to
     maximize the inference-per-fact ratio.

Usage:
    python3 evo_sampler.py rules.lp 8 [--population 40] [--generations 5]
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
from typing import Dict, List, Optional, Set, Tuple

# ═══════════════════════════════════════════════════════════════════════════
#  CORE DATA STRUCTURES + PARSER
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
class Rule:
    head: List[Atom]; body: List[Literal]
    is_choice: bool = False; is_constraint: bool = False; index: int = 0
    @property
    def positive_body(self): return [l for l in self.body if l.atom and not l.negated]
    @property
    def negative_body(self): return [l for l in self.body if l.atom and l.negated]
    @property
    def inequalities(self): return [l for l in self.body if l.is_inequality]

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
def is_variable(s): return bool(s) and s[0].isupper()
def resolve(b, a): return b.get(a, a) if is_variable(a) else a

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
#  RULE ANALYSIS
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
        g = collections.defaultdict(set)
        for k in self.parent: g[self.find(k)].add(k)
        return dict(g)

@dataclass
class Analysis:
    pred_arity: Dict[str, int]
    pure_base: Set[str]
    seedable: Set[str]            # safe to use as base facts (= pure_base or SCC-detected)
    derived: Set[str]
    slot_to_class: Dict[Tuple, int]
    type_classes: Dict[int, Set]
    rules_for: Dict[str, List[int]]
    symmetric: Set[str]
    strata: Dict[str, int]
    join_patterns: List[Tuple]
    rule_constants: Set[str]
    rc_slots: Set[Tuple]
    self_ref: Set[str] = field(default_factory=set)  # binary preds always used as p(X,X)

def analyze(rules, facts):
    pred_arity = {}; head_preds = set(); body_preds = set()
    for r in rules:
        for a in r.head: head_preds.add(a.pred); pred_arity[a.pred] = len(a.args)
        for l in r.body:
            if l.atom: body_preds.add(l.atom.pred); pred_arity[l.atom.pred] = len(l.atom.args)
    for f in facts: pred_arity[f.head[0].pred] = len(f.head[0].args)
    fact_preds = {f.head[0].pred for f in facts}
    pure_base = (body_preds | fact_preds) - head_preds
    derived = head_preds

    # Detect symmetric base predicates (only have symmetry rules as derivations)
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
        if all_sym: symmetric_base.add(p)

    # Compute seedable: pure_base when non-empty, SCC-based when empty
    if pure_base or symmetric_base:
        seedable = (set(pure_base) | symmetric_base) - fact_preds
    else:
        # SCC-based detection (same as backward/v2 samplers)
        dep_raw = collections.defaultdict(set)
        fanout_s = collections.Counter()
        for r in rules:
            if r.is_constraint: continue
            for ha in r.head:
                for l in r.positive_body:
                    if l.atom: dep_raw[ha.pred].add(l.atom.pred)
            for l in r.positive_body:
                if l.atom: fanout_s[l.atom.pred] += 1
        all_ps = set(dep_raw.keys())
        for vs in dep_raw.values(): all_ps |= vs
        idx_s = [0]; stk = []; ons = set()
        ix = {}; ll = {}; sccs_s = []
        old_lim = sys.getrecursionlimit()
        sys.setrecursionlimit(max(5000, len(all_ps) * 3))
        def _scc(v):
            ix[v] = ll[v] = idx_s[0]; idx_s[0] += 1
            stk.append(v); ons.add(v)
            for w in dep_raw.get(v, set()):
                if w not in ix: _scc(w); ll[v] = min(ll[v], ll[w])
                elif w in ons: ll[v] = min(ll[v], ix[w])
            if ll[v] == ix[v]:
                sc = set()
                while True:
                    w = stk.pop(); ons.discard(w); sc.add(w)
                    if w == v: break
                sccs_s.append(sc)
        for v in all_ps:
            if v not in ix: _scc(v)
        sys.setrecursionlimit(old_lim)
        has_simple_s = set()
        for r in rules:
            if r.is_constraint: continue
            pb = r.positive_body
            if len(pb) == 1 and len(r.head) == 1:
                has_simple_s.add(r.head[0].pred)
                has_simple_s.add(pb[0].atom.pred)
        seedable = set()
        for scc in sccs_s:
            bm = [(p, fanout_s[p]) for p in scc if fanout_s[p] > 0 and p in has_simple_s]
            if not bm: continue
            bm.sort(key=lambda x: -x[1])
            take = max(2, len(scc) // 8)
            for p, _ in bm[:take]: seedable.add(p)
        seedable = {p for p in seedable
                    if not p.startswith('no_') and not p.startswith('not_')
                    and p not in ('is_person','is_place','is_agent','is_asset',
                                  'is_level','living_in_same_place')}
        seedable -= fact_preds

    uf = UnionFind()
    for r in rules:
        vp = collections.defaultdict(list)
        for a in list(r.head) + [l.atom for l in r.body if l.atom]:
            for i, arg in enumerate(a.args):
                if is_variable(arg): vp[arg].append((a.pred, i))
        for var, positions in vp.items():
            for p1, p2 in zip(positions, positions[1:]): uf.union(p1, p2)
    for p, ar in pred_arity.items():
        for i in range(ar): uf.find((p, i))
    raw = uf.classes(); tc = {}; stc = {}
    for cid, (rep, members) in enumerate(raw.items()):
        tc[cid] = members
        for m in members: stc[m] = cid
    if len(tc) > 5:
        largest = max(tc, key=lambda c: len(tc[c]))
        for t in [c for c in tc if c != largest and len(tc[c]) <= 1]:
            tc[largest] |= tc[t]
            for s in tc[t]: stc[s] = largest
            del tc[t]

    rules_for = collections.defaultdict(list)
    for r in rules:
        if r.is_constraint: continue
        for a in r.head: rules_for[a.pred].append(r.index)

    symmetric = set()
    for r in rules:
        if r.is_constraint: continue
        pb = r.positive_body
        if (len(pb) == 1 and len(r.head) == 1
                and pb[0].atom.pred == r.head[0].pred
                and len(r.head[0].args) == 2 and len(pb[0].atom.args) == 2):
            ha, ba = r.head[0].args, pb[0].atom.args
            if ha[0] == ba[1] and ha[1] == ba[0]: symmetric.add(r.head[0].pred)

    strata = {p: 0 for p in pure_base | fact_preds}
    for _ in range(len(pred_arity) + 2):
        ch = False
        for r in rules:
            if r.is_constraint: continue
            for ha in r.head:
                ms = max((strata.get(l.atom.pred, 0) + (1 if l.negated else 0)
                          for l in r.body if l.atom), default=0)
                if ms > strata.get(ha.pred, -1): strata[ha.pred] = ms; ch = True
        if not ch: break

    join_patterns = []
    for r in rules:
        if r.is_constraint: continue
        pb = r.positive_body
        if len(pb) >= 2:
            pattern = [(l.atom.pred, l.atom.args) for l in pb if l.atom]
            if len(pattern) >= 2: join_patterns.append((r.index, pattern))

    # Rule constant detection
    rule_constants = set(); rc_slots = set()
    for f in facts:
        a = f.head[0]
        for i, arg in enumerate(a.args):
            if not is_variable(arg):
                rc_slots.add((a.pred, i)); rule_constants.add(arg)
    for _ in range(10):
        ch2 = False
        for r in rules:
            if r.is_constraint: continue
            vp2 = collections.defaultdict(set)
            for a in list(r.head) + [l.atom for l in r.body if l.atom]:
                for i, arg in enumerate(a.args):
                    if is_variable(arg): vp2[arg].add((a.pred, i))
            for var, positions in vp2.items():
                if any(p in rc_slots for p in positions):
                    for p in positions:
                        if p not in rc_slots: rc_slots.add(p); ch2 = True
        if not ch2: break

    # Self-referential binary predicates (always used as p(X,X))
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

    return Analysis(pred_arity=pred_arity, pure_base=pure_base, seedable=seedable,
                    derived=derived,
                    slot_to_class=stc, type_classes=tc, rules_for=dict(rules_for),
                    symmetric=symmetric, strata=strata, join_patterns=join_patterns,
                    rule_constants=rule_constants, rc_slots=rc_slots,
                    self_ref=self_ref)


# ═══════════════════════════════════════════════════════════════════════════
#  FORWARD CHAINER + FITNESS EVALUATOR
# ═══════════════════════════════════════════════════════════════════════════

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
    pos = rule.positive_body
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
    for iq in rule.inequalities:
        bindings = [b for b in bindings if resolve(b, iq.ineq_left) != resolve(b, iq.ineq_right)]
    for n in rule.negative_body:
        bindings = [b for b in bindings
                    if not has_fact(db, n.atom.pred, tuple(resolve(b, a) for a in n.atom.args))]
    results = set()
    for b in bindings:
        for ha in rule.head:
            g = tuple(resolve(b, a) for a in ha.args)
            if all(not is_variable(x) for x in g): results.add((ha.pred, g))
    return results

def forward_chain(db, rules, ana):
    out = copy_db(db)
    max_s = max(ana.strata.values()) if ana.strata else 0
    by_s = collections.defaultdict(list)
    for r in rules:
        if r.is_constraint: continue
        if r.head:
            s = max(ana.strata.get(a.pred, 0) for a in r.head)
            by_s[s].append(r)
    for s in range(max_s + 1):
        sr = by_s.get(s, [])
        cp = {l.atom.pred for r in sr for l in r.positive_body if l.atom}
        for it in range(25):
            ch = False; nxt = set()
            for r in sr:
                bps = {l.atom.pred for l in r.positive_body if l.atom}
                if it > 0 and not bps & cp: continue
                for pred, args in evaluate_rule(r, out):
                    if add_fact(out, pred, args): ch = True; nxt.add(pred)
            cp = nxt
            if not ch: break
    return out

def check_constraints(db, rules):
    for r in rules:
        if not r.is_constraint: continue
        dummy = Rule(head=[Atom("__c__", ("x","x"))], body=r.body, index=999)
        if evaluate_rule(dummy, db): return True
    return False


@dataclass
class Fitness:
    """True fitness of a candidate graph, based on actual proof depths."""
    total: float = 0
    base_count: int = 0
    derived_count: int = 0
    max_depth: int = 0
    avg_depth: float = 0
    deep3: int = 0          # facts at depth ≥ 3
    deep5: int = 0          # facts at depth ≥ 5
    active_preds: int = 0
    active_rules: int = 0
    amplification: float = 0
    violated: bool = False

    def __lt__(self, other): return self.total < other.total


def evaluate_fitness(base_db: FactDB, rules: List[Rule], ana: Analysis) -> Fitness:
    """TRUE fitness: forward-chain with depth tracking, no proxy."""
    derived = forward_chain(base_db, rules, ana)
    if check_constraints(derived, rules):
        return Fitness(total=-1000, violated=True)

    depth_map = {}
    for p in base_db:
        for a in base_db[p]: depth_map[(p, a)] = 0

    max_s = max(ana.strata.values()) if ana.strata else 0
    by_s = collections.defaultdict(list)
    for r in rules:
        if r.is_constraint: continue
        if r.head:
            s = max(ana.strata.get(a.pred, 0) for a in r.head)
            by_s[s].append(r)

    active_rules = set()
    temp = copy_db(base_db)
    for s in range(max_s + 1):
        for it in range(25):
            ch = False
            for r in by_s.get(s, []):
                pos = r.positive_body
                if not pos: continue
                bd = []
                for fact in temp.get(pos[0].atom.pred, set()):
                    b = unify({}, pos[0].atom.args, fact)
                    if b is not None: bd.append((b, depth_map.get((pos[0].atom.pred, fact), 0)))
                for lit in pos[1:]:
                    if not bd: break
                    fp = temp.get(lit.atom.pred, set())
                    new = []
                    for b, md in bd:
                        for f in fp:
                            nb = unify(b, lit.atom.args, f)
                            if nb is not None:
                                new.append((nb, max(md, depth_map.get((lit.atom.pred, f), 0))))
                    bd = new
                for iq in r.inequalities:
                    bd = [(b,d) for b,d in bd if resolve(b, iq.ineq_left) != resolve(b, iq.ineq_right)]
                for neg in r.negative_body:
                    bd = [(b,d) for b,d in bd
                          if not has_fact(temp, neg.atom.pred,
                                         tuple(resolve(b, a) for a in neg.atom.args))]
                for b, md in bd:
                    for ha in r.head:
                        g = tuple(resolve(b, a) for a in ha.args)
                        if all(not is_variable(x) for x in g):
                            nd = md + 1; key = (ha.pred, g)
                            if add_fact(temp, ha.pred, g):
                                ch = True; depth_map[key] = nd; active_rules.add(r.index)
                            elif key in depth_map and nd < depth_map[key]:
                                depth_map[key] = nd
            if not ch: break

    depths = [d for d in depth_map.values() if d > 0]
    if not depths:
        return Fitness(total=0, base_count=db_size(base_db))

    mx = max(depths)
    avg = sum(depths) / len(depths)
    d3 = sum(1 for d in depths if d >= 3)
    d5 = sum(1 for d in depths if d >= 5)
    ap = len({p for (p, _), d in depth_map.items() if d > 0})
    bc = db_size(base_db)
    amp = len(depths) / max(bc, 1)

    # Fitness formula: heavily reward depth and penalise bloat
    total = (
        mx * 40.0                  # max depth is king
        + avg * 20.0               # average depth matters
        + d3 * 5.0                 # deep facts
        + d5 * 12.0                # very deep facts
        + ap * 10.0                # predicate coverage
        + len(active_rules) * 6.0  # rule coverage
        + amp * 25.0               # amplification
        - bc * 0.5                 # penalise base bloat
    )

    return Fitness(total=total, base_count=bc, derived_count=len(depths),
                   max_depth=mx, avg_depth=avg, deep3=d3, deep5=d5,
                   active_preds=ap, active_rules=len(active_rules),
                   amplification=amp)


# ═══════════════════════════════════════════════════════════════════════════
#  UNIVERSE + BASIC GENERATORS
# ═══════════════════════════════════════════════════════════════════════════

def generate_universe(n, ana, facts):
    existing = collections.defaultdict(set)
    for f in facts:
        a = f.head[0]
        for i, arg in enumerate(a.args):
            if not is_variable(arg):
                cls = ana.slot_to_class.get((a.pred, i), 0)
                existing[cls].add(arg)
    ranked = sorted(ana.type_classes.keys(),
                    key=lambda c: len(ana.type_classes[c]), reverse=True)
    # Distribute N across type classes proportionally
    total_slots = max(1, sum(len(ana.type_classes[c]) for c in ranked))
    budgets = {}; remaining = n
    for i, cid in enumerate(ranked):
        slots_left = max(1, sum(len(ana.type_classes[c]) for c in ranked[i:]))
        share = max(1, round(remaining * len(ana.type_classes[cid]) / slots_left))
        share = min(share, remaining - (len(ranked) - i - 1))
        share = max(1, share)
        budgets[cid] = share; remaining -= share
    universe = {}
    for cid in ranked:
        pool = sorted(existing.get(cid, set()))
        pool = [p for p in pool if p not in ana.rule_constants]
        target = budgets[cid]
        prefix = chr(ord('a') + (cid % 26))
        idx = 0
        while len(pool) < target:
            name = f"{prefix}{idx}"
            if name not in pool and name not in ana.rule_constants:
                pool.append(name)
            idx += 1
        pool = pool[:target]
        universe[cid] = pool
    return universe

def gen_fact(pred, ana, universe, rng):
    arity = ana.pred_arity.get(pred, 2)
    # Self-referential predicate: both args must be same entity
    if pred in ana.self_ref and arity == 2:
        if (pred, 0) in ana.rc_slots and ana.rule_constants:
            c = rng.choice(sorted(ana.rule_constants))
        else:
            c = rng.choice(universe.get(ana.slot_to_class.get((pred, 0), 0), ["x0"]))
        return (c, c)
    args = []
    for i in range(arity):
        if (pred, i) in ana.rc_slots and ana.rule_constants:
            args.append(rng.choice(sorted(ana.rule_constants)))
        else:
            args.append(rng.choice(universe.get(ana.slot_to_class.get((pred, i), 0), ["x0"])))
    return tuple(args)

def inject_join(db, rules, ana, universe, rng):
    if not ana.join_patterns: return
    ri, pattern = rng.choice(ana.join_patterns)
    binding = {}
    for pred, args in pattern:
        for i, a in enumerate(args):
            if is_variable(a) and a not in binding:
                if (pred, i) in ana.rc_slots and ana.rule_constants:
                    binding[a] = rng.choice(sorted(ana.rule_constants))
                else:
                    cls = ana.slot_to_class.get((pred, i), 0)
                    binding[a] = rng.choice(universe.get(cls, ["x0"]))
    rule = rules[ri] if ri < len(rules) else None
    if rule:
        for iq in rule.inequalities:
            l, r_ = resolve(binding, iq.ineq_left), resolve(binding, iq.ineq_right)
            if l == r_:
                for v in [iq.ineq_right, iq.ineq_left]:
                    if is_variable(v):
                        for pred, args in pattern:
                            for i, a in enumerate(args):
                                if a == v:
                                    pool = universe.get(ana.slot_to_class.get((pred, i), 0), ["x0"])
                                    for _ in range(10):
                                        nv = rng.choice(pool)
                                        if nv != binding.get(v): binding[v] = nv; break
                        break
    for pred, args in pattern:
        if pred not in ana.seedable:
            continue
        g = tuple(resolve(binding, a) for a in args)
        if all(not is_variable(x) for x in g):
            if pred in ana.symmetric and len(g) == 2 and has_fact(db, pred, (g[1], g[0])): continue
            # Self-ref: force both args equal
            if pred in ana.self_ref and len(g) == 2 and g[0] != g[1]:
                g = (g[0], g[0])
            add_fact(db, pred, g)


# ═══════════════════════════════════════════════════════════════════════════
#  DIVERSE SEEDING STRATEGIES
# ═══════════════════════════════════════════════════════════════════════════

def strategy_random(ana, rules, universe, n, rng):
    """Pure random: generate random pure-base facts."""
    db = new_db()
    for pred in ana.seedable:
        if pred not in ana.pred_arity: continue
        for _ in range(rng.randint(1, max(2, n))):
            a = gen_fact(pred, ana, universe, rng)
            if pred in ana.symmetric and len(a) == 2 and has_fact(db, pred, (a[1], a[0])): continue
            add_fact(db, pred, a)
    return db

def strategy_join_heavy(ana, rules, universe, n, rng):
    """Heavy join-motif injection: many connected subgraphs."""
    db = new_db()
    num_injections = rng.randint(n, n * 3)
    for _ in range(num_injections):
        inject_join(db, rules, ana, universe, rng)
    # Sprinkle random facts
    for pred in ana.seedable:
        if pred not in ana.pred_arity: continue
        for _ in range(rng.randint(0, max(1, n // 3))):
            add_fact(db, pred, gen_fact(pred, ana, universe, rng))
    return db

def strategy_sparse(ana, rules, universe, n, rng):
    """Minimal: few carefully chosen facts targeting deep rules."""
    db = new_db()
    # Only inject joins for highest-strata rules
    high_strata_patterns = [
        (ri, pat) for ri, pat in ana.join_patterns
        if any(ana.strata.get(rules[ri].head[0].pred if ri < len(rules) and rules[ri].head else "", 0) >= 2
               for _ in [1])
    ]
    patterns = high_strata_patterns or ana.join_patterns
    for _ in range(rng.randint(2, max(3, n // 2))):
        if patterns:
            ri, pattern = rng.choice(patterns)
            binding = {}
            for pred, args in pattern:
                for i, a in enumerate(args):
                    if is_variable(a) and a not in binding:
                        if (pred, i) in ana.rc_slots and ana.rule_constants:
                            binding[a] = rng.choice(sorted(ana.rule_constants))
                        else:
                            cls = ana.slot_to_class.get((pred, i), 0)
                            binding[a] = rng.choice(universe.get(cls, ["x0"]))
            for pred, args in pattern:
                if pred in ana.seedable:
                    g = tuple(resolve(binding, a) for a in args)
                    if all(not is_variable(x) for x in g):
                        add_fact(db, pred, g)
    return db

def strategy_chain(ana, rules, universe, n, rng):
    """Build long chains in self-referential predicates."""
    db = new_db()
    # Find predicates that depend on themselves
    self_dep = set()
    for p in ana.derived:
        for ri in ana.rules_for.get(p, []):
            if ri < len(rules):
                for l in rules[ri].positive_body:
                    if l.atom and l.atom.pred == p:
                        self_dep.add(p)
    # Also include pure base that feeds into chains
    chain_preds = set()
    for p in ana.seedable:
        if ana.pred_arity.get(p) == 2:
            chain_preds.add(p)

    target_preds = (self_dep & ana.seedable) or chain_preds
    if not target_preds:
        target_preds = {p for p in ana.seedable if ana.pred_arity.get(p) == 2}

    for pred in target_preds:
        cls0 = ana.slot_to_class.get((pred, 0), 0)
        cls1 = ana.slot_to_class.get((pred, 1), 0)
        pool = universe.get(cls0, ["x0"])
        if cls0 == cls1 and len(pool) >= 3:
            chain = rng.sample(pool, min(rng.randint(3, max(4, n)), len(pool)))
            for i in range(len(chain) - 1):
                add_fact(db, pred, (chain[i], chain[i+1]))

    # Add supporting facts from other preds
    for pred in ana.seedable - target_preds:
        if pred not in ana.pred_arity: continue
        for _ in range(rng.randint(1, 3)):
            add_fact(db, pred, gen_fact(pred, ana, universe, rng))

    return db

def strategy_hybrid(ana, rules, universe, n, rng):
    """Mix of strategies."""
    db = new_db()
    # Some joins
    for _ in range(rng.randint(2, n)):
        inject_join(db, rules, ana, universe, rng)
    # Some chains
    for pred in ana.seedable:
        if ana.pred_arity.get(pred) == 2:
            cls0 = ana.slot_to_class.get((pred, 0), 0)
            pool = universe.get(cls0, ["x0"])
            if len(pool) >= 3:
                chain = rng.sample(pool, min(3, len(pool)))
                for i in range(len(chain) - 1):
                    add_fact(db, pred, (chain[i], chain[i+1]))
            break  # just one chain pred
    # Some random
    for pred in ana.seedable:
        if pred not in ana.pred_arity: continue
        for _ in range(rng.randint(0, 2)):
            add_fact(db, pred, gen_fact(pred, ana, universe, rng))
    return db

STRATEGIES = [strategy_random, strategy_join_heavy, strategy_sparse,
              strategy_chain, strategy_hybrid]


# ═══════════════════════════════════════════════════════════════════════════
#  LIGHT MUTATION (replaces hill-climbing)
# ═══════════════════════════════════════════════════════════════════════════

def mutate(db, ana, rules, universe, rng, steps=15):
    """Light mutation: a few random add/remove/swap operations."""
    for _ in range(steps):
        action = rng.choices(["add", "remove", "join"], weights=[3, 2, 3])[0]
        if action == "add":
            preds = [p for p in ana.seedable if p in ana.pred_arity]
            if preds:
                pred = rng.choice(preds)
                a = gen_fact(pred, ana, universe, rng)
                if pred in ana.symmetric and len(a) == 2 and has_fact(db, pred, (a[1], a[0])): continue
                add_fact(db, pred, a)
        elif action == "remove":
            candidates = [(p, a) for p in ana.seedable for a in db.get(p, set())]
            if candidates:
                p, a = rng.choice(candidates)
                db[p].discard(a)
        elif action == "join":
            inject_join(db, rules, ana, universe, rng)
    return db


# ═══════════════════════════════════════════════════════════════════════════
#  CROSSOVER
# ═══════════════════════════════════════════════════════════════════════════

def crossover(parent1: FactDB, parent2: FactDB, rng: random.Random) -> FactDB:
    """Create offspring by combining facts from two parents.
    For each predicate, randomly take facts from one parent or the other,
    with some taken from both."""
    child = new_db()
    all_preds = set(parent1.keys()) | set(parent2.keys())
    for pred in all_preds:
        f1 = list(parent1.get(pred, set()))
        f2 = list(parent2.get(pred, set()))

        # Strategy: take a random subset from each parent
        ratio = rng.random()  # how much from parent1
        take1 = int(len(f1) * ratio)
        take2 = int(len(f2) * (1 - ratio))

        rng.shuffle(f1)
        rng.shuffle(f2)
        for a in f1[:max(1, take1)]: add_fact(child, pred, a)
        for a in f2[:max(1, take2)]: add_fact(child, pred, a)

    return child


# ═══════════════════════════════════════════════════════════════════════════
#  CONSTRAINT REPAIR
# ═══════════════════════════════════════════════════════════════════════════

def repair(db, rules, ana, rng, max_attempts=200):
    """Remove facts until constraints are satisfied."""
    derived = forward_chain(db, rules, ana)
    for _ in range(max_attempts):
        if not check_constraints(derived, rules): return True
        # Target constraint predicates
        removed = False
        for r in rules:
            if not r.is_constraint: continue
            dummy = Rule(head=[Atom("__c__", ("x","x"))], body=r.body, index=999)
            if not evaluate_rule(dummy, derived): continue
            for l in r.body:
                if l.atom and l.atom.pred in db and db[l.atom.pred]:
                    victim = rng.choice(list(db[l.atom.pred]))
                    db[l.atom.pred].discard(victim)
                    removed = True; break
            if removed: break
        if not removed:
            candidates = [(p, a) for p in ana.seedable for a in db.get(p, set())]
            if not candidates: break
            p, a = rng.choice(candidates)
            db[p].discard(a)
        derived = forward_chain(db, rules, ana)
    return not check_constraints(derived, rules)


# ═══════════════════════════════════════════════════════════════════════════
#  MINIMIZATION
# ═══════════════════════════════════════════════════════════════════════════

def minimize(db, rules, ana, rng, max_removals=40):
    """Remove base facts that can be derived from the remaining ones."""
    removed = 0
    candidates = [(p, a) for p in db if p in ana.derived for a in list(db[p])]
    rng.shuffle(candidates)
    for p, a in candidates:
        if removed >= max_removals: break
        trial = copy_db(db)
        trial[p].discard(a)
        derived = forward_chain(trial, rules, ana)
        if has_fact(derived, p, a) and not check_constraints(derived, rules):
            db[p].discard(a); removed += 1
    return removed


# ═══════════════════════════════════════════════════════════════════════════
#  EVOLUTIONARY LOOP
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class Individual:
    db: FactDB
    fitness: Fitness
    strategy: str = ""
    generation: int = 0


def evolve(rules, ana, universe, n, rng,
           population_size=40, generations=5, mutation_steps=15,
           elitism=3, verbose=False):
    """Main evolutionary loop."""

    # ── Phase 1: Generate diverse initial population ──
    if verbose:
        print(f"\n  Phase 1: Generating {population_size} candidates...",
              file=sys.stderr)

    population = []
    existing_facts = [r for r in rules if not r.body and len(r.head) == 1]
    base_facts_db = new_db()
    for f in existing_facts: add_fact(base_facts_db, f.head[0].pred, f.head[0].args)

    for i in range(population_size):
        strategy = STRATEGIES[i % len(STRATEGIES)]
        # Use a different sub-seed for each candidate
        sub_rng = random.Random(rng.randint(0, 2**31))
        db = strategy(ana, rules, universe, n, sub_rng)
        # Include file-level facts
        for p, fs in base_facts_db.items():
            for a in fs: add_fact(db, p, a)
        # Light mutation
        mutate(db, ana, rules, universe, sub_rng, steps=mutation_steps)
        # Repair
        ok = repair(db, rules, ana, sub_rng)
        if not ok: continue

        fitness = evaluate_fitness(db, rules, ana)
        if fitness.violated: continue

        population.append(Individual(
            db=db, fitness=fitness,
            strategy=strategy.__name__, generation=0))

    population.sort(key=lambda ind: ind.fitness.total, reverse=True)

    if verbose:
        print(f"    Viable: {len(population)}/{population_size}", file=sys.stderr)
        if population:
            best = population[0]
            print(f"    Best: fitness={best.fitness.total:.0f} "
                  f"depth={best.fitness.max_depth} base={best.fitness.base_count} "
                  f"derived={best.fitness.derived_count} "
                  f"strat={best.strategy}", file=sys.stderr)

    # ── Phase 2: Evolutionary generations ──
    for gen in range(1, generations + 1):
        if verbose:
            print(f"\n  Generation {gen}:", file=sys.stderr)

        if len(population) < 4:
            if verbose: print("    Population too small, adding random", file=sys.stderr)
            for _ in range(10):
                s = STRATEGIES[rng.randint(0, len(STRATEGIES)-1)]
                db = s(ana, rules, universe, n, random.Random(rng.randint(0, 2**31)))
                for p, fs in base_facts_db.items():
                    for a in fs: add_fact(db, p, a)
                mutate(db, ana, rules, universe, rng, steps=mutation_steps)
                if repair(db, rules, ana, rng):
                    f = evaluate_fitness(db, rules, ana)
                    if not f.violated:
                        population.append(Individual(db=db, fitness=f, generation=gen))

        offspring = []

        # Elitism: keep top individuals
        elite = population[:elitism]

        # Tournament selection + crossover
        num_offspring = population_size - elitism
        for _ in range(num_offspring):
            # Tournament: pick 3, take best
            if len(population) < 3: break
            tournament = rng.sample(population, min(3, len(population)))
            tournament.sort(key=lambda ind: ind.fitness.total, reverse=True)
            p1 = tournament[0]

            tournament2 = rng.sample(population, min(3, len(population)))
            tournament2.sort(key=lambda ind: ind.fitness.total, reverse=True)
            p2 = tournament2[0]

            # Crossover
            child_db = crossover(p1.db, p2.db, rng)

            # Mutation (light)
            mutate(child_db, ana, rules, universe, rng, steps=mutation_steps)

            # Repair
            if not repair(child_db, rules, ana, rng):
                continue

            fitness = evaluate_fitness(child_db, rules, ana)
            if fitness.violated: continue

            offspring.append(Individual(
                db=child_db, fitness=fitness,
                strategy=f"cross({p1.strategy[:4]},{p2.strategy[:4]})",
                generation=gen))

        # Also inject fresh random individuals for diversity
        for _ in range(max(2, population_size // 5)):
            s = STRATEGIES[rng.randint(0, len(STRATEGIES)-1)]
            db = s(ana, rules, universe, n, random.Random(rng.randint(0, 2**31)))
            for p, fs in base_facts_db.items():
                for a in fs: add_fact(db, p, a)
            mutate(db, ana, rules, universe, rng, steps=mutation_steps)
            if repair(db, rules, ana, rng):
                f = evaluate_fitness(db, rules, ana)
                if not f.violated:
                    offspring.append(Individual(db=db, fitness=f,
                                               strategy=s.__name__, generation=gen))

        # Merge and select
        population = elite + offspring
        population.sort(key=lambda ind: ind.fitness.total, reverse=True)
        population = population[:population_size]

        if verbose and population:
            b = population[0]
            print(f"    Best: fitness={b.fitness.total:.0f} "
                  f"depth={b.fitness.max_depth} base={b.fitness.base_count} "
                  f"derived={b.fitness.derived_count} amp={b.fitness.amplification:.1f} "
                  f"strat={b.strategy}", file=sys.stderr)
            # Diversity report
            depths = [ind.fitness.max_depth for ind in population[:10]]
            bases = [ind.fitness.base_count for ind in population[:10]]
            print(f"    Top 10 depths: {depths}", file=sys.stderr)
            print(f"    Top 10 bases:  {bases}", file=sys.stderr)

    if not population:
        return None

    return population[0]


# ═══════════════════════════════════════════════════════════════════════════
#  OUTPUT
# ═══════════════════════════════════════════════════════════════════════════

def format_asp(db, ana):
    lines = ["% === BASE FACTS (evolved) ===", ""]
    # When pure_base is non-empty, only output those.
    # When pure_base is empty (all preds recursive, e.g. NoRa),
    # output all preds in the db (the strategies only seed safe preds).
    output_preds = ana.pure_base if ana.pure_base else set(db.keys())
    for pred in sorted(output_preds):
        facts = sorted(db.get(pred, set()))
        if not facts: continue
        lines.append(f"% {pred}")
        for args in facts: lines.append(f"{pred}({','.join(args)}).")
        lines.append("")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Evolutionary population-based ASP graph sampler")
    parser.add_argument("rules_file")
    parser.add_argument("num_vertices", type=int)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--population", type=int, default=40,
                        help="Population size (default: 40)")
    parser.add_argument("--generations", type=int, default=5,
                        help="Number of generations (default: 5)")
    parser.add_argument("--mutation", type=int, default=15,
                        help="Mutation steps per candidate (default: 15)")
    parser.add_argument("--output", "-o", type=str, default=None)
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--viz", type=str, default=None)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    with open(args.rules_file) as f: program_text = f.read()

    if args.verbose: print(f"Parsing {args.rules_file}...", file=sys.stderr)
    rules, facts = parse_program(program_text)
    ana = analyze(rules, facts)

    if args.verbose:
        print(f"  {len(rules)} rules, pure_base={sorted(ana.pure_base)}", file=sys.stderr)
        print(f"  Symmetric: {sorted(ana.symmetric)}", file=sys.stderr)
        print(f"  Join patterns: {len(ana.join_patterns)}", file=sys.stderr)

    universe = generate_universe(args.num_vertices, ana, facts)
    if args.verbose:
        for cid, pool in sorted(universe.items()):
            print(f"  Type class {cid}: {len(pool)} constants", file=sys.stderr)

    # Run evolution
    winner = evolve(rules, ana, universe, args.num_vertices, rng,
                    population_size=args.population,
                    generations=args.generations,
                    mutation_steps=args.mutation,
                    verbose=args.verbose)

    if winner is None:
        print("ERROR: no viable candidates found", file=sys.stderr)
        sys.exit(1)

    # Final minimization
    if args.verbose:
        print(f"\n  Final minimization...", file=sys.stderr)
    removed = minimize(winner.db, rules, ana, rng)
    final_fitness = evaluate_fitness(winner.db, rules, ana)

    if args.verbose:
        print(f"  Removed {removed} derivable base facts", file=sys.stderr)
        print(f"\n=== FINAL RESULT ===", file=sys.stderr)
        print(f"  Fitness: {final_fitness.total:.0f}", file=sys.stderr)
        print(f"  Base: {final_fitness.base_count}  Derived: {final_fitness.derived_count}",
              file=sys.stderr)
        print(f"  Max depth: {final_fitness.max_depth}  Avg depth: {final_fitness.avg_depth:.2f}",
              file=sys.stderr)
        print(f"  Deep(≥3): {final_fitness.deep3}  Deep(≥5): {final_fitness.deep5}",
              file=sys.stderr)
        print(f"  Active preds: {final_fitness.active_preds}  Rules: {final_fitness.active_rules}",
              file=sys.stderr)
        print(f"  Amplification: {final_fitness.amplification:.1f}x", file=sys.stderr)
        print(f"  Strategy: {winner.strategy}  Gen: {winner.generation}", file=sys.stderr)

    # Output
    report = [
        "% ═══════════════════════════════════════════",
        "% EVOLUTIONARY SAMPLER",
        "% ═══════════════════════════════════════════",
        f"% fitness: {final_fitness.total:.0f}",
        f"% base_facts: {final_fitness.base_count}",
        f"% derived: {final_fitness.derived_count}",
        f"% max_depth: {final_fitness.max_depth}",
        f"% avg_depth: {final_fitness.avg_depth:.2f}",
        f"% deep_3plus: {final_fitness.deep3}",
        f"% deep_5plus: {final_fitness.deep5}",
        f"% active_preds: {final_fitness.active_preds}",
        f"% active_rules: {final_fitness.active_rules}",
        f"% amplification: {final_fitness.amplification:.1f}x",
        f"% strategy: {winner.strategy}",
        f"% generation: {winner.generation}",
    ]

    output = "\n".join(report) + "\n\n" + format_asp(winner.db, ana)

    if args.output:
        with open(args.output, "w") as f: f.write(output)
        if args.verbose: print(f"Written to {args.output}", file=sys.stderr)
    else:
        print(output)

    if args.viz:
        import asp_viz
        derived = forward_chain(winner.db, rules, ana)
        asp_viz.visualize_db(derived, args.viz,
                             title=f"Evolved Graph — {args.rules_file}",
                             base_preds=ana.seedable, derived_preds=ana.derived)
        if args.verbose: print(f"Viz written to {args.viz}", file=sys.stderr)


if __name__ == "__main__":
    main()
