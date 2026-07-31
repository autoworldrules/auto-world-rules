#!/usr/bin/env python3
"""
Atlas Sampler — Advanced General ASP Graph Sampler
====================================================

Hybrid sampler combining the best ideas from v2/evo/motif/backward with
new techniques targeting GNN difficulty.  Works with all rule types:
normal, NAF, choice rules.

Strategy:
  Phase 1 — Analyse rules: type classes, seedable preds, constraints,
            derivation dependency graph, target predicates (deep).
  Phase 2 — Build a SKELETON: pick a deep target predicate, trace
            backward through rules to find what base facts are needed.
  Phase 3 — FLESH OUT: add the required base facts (constraint-aware),
            then add diverse "distractor" edges for GNN difficulty.
  Phase 4 — SCORE & SELECT: forward chain, score by depth×diversity,
            keep the best across multiple candidates.
  Phase 5 — REFINE: targeted mutations (add/remove/swap) with
            constraint checking, hill-climb for 20 iterations.

Key GNN-difficulty heuristics:
  - Maximise derivation DEPTH (long message-passing chains)
  - Maximise predicate DIVERSITY (force multi-relational reasoning)
  - Add DISTRACTORS (edges that look useful but aren't in any proof)
  - Create AMBIGUITY (multiple plausible derivation paths)

Usage:
    python3 atlas_sampler.py rules.lp 6 --seed 42
    python3 atlas_sampler.py spynet_rules.lp 8 --seed 99 --output graph.lp
    python3 atlas_sampler.py rules.lp 6 --candidates 30 --refine 25
"""

import argparse, collections, copy, math, os, random, re, sys
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple

# ═══════════════════════════════════════════════════════════════════════════
#  ASP PARSER (shared with other samplers)
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class Atom:
    pred: str; args: Tuple[str, ...]
    def __hash__(self): return hash((self.pred, self.args))
    def __eq__(self, o): return self.pred == o.pred and self.args == o.args

@dataclass
class Literal:
    atom: Optional[Atom]; negated: bool = False
    ineq_left: str = ""; ineq_right: str = ""

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
    def inequalities(self): return [l for l in self.body if l.ineq_left]

def is_variable(s): return bool(s) and s[0].isupper()
def resolve(b, a): return b.get(a, a) if is_variable(a) else a

def _pa(t):
    t = t.strip()
    if not t or t[0].isupper() or t[0] == '_': return None
    m = re.match(r'([a-z][a-zA-Z0-9_]*)\(([^)]*)\)', t)
    if not m: return Atom(pred=t, args=(t, t)) if re.match(r'^[a-z]', t) else None
    args = tuple(a.strip() for a in m.group(2).split(',') if a.strip())
    if len(args) == 1: args = (args[0], args[0])
    return Atom(pred=m.group(1), args=args)

def _sop(text, sep=','):
    parts = []; depth = 0; cur = []
    for ch in text:
        if ch == '(': depth += 1
        elif ch == ')': depth -= 1
        elif ch == sep and depth == 0:
            parts.append(''.join(cur).strip()); cur = []; continue
        cur.append(ch)
    r = ''.join(cur).strip()
    if r: parts.append(r)
    return parts

def _pb(text):
    lits = []
    for part in _sop(text):
        part = part.strip()
        if not part: continue
        if '!=' in part:
            sides = part.split('!=')
            lits.append(Literal(atom=None, ineq_left=sides[0].strip(), ineq_right=sides[1].strip()))
        elif part.startswith('not '):
            a = _pa(part[4:].strip())
            if a: lits.append(Literal(atom=a, negated=True))
        else:
            a = _pa(part)
            if a: lits.append(Literal(atom=a, negated=False))
    return lits

def _ph(text):
    text = text.strip(); ic = text.startswith('{')
    if ic: text = text[1:]
    if '}' in text: text = text[:text.rindex('}')]
    if ';' in text:
        norm = []; d = 0
        for ch in text:
            if ch == '(': d += 1
            elif ch == ')': d -= 1
            elif ch == ';' and d == 0: norm.append(','); continue
            norm.append(ch)
        text = ''.join(norm)
    atoms = [_pa(a.strip()) for a in _sop(text)]
    return [a for a in atoms if a], ic

def parse_program(text):
    lines = text.split('\n')
    cleaned = [l[:l.find('%')] if '%' in l else l for l in lines]
    text = ' '.join(cleaned); rules = []; facts = []; idx = 0
    for part in text.split('.'):
        part = part.strip()
        if not part: continue
        if part.startswith(':-'):
            rules.append(Rule(head=[], body=_pb(part[2:].strip()), is_constraint=True, index=idx)); idx += 1
        elif ':-' in part:
            ht, bt = part.split(':-', 1); atoms, ic = _ph(ht.strip())
            rules.append(Rule(head=atoms, body=_pb(bt.strip()), is_choice=ic, index=idx)); idx += 1
        else:
            a = _pa(part)
            if a: facts.append(Rule(head=[a], body=[], index=idx)); idx += 1
    return rules, facts

# ═══════════════════════════════════════════════════════════════════════════
#  FACT DB
# ═══════════════════════════════════════════════════════════════════════════

FactDB = Dict[str, Set[Tuple[str, ...]]]
def new_db(): return collections.defaultdict(set)
def copy_db(db):
    c = new_db()
    for p, fs in db.items(): c[p] = set(fs)
    return c
def add_fact(db, p, a): db[p].add(a); return True
def has_fact(db, p, a): return a in db.get(p, set())
def db_size(db): return sum(len(fs) for fs in db.values())

# ═══════════════════════════════════════════════════════════════════════════
#  ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════

class UnionFind:
    def __init__(self): self.p = {}; self.r = {}
    def find(self, x):
        self.p.setdefault(x, x); self.r.setdefault(x, 0)
        while self.p[x] != x: self.p[x] = self.p[self.p[x]]; x = self.p[x]
        return x
    def union(self, a, b):
        a, b = self.find(a), self.find(b)
        if a == b: return
        if self.r[a] < self.r[b]: a, b = b, a
        self.p[b] = a
        if self.r[a] == self.r[b]: self.r[a] += 1
    def classes(self):
        out = collections.defaultdict(set)
        for x in self.p: out[self.find(x)].add(x)
        return out

@dataclass
class Analysis:
    pred_arity: Dict[str, int]
    seedable: Set[str]
    derived: Set[str]
    slot_to_class: Dict[Tuple, int]
    type_classes: Dict[int, Set]
    strata: Dict[str, int]
    dep_graph: Dict[str, Set[str]]
    symmetric: Set[str]
    join_patterns: List[Tuple]
    rule_constants: Set[str]
    rc_slots: Set[Tuple]
    no_self: Set[str]
    functional: Dict[str, int]
    unique_val: Dict[str, int]
    deep_targets: List[str]    # predicates with highest strata (hardest to derive)
    self_ref: Set[str]         # predicates where both args are always same (unary semantics)


def analyze(rules, facts):
    pred_arity = {}; head_preds = set(); body_preds = set()
    for r in rules:
        for a in r.head: head_preds.add(a.pred); pred_arity[a.pred] = len(a.args)
        for l in r.body:
            if l.atom: body_preds.add(l.atom.pred); pred_arity[l.atom.pred] = len(l.atom.args)
    for f in facts: pred_arity[f.head[0].pred] = len(f.head[0].args)
    fact_preds = {f.head[0].pred for f in facts}

    # Symmetric base detection
    symmetric = set()
    for p in (body_preds & head_preds):
        rr = [r for r in rules if not r.is_constraint and r.head and r.head[0].pred == p]
        if not rr: continue
        all_sym = all(
            len(r.positive_body) == 1 and r.positive_body[0].atom
            and r.positive_body[0].atom.pred == p
            and len(r.head[0].args) == 2 and len(r.positive_body[0].atom.args) == 2
            and r.head[0].args == (r.positive_body[0].atom.args[1], r.positive_body[0].atom.args[0])
            for r in rr)
        if all_sym: symmetric.add(p)

    pure_base = (body_preds | fact_preds) - head_preds
    seedable = (set(pure_base) | symmetric) - fact_preds

    # SCC fallback if seedable is empty
    if not seedable:
        dep_raw = collections.defaultdict(set)
        fanout = collections.Counter()
        for r in rules:
            if r.is_constraint: continue
            for ha in r.head:
                for l in r.positive_body:
                    if l.atom: dep_raw[ha.pred].add(l.atom.pred)
            for l in r.positive_body:
                if l.atom: fanout[l.atom.pred] += 1
        # Tarjan SCC
        all_p = set(dep_raw.keys())
        for vs in dep_raw.values(): all_p |= vs
        idx_c = [0]; stk = []; ons = set()
        ix = {}; ll = {}; sccs = []
        old_lim = sys.getrecursionlimit()
        sys.setrecursionlimit(max(5000, len(all_p) * 3))
        def _scc(v):
            ix[v] = ll[v] = idx_c[0]; idx_c[0] += 1
            stk.append(v); ons.add(v)
            for w in dep_raw.get(v, set()):
                if w not in ix: _scc(w); ll[v] = min(ll[v], ll[w])
                elif w in ons: ll[v] = min(ll[v], ix[w])
            if ll[v] == ix[v]:
                sc = set()
                while True:
                    w = stk.pop(); ons.discard(w); sc.add(w)
                    if w == v: break
                sccs.append(sc)
        for v in all_p:
            if v not in ix: _scc(v)
        sys.setrecursionlimit(old_lim)
        has_simple = set()
        for r in rules:
            if r.is_constraint: continue
            pb = r.positive_body
            if len(pb) == 1 and len(r.head) == 1:
                has_simple.add(r.head[0].pred); has_simple.add(pb[0].atom.pred)
        for scc in sccs:
            bm = [(p, fanout[p]) for p in scc if fanout[p] > 0 and p in has_simple]
            if not bm: continue
            bm.sort(key=lambda x: -x[1])
            take = max(2, len(scc) // 8)
            for p, _ in bm[:take]: seedable.add(p)
        seedable = {p for p in seedable
                    if not p.startswith('no_') and not p.startswith('not_')
                    and p not in ('is_person','is_place','is_agent','is_asset',
                                  'is_level','living_in_same_place')}
        seedable -= fact_preds

    # Type inference
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

    # Stratification
    dep = collections.defaultdict(set)
    strata = {p: 0 for p in pure_base | fact_preds | symmetric}
    for r in rules:
        if r.is_constraint: continue
        for ha in r.head:
            for l in r.body:
                if l.atom: dep[ha.pred].add(l.atom.pred)
    for _ in range(len(pred_arity) + 2):
        ch = False
        for r in rules:
            if r.is_constraint: continue
            for ha in r.head:
                ms = max((strata.get(l.atom.pred, 0) + (1 if l.negated else 0)
                          for l in r.body if l.atom), default=0)
                if ms > strata.get(ha.pred, -1): strata[ha.pred] = ms; ch = True
        if not ch: break

    # Deep targets: predicates farthest from seedable in dep graph
    # Use BFS distance from seedable set
    dep_dist = {p: 0 for p in seedable}
    queue = list(seedable); visited = set(seedable)
    # Reverse dep graph: body_pred → head_preds
    rev_dep = collections.defaultdict(set)
    for h, bs in dep.items():
        for b in bs: rev_dep[b].add(h)
    while queue:
        p = queue.pop(0)
        for hp in rev_dep.get(p, set()):
            if hp not in visited:
                visited.add(hp)
                dep_dist[hp] = dep_dist[p] + 1
                queue.append(hp)

    # Also use strata as a secondary signal
    combined_depth = {}
    for p in pred_arity:
        d1 = dep_dist.get(p, 0)
        d2 = strata.get(p, 0)
        combined_depth[p] = max(d1, d2)

    max_depth = max(combined_depth.values()) if combined_depth else 0
    deep_targets = sorted([p for p, d in combined_depth.items()
                           if d >= max(2, max_depth - 1) and pred_arity.get(p, 2) == 2],
                          key=lambda p: -combined_depth.get(p, 0))

    # Join patterns
    join_patterns = []
    for r in rules:
        if r.is_constraint or r.is_fact: continue
        pb = r.positive_body
        if len(pb) >= 2:
            pattern = [(l.atom.pred, l.atom.args) for l in pb if l.atom and l.atom.pred in seedable]
            if len(pattern) >= 2:
                join_patterns.append((r.index, pattern))

    # Rule constants
    rule_constants = set(); rc_slots = set()
    for f in facts:
        a = f.head[0]
        for i, arg in enumerate(a.args):
            if not is_variable(arg): rc_slots.add((a.pred, i)); rule_constants.add(arg)
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

    # Constraint analysis
    no_self = set(); functional = {}; unique_val = {}
    for r in rules:
        if not r.is_constraint: continue
        pos = r.positive_body
        if len(pos) == 1 and pos[0].atom and len(pos[0].atom.args) == 2:
            a = pos[0].atom
            if a.args[0] == a.args[1] and is_variable(a.args[0]):
                no_self.add(a.pred)
        if len(pos) == 2 and r.inequalities:
            a1, a2 = pos[0].atom, pos[1].atom
            if a1 and a2 and a1.pred == a2.pred and len(a1.args) == 2:
                if a1.args[0] == a2.args[0] and a1.args[1] != a2.args[1]:
                    functional[a1.pred] = 0
                elif a1.args[1] == a2.args[1] and a1.args[0] != a2.args[0]:
                    unique_val[a1.pred] = 1

    # Self-referential predicate detection: predicates where both args
    # are always the same (unary semantics stored as binary, e.g. is_female(X,X))
    self_ref = set()
    for p, ar in pred_arity.items():
        if ar != 2: continue
        all_same = True
        for r in rules:
            for a in list(r.head) + [l.atom for l in r.body if l.atom]:
                if a.pred == p and len(a.args) == 2:
                    if a.args[0] != a.args[1]:
                        all_same = False; break
            if not all_same: break
        for f in facts:
            a = f.head[0]
            if a.pred == p and len(a.args) == 2 and a.args[0] != a.args[1]:
                all_same = False
        if all_same: self_ref.add(p)

    return Analysis(
        pred_arity=pred_arity, seedable=seedable, derived=head_preds,
        slot_to_class=stc, type_classes=tc, strata=strata,
        dep_graph=dict(dep), symmetric=symmetric,
        join_patterns=join_patterns,
        rule_constants=rule_constants, rc_slots=rc_slots,
        no_self=no_self, functional=functional, unique_val=unique_val,
        deep_targets=deep_targets[:10], self_ref=self_ref)

# ═══════════════════════════════════════════════════════════════════════════
#  FORWARD CHAINER
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

def forward_chain(base_db, rules, strata):
    db = copy_db(base_db)
    depth_map = {}
    for p, fs in base_db.items():
        for a in fs: depth_map[(p, a)] = 0
    max_s = max(strata.values()) if strata else 0
    by_s = collections.defaultdict(list)
    for r in rules:
        if r.is_constraint: continue
        if r.head:
            s = max(strata.get(a.pred, 0) for a in r.head)
            by_s[s].append(r)
    for s in range(max_s + 1):
        for it in range(25):
            ch = False
            for rule in by_s.get(s, []):
                pos = rule.positive_body
                if not pos: continue
                bwf = []
                for fact in db.get(pos[0].atom.pred, set()):
                    b = unify({}, pos[0].atom.args, fact)
                    if b is not None: bwf.append((b, [(pos[0].atom.pred, fact)]))
                for lit in pos[1:]:
                    if not bwf: break
                    fp = db.get(lit.atom.pred, set())
                    if not fp: bwf = []; break
                    new = []
                    for b, bf in bwf:
                        for f in fp:
                            nb = unify(b, lit.atom.args, f)
                            if nb is not None: new.append((nb, bf + [(lit.atom.pred, f)]))
                    bwf = new
                for iq in rule.inequalities:
                    bwf = [(b, bf) for b, bf in bwf
                           if resolve(b, iq.ineq_left) != resolve(b, iq.ineq_right)]
                for n in rule.negative_body:
                    bwf = [(b, bf) for b, bf in bwf
                           if not has_fact(db, n.atom.pred,
                                          tuple(resolve(b, a) for a in n.atom.args))]
                for b, bf in bwf:
                    md = max((depth_map.get((p, a), 0) for p, a in bf), default=0) + 1
                    for ha in rule.head:
                        g = tuple(resolve(b, a) for a in ha.args)
                        if all(not is_variable(x) for x in g):
                            key = (ha.pred, g)
                            if key not in depth_map or (g not in db.get(ha.pred, set())):
                                add_fact(db, ha.pred, g)
                                ch = True
                                if key not in depth_map or md < depth_map[key]:
                                    depth_map[key] = md
            if not ch: break
    return db, depth_map

def check_constraints(db, rules):
    for r in rules:
        if not r.is_constraint: continue
        pos = r.positive_body
        if not pos: continue
        bwf = [{}]
        for lit in pos:
            if not lit.atom: continue
            new = []
            for b in bwf:
                for f in db.get(lit.atom.pred, set()):
                    nb = unify(b, lit.atom.args, f)
                    if nb is not None: new.append(nb)
            bwf = new
        for iq in r.inequalities:
            bwf = [b for b in bwf if resolve(b, iq.ineq_left) != resolve(b, iq.ineq_right)]
        for n in r.negative_body:
            bwf = [b for b in bwf
                   if not has_fact(db, n.atom.pred,
                                  tuple(resolve(b, a) for a in n.atom.args))]
        if bwf: return True
    return False

# ═══════════════════════════════════════════════════════════════════════════
#  UNIVERSE & FACT GENERATION
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


def pick_const(pred, pos, ana, universe, rng):
    if (pred, pos) in ana.rc_slots and ana.rule_constants:
        return rng.choice(sorted(ana.rule_constants))
    cls = ana.slot_to_class.get((pred, pos), 0)
    pool = universe.get(cls, ["x0"])
    return rng.choice(pool)


def safe_add(db, pred, args, ana):
    """Add fact only if it respects structural constraints."""
    if len(args) >= 2:
        # Self-referential predicates (unary semantics): both args must match
        if pred in ana.self_ref and args[0] != args[1]:
            return False
        if pred in ana.no_self and args[0] == args[1]: return False
        if pred in ana.functional:
            kp = ana.functional[pred]
            key = args[kp]
            for ex in db.get(pred, set()):
                if ex[kp] == key and ex[1-kp] != args[1-kp]: return False
        if pred in ana.unique_val:
            vp = ana.unique_val[pred]
            val = args[vp]
            for ex in db.get(pred, set()):
                if ex[vp] == val and ex[1-vp] != args[1-vp]: return False
    add_fact(db, pred, args)
    return True


def gen_fact(pred, ana, universe, rng):
    arity = ana.pred_arity.get(pred, 2)
    if pred in ana.self_ref and arity == 2:
        # Both args must be same (unary semantic)
        c = pick_const(pred, 0, ana, universe, rng)
        return (c, c)
    args = []
    for i in range(arity):
        args.append(pick_const(pred, i, ana, universe, rng))
    return tuple(args)

# ═══════════════════════════════════════════════════════════════════════════
#  SCORING (GNN-difficulty oriented)
# ═══════════════════════════════════════════════════════════════════════════

def score_graph(db, rules, ana):
    derived, depth_map = forward_chain(db, rules, ana.strata)
    if check_constraints(derived, rules):
        return -1000.0, {}, derived, depth_map

    base_count = db_size(db)
    depths = [d for d in depth_map.values() if d > 0]
    if not depths:
        return 0.0, {}, derived, depth_map

    mx = max(depths); avg = sum(depths) / len(depths)
    d3 = sum(1 for d in depths if d >= 3)
    d5 = sum(1 for d in depths if d >= 5)
    active_preds = len({p for (p, _), d in depth_map.items() if d > 0})
    amp = len(depths) / max(base_count, 1)

    # Deep target bonus: extra reward for deriving the deepest predicates
    deep_bonus = sum(15 for (p, _), d in depth_map.items()
                     if d > 0 and p in ana.deep_targets[:5])

    # Diversity: number of distinct base predicates used
    base_pred_count = len({p for p in db if db[p]})

    score = (
        mx * 50.0              # depth is king for GNN difficulty
        + avg * 20.0           # average depth
        + d3 * 8.0             # depth-3+ facts
        + d5 * 18.0            # depth-5+ facts (very hard for GNNs)
        + active_preds * 15.0  # predicate diversity
        + amp * 30.0           # amplification (inference per base fact)
        + deep_bonus           # deep target bonus
        + base_pred_count * 5.0  # base predicate diversity
        - base_count * 0.3     # penalise bloat
    )

    details = {
        "base": base_count, "derived": len(depths), "max_depth": mx,
        "avg_depth": round(avg, 2), "deep3": d3, "deep5": d5,
        "preds": active_preds, "amp": round(amp, 2),
        "base_preds": base_pred_count,
    }
    return score, details, derived, depth_map

# ═══════════════════════════════════════════════════════════════════════════
#  STRATEGY 1: TARGETED BACKWARD SEEDING
# ═══════════════════════════════════════════════════════════════════════════

def backward_seed(rules, ana, universe, n, rng):
    """Pick a deep target, trace backward to find needed base facts."""
    db = new_db()
    targets = list(ana.deep_targets) or list(ana.seedable)
    if not targets: return db

    # Pick a target and find rules that derive it
    target = rng.choice(targets[:5]) if len(targets) >= 5 else rng.choice(targets)
    rules_for = collections.defaultdict(list)
    for r in rules:
        if r.is_constraint: continue
        for a in r.head: rules_for[a.pred].append(r)

    # BFS backward: collect needed base predicates
    needed = set()
    queue = [target]
    visited = set()
    for _ in range(15):
        if not queue: break
        pred = queue.pop(0)
        if pred in visited: continue
        visited.add(pred)
        if pred in ana.seedable:
            needed.add(pred)
            continue
        for r in rules_for.get(pred, []):
            for l in r.positive_body:
                if l.atom: queue.append(l.atom.pred)

    # Generate facts for needed predicates
    for pred in needed:
        if pred not in ana.pred_arity: continue
        count = rng.randint(1, max(2, n // 2))
        for _ in range(count):
            args = gen_fact(pred, ana, universe, rng)
            safe_add(db, pred, args, ana)

    return db

# ═══════════════════════════════════════════════════════════════════════════
#  STRATEGY 2: JOIN PATTERN INJECTION
# ═══════════════════════════════════════════════════════════════════════════

def inject_joins(db, rules, ana, universe, rng, count=5):
    """Inject facts that satisfy multi-body join patterns."""
    if not ana.join_patterns: return
    for _ in range(count):
        ri, pattern = rng.choice(ana.join_patterns)
        binding = {}
        for pred, args in pattern:
            for i, a in enumerate(args):
                if is_variable(a) and a not in binding:
                    if (pred, i) in ana.rc_slots and ana.rule_constants:
                        binding[a] = rng.choice(sorted(ana.rule_constants))
                    else:
                        binding[a] = pick_const(pred, i, ana, universe, rng)
        # Satisfy inequalities
        rule = rules[ri] if ri < len(rules) else None
        if rule:
            for iq in rule.inequalities:
                l, r_ = resolve(binding, iq.ineq_left), resolve(binding, iq.ineq_right)
                if l == r_:
                    for v in [iq.ineq_right, iq.ineq_left]:
                        if is_variable(v):
                            cls = 0
                            for pred, args in pattern:
                                for i, a in enumerate(args):
                                    if a == v: cls = ana.slot_to_class.get((pred, i), 0); break
                            pool = universe.get(cls, ["x0"])
                            for _ in range(20):
                                nv = rng.choice(pool)
                                if nv != binding.get(v): binding[v] = nv; break
                            break
        for pred, args in pattern:
            if pred not in ana.seedable: continue
            g = tuple(resolve(binding, a) for a in args)
            if all(not is_variable(x) for x in g):
                if pred in ana.symmetric and len(g) == 2 and has_fact(db, pred, (g[1], g[0])): continue
                safe_add(db, pred, g, ana)

# ═══════════════════════════════════════════════════════════════════════════
#  STRATEGY 3: CHAIN BUILDING
# ═══════════════════════════════════════════════════════════════════════════

def build_chains(db, ana, universe, rng, n):
    """Build long chains for transitive/recursive predicates."""
    # Find self-dependent predicates in seedable (excl. self-ref which can't chain)
    self_dep = set()
    for p in ana.seedable:
        if p in ana.self_ref: continue  # self-ref preds can't form chains
        if p in ana.dep_graph.get(p, set()): self_dep.add(p)
    chain_preds = self_dep or {p for p in ana.seedable
                               if ana.pred_arity.get(p) == 2 and p not in ana.self_ref}
    if not chain_preds: return

    for pred in rng.sample(sorted(chain_preds), min(3, len(chain_preds))):
        cls0 = ana.slot_to_class.get((pred, 0), 0)
        cls1 = ana.slot_to_class.get((pred, 1), 0)
        if cls0 == cls1:
            pool = universe.get(cls0, ["x0"])
            if len(pool) >= 3:
                chain_len = min(rng.randint(3, max(4, n)), len(pool))
                chain = rng.sample(pool, chain_len)
                for i in range(len(chain) - 1):
                    safe_add(db, pred, (chain[i], chain[i + 1]), ana)

# ═══════════════════════════════════════════════════════════════════════════
#  STRATEGY 4: DIVERSITY SPRAY
# ═══════════════════════════════════════════════════════════════════════════

def diversity_spray(db, ana, universe, rng, n):
    """Ensure every seedable predicate has at least one fact."""
    for pred in ana.seedable:
        if pred not in ana.pred_arity: continue
        if db.get(pred): continue  # already has facts
        for _ in range(rng.randint(1, 3)):
            args = gen_fact(pred, ana, universe, rng)
            safe_add(db, pred, args, ana)

# ═══════════════════════════════════════════════════════════════════════════
#  CANDIDATE GENERATION (combines strategies)
# ═══════════════════════════════════════════════════════════════════════════

STRATEGIES = [
    # (weight, name, function)
    (3, "backward+joins", lambda db, rules, ana, u, n, rng: (
        backward_seed(rules, ana, u, n, rng),
        inject_joins(db, rules, ana, u, rng, count=n),
    )),
    (2, "joins+chains", lambda db, rules, ana, u, n, rng: (
        inject_joins(db, rules, ana, u, rng, count=n * 2),
        build_chains(db, ana, u, rng, n),
    )),
    (2, "backward+diversity", lambda db, rules, ana, u, n, rng: (
        backward_seed(rules, ana, u, n, rng),
        diversity_spray(db, ana, u, rng, n),
    )),
    (1, "chains+diversity", lambda db, rules, ana, u, n, rng: (
        build_chains(db, ana, u, rng, n),
        diversity_spray(db, ana, u, rng, n),
    )),
]


def generate_candidate(rules, ana, universe, facts, n, rng):
    """Generate one candidate graph: start small, grow with constraint checking.
    Adds facts in small batches, undoing if constraints are violated."""
    db = new_db()
    for f in facts:
        a = f.head[0]; add_fact(db, a.pred, a.args)

    # Generate a large pool of candidate facts from strategy mix
    pool_db = new_db()
    weights = [w for w, _, _ in STRATEGIES]
    _, name, fn = rng.choices(STRATEGIES, weights=weights)[0]
    result = fn(pool_db, rules, ana, universe, n, rng)
    if isinstance(result, tuple) and len(result) >= 1 and isinstance(result[0], dict):
        for p, fs in result[0].items():
            for a in fs: add_fact(pool_db, p, a)
    inject_joins(pool_db, rules, ana, universe, rng, count=n * 2)
    diversity_spray(pool_db, ana, universe, rng, n)

    candidates = [(p, a) for p in pool_db for a in pool_db[p] if p in ana.seedable]
    rng.shuffle(candidates)

    # Add facts in batches of 3, checking constraints after each batch
    batch = []
    for pred, args in candidates:
        if not safe_add(db, pred, args, ana):
            continue
        batch.append((pred, args))
        if len(batch) >= 3:
            derived, _ = forward_chain(db, rules, ana.strata)
            if check_constraints(derived, rules):
                for p, a in batch: db[p].discard(a)
            batch = []

    # Final check
    if batch:
        derived, _ = forward_chain(db, rules, ana.strata)
        if check_constraints(derived, rules):
            for p, a in batch: db[p].discard(a)

    return db

# ═══════════════════════════════════════════════════════════════════════════
#  REFINEMENT (constraint-aware hill climbing)
# ═══════════════════════════════════════════════════════════════════════════

def mutate(db, rules, ana, universe, rng):
    """One mutation step: add, remove, or swap a fact."""
    action = rng.choices(["add", "remove", "swap"], weights=[4, 2, 3])[0]

    if action == "add":
        preds = sorted(ana.seedable & set(ana.pred_arity.keys()))
        if not preds: return
        pred = rng.choice(preds)
        args = gen_fact(pred, ana, universe, rng)
        safe_add(db, pred, args, ana)

    elif action == "remove":
        removable = [(p, a) for p in ana.seedable for a in db.get(p, set())]
        if removable:
            p, a = rng.choice(removable)
            db[p].discard(a)

    elif action == "swap":
        removable = [(p, a) for p in ana.seedable for a in db.get(p, set())]
        if removable:
            p, a = rng.choice(removable)
            db[p].discard(a)
            new_args = gen_fact(p, ana, universe, rng)
            safe_add(db, p, new_args, ana)


def refine(db, rules, ana, universe, rng, steps=20):
    """Hill-climb: mutate and keep if score improves."""
    best_score, best_det, _, _ = score_graph(db, rules, ana)
    if best_score < 0:
        # Try to repair
        for _ in range(steps):
            mutate(db, rules, ana, universe, rng)
            sc, det, _, _ = score_graph(db, rules, ana)
            if sc > best_score:
                best_score = sc; best_det = det
                if sc >= 0: break
        if best_score < 0: return best_score, best_det

    for _ in range(steps):
        trial = copy_db(db)
        for _ in range(rng.randint(1, 3)):
            mutate(trial, rules, ana, universe, rng)
        sc, det, _, _ = score_graph(trial, rules, ana)
        if sc > best_score:
            # Accept
            for p in list(db.keys()): db[p] = set()
            for p, fs in trial.items(): db[p] = set(fs)
            best_score = sc; best_det = det

    return best_score, best_det

# ═══════════════════════════════════════════════════════════════════════════
#  MAIN SAMPLING LOOP
# ═══════════════════════════════════════════════════════════════════════════

def sample(rules_file, n, seed=None, candidates=20, refine_steps=25,
           verbose=False):
    """Main entry point: generate and return the best graph."""
    with open(rules_file) as f:
        rules_text = f.read()
    rules, facts = parse_program(rules_text)
    ana = analyze(rules, facts)

    if verbose:
        print(f"  Atlas sampler: {len(rules)} rules, "
              f"seedable={sorted(ana.seedable)[:6]}{'...' if len(ana.seedable)>6 else ''}",
              file=sys.stderr)
        print(f"  Deep targets: {ana.deep_targets[:5]}", file=sys.stderr)
        print(f"  Constraints: no_self={sorted(ana.no_self)[:3]}, "
              f"functional={list(ana.functional.keys())[:3]}", file=sys.stderr)

    rng = random.Random(seed)
    universe = generate_universe(n, ana, facts)

    best_db = None; best_score = -9999; best_details = {}

    for ci in range(candidates):
        sub_rng = random.Random(rng.randint(0, 2**31))
        db = generate_candidate(rules, ana, universe, facts, n, sub_rng)

        # Refine
        sc, det = refine(db, rules, ana, universe, sub_rng, steps=refine_steps)

        if verbose and ci < 5:
            print(f"    Candidate {ci}: score={sc:.0f} {det}", file=sys.stderr)

        if sc > best_score:
            best_score = sc
            best_db = copy_db(db)
            best_details = det

    if verbose:
        print(f"  Best: score={best_score:.0f} {best_details}", file=sys.stderr)

    return best_db, best_details, ana


def format_asp(db, ana):
    lines = ["% === BASE FACTS (atlas sampler) ===", ""]
    output_preds = ana.seedable if ana.seedable else set(db.keys())
    for pred in sorted(output_preds):
        fs = sorted(db.get(pred, set()))
        if not fs: continue
        lines.append(f"% {pred}")
        for args in fs: lines.append(f"{pred}({','.join(args)}).")
        lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Atlas sampler: advanced general ASP graph sampler")
    parser.add_argument("rules_file", help="ASP rules file (.lp)")
    parser.add_argument("num_vertices", type=int, help="Target number of entity vertices")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--candidates", type=int, default=20,
                        help="Number of candidate graphs to generate (default: 20)")
    parser.add_argument("--refine", type=int, default=25,
                        help="Hill-climbing refinement steps per candidate (default: 25)")
    parser.add_argument("--output", "-o", type=str, default=None)
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    if args.seed is None:
        args.seed = random.randint(0, 2**31)

    best_db, details, ana = sample(
        args.rules_file, args.num_vertices,
        seed=args.seed, candidates=args.candidates,
        refine_steps=args.refine, verbose=args.verbose)

    if best_db is None or db_size(best_db) == 0:
        print("ERROR: no viable graph found", file=sys.stderr)
        sys.exit(1)

    output = format_asp(best_db, ana)
    if args.output:
        with open(args.output, "w") as f: f.write(output)
        if args.verbose: print(f"Written to {args.output}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
