#!/usr/bin/env python3
"""
Backward Proof-Planning ASP Sampler (v2 — fast, SCC-aware)
===========================================================
Works with highly circular rule sets like NoRa (291 rules, 51-pred SCC).

Key improvements over v1:
1. SCC-AWARE RECURSION: Detects strongly connected components in the rule
   dependency graph. Within an SCC, allows max 2 hops before treating a
   predicate as a leaf — breaking circular dependencies.
2. INLINED FORWARD CHAINER: No subprocess calls. Rules parsed once.
3. SEEDABLE DETECTION: Automatically identifies which predicates can serve
   as base facts, even when pure_base is empty.
4. POPULATION SAMPLING: Generates multiple skeleton configurations and
   picks the best by true depth scoring.

Usage:
    python3 backward_sampler.py rules.lp 6 --seed 42 --output graph.lp
    python3 backward_sampler.py nora_rules.lp 6 --seed 42 --population 20 -v
"""

import argparse, collections, copy, math, os, random, re, sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

# ═══════════════════════════════════════════════════════════════════════════
#  ASP ENGINE (inlined — no subprocess)
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
def new_db(): return collections.defaultdict(set)
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

# ── Parser ───────────────────────────────────────────────────────────────

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

# ── Forward chainer (inlined, with depth tracking) ───────────────────────

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
        new = []
        for b in bindings:
            bp = [(i, a) for i, a in enumerate(lit.atom.args) if is_variable(a) and a in b]
            if bp:
                idx = collections.defaultdict(list)
                for f in fp: idx[tuple(f[i] for i, _ in bp)].append(f)
                for f in idx.get(tuple(b[v] for _, v in bp), []):
                    nb = unify(b, lit.atom.args, f)
                    if nb is not None: new.append(nb)
            else:
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

def forward_chain_depth(base_db, rules, strata):
    """Forward-chain with depth tracking. Returns (derived_db, depth_map)."""
    db = copy_db(base_db)
    depth_map = {(p, a): 0 for p in base_db for a in base_db[p]}
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
            for r in by_s.get(s, []):
                pos = r.positive_body
                if not pos: continue
                bd = []
                for fact in db.get(pos[0].atom.pred, set()):
                    b = unify({}, pos[0].atom.args, fact)
                    if b is not None: bd.append((b, depth_map.get((pos[0].atom.pred, fact), 0)))
                for lit in pos[1:]:
                    if not bd: break
                    fp = db.get(lit.atom.pred, set())
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
                          if not has_fact(db, neg.atom.pred,
                                         tuple(resolve(b, a) for a in neg.atom.args))]
                for b, md in bd:
                    for ha in r.head:
                        g = tuple(resolve(b, a) for a in ha.args)
                        if all(not is_variable(x) for x in g):
                            nd = md + 1; key = (ha.pred, g)
                            if add_fact(db, ha.pred, g):
                                ch = True; depth_map[key] = nd
                            elif key in depth_map and nd < depth_map[key]:
                                depth_map[key] = nd
            if not ch: break
    return db, depth_map

def check_constraints(db, rules):
    for r in rules:
        if not r.is_constraint: continue
        dummy = Rule(head=[Atom("__c__", ("x","x"))], body=r.body, index=999)
        if evaluate_rule(dummy, db): return True
    return False

# ═══════════════════════════════════════════════════════════════════════════
#  RULE ANALYSIS WITH SCC DETECTION
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class Analysis:
    pred_arity: Dict[str, int]
    strata: Dict[str, int]
    rules_for: Dict[str, List[int]]
    seedable: Set[str]
    scc_id: Dict[str, int]
    dep_graph: Dict[str, Set[str]]
    rule_constants: Set[str]
    rc_slots: Set[Tuple[str, int]]
    no_self: Set[str]             # predicates with :- p(X,X)
    functional: Dict[str, int]    # pred → key position (:- p(X,Y1), p(X,Y2), Y1!=Y2)
    unique_val: Dict[str, int]    # pred → val position (:- p(X1,Y), p(X2,Y), X1!=X2)
    self_ref: Set[str] = field(default_factory=set)  # binary preds always used as p(X,X)

def analyze(rules, facts):
    pred_arity = {}; head_preds = set(); body_preds = set()
    for r in rules:
        for a in r.head: head_preds.add(a.pred); pred_arity[a.pred] = len(a.args)
        for l in r.body:
            if l.atom: body_preds.add(l.atom.pred); pred_arity[l.atom.pred] = len(l.atom.args)
    for f in facts: pred_arity[f.head[0].pred] = len(f.head[0].args)

    # Dependency graph
    dep = collections.defaultdict(set)
    for r in rules:
        if r.is_constraint: continue
        for ha in r.head:
            for l in r.positive_body:
                if l.atom: dep[ha.pred].add(l.atom.pred)

    # SCC detection (Tarjan's)
    all_preds = set(dep.keys())
    for vs in dep.values(): all_preds |= vs
    idx_c = [0]; stack = []; on_stack = set()
    index = {}; lowlink = {}; sccs = []; scc_id = {}
    sys.setrecursionlimit(max(5000, len(all_preds) * 3))
    def sc(v):
        index[v] = lowlink[v] = idx_c[0]; idx_c[0] += 1
        stack.append(v); on_stack.add(v)
        for w in dep.get(v, set()):
            if w not in index: sc(w); lowlink[v] = min(lowlink[v], lowlink[w])
            elif w in on_stack: lowlink[v] = min(lowlink[v], index[w])
        if lowlink[v] == index[v]:
            scc = set()
            while True:
                w = stack.pop(); on_stack.discard(w); scc.add(w)
                if w == v: break
            sid = len(sccs); sccs.append(scc)
            for p in scc: scc_id[p] = sid
    for v in all_preds:
        if v not in index: sc(v)

    # Body fan-out
    fanout = collections.Counter()
    for r in rules:
        if r.is_constraint: continue
        for l in r.positive_body:
            if l.atom: fanout[l.atom.pred] += 1

    # Seedable: predicates safe to state as base facts.
    # Key insight: NOT all body predicates are safe. Derived predicates like
    # no_sons, aunt_or_uncle_of, maternal_grandparent_of should NEVER be
    # stated as base facts — they must be derived through the rules.
    #
    # A predicate P is safe to seed if:
    # 1. It's pure_base (never in any head), OR
    # 2. It has at least one rule "P(X,Y) :- Q(X,Y)" with exactly 1 positive
    #    body literal (simple alias/conversion — these are the "atomic" layer).
    # AND it's not a closed-world assumption (no_*, not_*).

    pure_base = body_preds - head_preds
    seedable = set(pure_base)

    # Detect symmetric base predicates
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
    seedable |= symmetric_base

    # Only expand via SCC analysis if seedable is still empty
    if not seedable:
        # Find predicates with at least one 1-body derivation rule
        has_simple_rule = set()
        for r in rules:
            if r.is_constraint: continue
            pb = r.positive_body
            if len(pb) == 1 and len(r.head) == 1:
                has_simple_rule.add(r.head[0].pred)
                has_simple_rule.add(pb[0].atom.pred)

        for scc in sccs:
            body_members = [(p, fanout[p]) for p in scc
                            if fanout[p] > 0 and p in has_simple_rule]
            if not body_members: continue
            body_members.sort(key=lambda x: -x[1])
            take = max(2, len(scc) // 8)
            for p, _ in body_members[:take]:
                seedable.add(p)

    # Filter out unsafe predicates
    unsafe_prefixes = ('no_', 'not_')
    unsafe_preds = {'is_person', 'is_place', 'living_in_same_place'}
    fact_preds = {f.head[0].pred for f in facts}
    seedable = {p for p in seedable
                if not any(p.startswith(pfx) for pfx in unsafe_prefixes)
                and p not in unsafe_preds}
    seedable -= fact_preds

    # Rules-for index
    rules_for = collections.defaultdict(list)
    for r in rules:
        if r.is_constraint: continue
        for a in r.head: rules_for[a.pred].append(r.index)

    # Stratification
    fact_preds = {f.head[0].pred for f in facts}
    strata = {p: 0 for p in body_preds | fact_preds | head_preds}
    for _ in range(len(pred_arity) + 2):
        ch = False
        for r in rules:
            if r.is_constraint: continue
            for ha in r.head:
                ms = max((strata.get(l.atom.pred, 0) + (1 if l.negated else 0)
                          for l in r.body if l.atom), default=0)
                if ms > strata.get(ha.pred, -1): strata[ha.pred] = ms; ch = True
        if not ch: break

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

    # ── Constraint analysis ──
    # Detect structural constraints for safe fact generation
    no_self = set()       # predicates with :- p(X,X)
    functional = {}       # pred → key_position
    unique_val = {}       # pred → val_position
    for r in rules:
        if not r.is_constraint: continue
        pos = r.positive_body
        # :- p(X,X) → no self-loops
        if len(pos) == 1 and pos[0].atom and len(pos[0].atom.args) == 2:
            a = pos[0].atom
            if a.args[0] == a.args[1] and is_variable(a.args[0]):
                no_self.add(a.pred)
        # :- p(X,Y1), p(X,Y2), Y1 != Y2 → functional on position 0
        # :- p(X1,Y), p(X2,Y), X1 != X2 → unique on position 1
        if len(pos) == 2 and r.inequalities:
            a1, a2 = pos[0].atom, pos[1].atom
            if a1 and a2 and a1.pred == a2.pred and len(a1.args) == 2:
                p = a1.pred
                # Check which position is shared (key) vs different (ineq)
                if a1.args[0] == a2.args[0] and a1.args[1] != a2.args[1]:
                    functional[p] = 0  # key is position 0
                elif a1.args[1] == a2.args[1] and a1.args[0] != a2.args[0]:
                    unique_val[p] = 1  # unique on position 1

    # Self-referential predicates: binary preds where BOTH args are ALWAYS
    # the same variable/constant (e.g. is_female(X,X), captured(X,X) in SpyNet)
    self_ref = set()
    for p, ar in pred_arity.items():
        if ar != 2: continue
        always_same = True
        seen_any = False
        for r in rules:
            for a in list(r.head) + [l.atom for l in r.body if l.atom]:
                if a.pred == p and len(a.args) == 2:
                    seen_any = True
                    if a.args[0] != a.args[1]:
                        always_same = False; break
            if not always_same: break
        for f in facts:
            a = f.head[0]
            if a.pred == p and len(a.args) == 2 and a.args[0] != a.args[1]:
                always_same = False
        if seen_any and always_same:
            self_ref.add(p)

    return Analysis(pred_arity=pred_arity, strata=strata,
                    rules_for=dict(rules_for), seedable=seedable,
                    scc_id=scc_id, dep_graph=dict(dep),
                    rule_constants=rule_constants, rc_slots=rc_slots,
                    no_self=no_self, functional=functional,
                    unique_val=unique_val, self_ref=self_ref)

# ═══════════════════════════════════════════════════════════════════════════
#  SCC-AWARE SKELETON ENUMERATION
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class SkNode:
    rule_index: int   # -1 = leaf
    pred: str
    children: list
    depth: int = 0
    is_leaf: bool = False

def enumerate_skeletons(rules, ana, max_depth=6, max_skeletons=100, rng=None):
    """SCC-aware skeleton enumeration.
    Within an SCC, allows max 2 hops before forcing a leaf.
    Between SCCs, allows full depth."""
    if rng is None: rng = random.Random(42)
    skeletons = []; seen = set()

    def build(pred, depth, scc_hops, visited_rules):
        if depth > max_depth:
            # Can only be a leaf if seedable
            if pred in ana.seedable:
                return SkNode(-1, pred, [], 0, True)
            return None

        # Force leaf if seedable and we've gone deep enough
        if pred in ana.seedable and (depth > 0 or scc_hops > 0):
            return SkNode(-1, pred, [], 0, True)
        if scc_hops >= 2 and pred in ana.seedable:
            return SkNode(-1, pred, [], 0, True)
        if scc_hops >= 3:
            # Can only be a leaf if seedable — otherwise this branch fails
            if pred in ana.seedable:
                return SkNode(-1, pred, [], 0, True)
            return None

        cands = ana.rules_for.get(pred, [])
        if not cands:
            # No derivation rules — only valid as leaf if seedable
            if pred in ana.seedable:
                return SkNode(-1, pred, [], 0, True)
            return None

        rng.shuffle(cands)
        for ri in cands:
            if ri in visited_rules: continue
            rule = rules[ri]
            pb = rule.positive_body
            if not pb: continue

            children = []; max_cd = 0; ok = True
            for lit in pb:
                if not lit.atom: continue
                bp = lit.atom.pred

                # Track SCC hops
                same_scc = (ana.scc_id.get(bp, -1) == ana.scc_id.get(pred, -2))
                new_hops = (scc_hops + 1) if same_scc else 0

                child = build(bp, depth + 1, new_hops, visited_rules | {ri})
                if child is None:
                    # Can't build this branch — try as leaf
                    child = SkNode(-1, bp, [], 0, True)
                children.append(child)
                max_cd = max(max_cd, child.depth)

            if children:
                return SkNode(ri, pred, children, max_cd + 1)

        # No rule worked
        return SkNode(-1, pred, [], 0, True)

    # Enumerate from high-strata predicates
    sorted_preds = sorted(ana.pred_arity.keys(),
                          key=lambda p: ana.strata.get(p, 0), reverse=True)

    for pred in sorted_preds:
        if len(skeletons) >= max_skeletons: break
        for _ in range(3):
            sk = build(pred, 0, 0, set())
            if sk and sk.depth >= 2:
                sig = _sig(sk)
                if sig not in seen:
                    seen.add(sig); skeletons.append(sk)
                    break

    skeletons.sort(key=lambda s: s.depth, reverse=True)
    return skeletons

def _sig(node):
    if node.is_leaf: return (node.pred, "L")
    return (node.pred, node.rule_index, tuple(_sig(c) for c in node.children))

# ═══════════════════════════════════════════════════════════════════════════
#  INSTANTIATION + GRAPH ASSEMBLY
# ═══════════════════════════════════════════════════════════════════════════

def generate_universe(n, ana):
    """Universe with person constants, place constants, and rule constants.
    Total entities (persons + places) is capped to n."""
    n_places = 2
    n_persons = max(2, n - n_places)
    persons = [chr(ord('a') + i) + str(j) for j in range(3) for i in range(8)][:n_persons]
    persons = [p for p in persons if p not in ana.rule_constants]
    places = ["p0", "p1"][:n_places]
    rc_pool = sorted(ana.rule_constants) if ana.rule_constants else []
    universe = {"person": persons, "place": places, "default": persons,
                "rule_constants": rc_pool}
    return universe

def pick_const(pred, pos, ana, universe, rng):
    """Pick a constant for position pos of pred."""
    # Rule constant slots (e.g. clearance levels)
    if (pred, pos) in ana.rc_slots and universe.get("rule_constants"):
        return rng.choice(universe["rule_constants"])
    if pred == "living_in" and pos == 1: return rng.choice(universe["place"])
    if pred in ("is_place", "not_living_in") and pos == 0: return rng.choice(universe["place"])
    if pred in ("stationed_at",) and pos == 1: return rng.choice(universe["place"])
    return rng.choice(universe["person"])

def safe_add(db, pred, args, ana):
    """Add a fact only if it doesn't violate structural constraints.
    Returns True if added, False if blocked."""
    if len(args) >= 2:
        # Self-referential predicates (unary semantics): force both args equal
        if pred in ana.self_ref:
            if args[0] != args[1]:
                return False
        # No self-loops
        if pred in ana.no_self and args[0] == args[1]:
            return False
        # Functional: at most one value per key
        if pred in ana.functional:
            kp = ana.functional[pred]
            vp = 1 - kp
            key = args[kp]
            for existing in db.get(pred, set()):
                if existing[kp] == key and existing[vp] != args[vp]:
                    return False
        # Unique value: at most one key per value
        if pred in ana.unique_val:
            vp = ana.unique_val[pred]
            kp = 1 - vp
            val = args[vp]
            for existing in db.get(pred, set()):
                if existing[vp] == val and existing[kp] != args[kp]:
                    return False
    add_fact(db, pred, args)
    return True


def instantiate(skeleton, rules, ana, universe, rng, shared=None):
    """Instantiate a skeleton into base facts (constraint-aware)."""
    if shared is None: shared = {}
    db = new_db()
    binding = dict(shared)

    def pick_safe(pred, pos, existing_binding, lit_args):
        """Pick a constant that doesn't create constraint violations."""
        base_choice = pick_const(pred, pos, ana, universe, rng)

        # Quick check: would this create a self-loop?
        if pred in ana.no_self and len(lit_args) == 2:
            other_pos = 1 - pos
            other_arg = lit_args[other_pos]
            if is_variable(other_arg) and other_arg in existing_binding:
                other_val = existing_binding[other_arg]
                if base_choice == other_val:
                    # Try alternatives
                    pool = universe.get("rule_constants") if (pred, pos) in ana.rc_slots else universe.get("person", ["x"])
                    for _ in range(20):
                        alt = rng.choice(pool)
                        if alt != other_val:
                            return alt

        # Check functional constraint
        if pred in ana.functional:
            kp = ana.functional[pred]
            if pos != kp:  # we're picking the value
                # Find the key value
                key_arg = lit_args[kp]
                key_val = existing_binding.get(key_arg, key_arg) if is_variable(key_arg) else key_arg
                if not is_variable(key_val):
                    for existing in db.get(pred, set()):
                        if existing[kp] == key_val:
                            return existing[1 - kp]  # reuse existing value

        return base_choice

    def inst(node, target_args=None):
        if node.is_leaf:
            if node.pred not in ana.seedable:
                return
            if target_args:
                # If self-ref, force both args equal
                if node.pred in ana.self_ref and len(target_args) == 2:
                    target_args = (target_args[0], target_args[0])
                safe_add(db, node.pred, target_args, ana)
            else:
                arity = ana.pred_arity.get(node.pred, 2)
                if node.pred in ana.self_ref and arity == 2:
                    c = pick_const(node.pred, 0, ana, universe, rng)
                    args = (c, c)
                else:
                    args = tuple(pick_const(node.pred, i, ana, universe, rng) for i in range(arity))
                safe_add(db, node.pred, args, ana)
            return

        rule = rules[node.rule_index]
        b = {}
        if target_args and rule.head:
            for i, (var, const) in enumerate(zip(rule.head[0].args, target_args)):
                if is_variable(var): b[var] = const

        # Assign unbound vars with constraint awareness
        for lit in rule.positive_body:
            if not lit.atom: continue
            for i, arg in enumerate(lit.atom.args):
                if is_variable(arg) and arg not in b:
                    b[arg] = pick_safe(lit.atom.pred, i, b, lit.atom.args)

        # Satisfy inequalities
        for iq in rule.inequalities:
            l, r_ = resolve(b, iq.ineq_left), resolve(b, iq.ineq_right)
            if l == r_:
                for v in [iq.ineq_right, iq.ineq_left]:
                    if is_variable(v):
                        pool = universe.get("person", ["x"])
                        for _ in range(20):
                            nv = rng.choice(pool)
                            if nv != b.get(v): b[v] = nv; break
                        break

        for child, lit in zip(node.children, rule.positive_body):
            if not lit.atom: continue
            child_args = tuple(resolve(b, a) for a in lit.atom.args)
            inst(child, child_args)

    arity = ana.pred_arity.get(skeleton.pred, 2)
    if skeleton.pred in ana.self_ref and arity == 2:
        c = pick_const(skeleton.pred, 0, ana, universe, rng)
        root_args = (c, c)
    else:
        root_args = tuple(pick_const(skeleton.pred, i, ana, universe, rng) for i in range(arity))
    inst(skeleton, root_args)
    return db

def assemble_graph(skeletons, rules, ana, universe, n, rng,
                   target_proofs=15, verbose=False):
    """Instantiate multiple skeletons into one graph with constraint checking."""
    combined = new_db()
    shared = {}
    instantiated = 0

    for sk in skeletons[:target_proofs * 2]:
        if instantiated >= target_proofs: break

        facts = instantiate(sk, rules, ana, universe, rng, shared)

        # Merge facts into combined, respecting constraints
        trial = copy_db(combined)
        for p, fs in facts.items():
            for a in fs:
                safe_add(trial, p, a, ana)

        # Check constraints after merge
        derived, _ = forward_chain_depth(trial, rules, ana.strata)
        if check_constraints(derived, rules):
            # Violated — skip this skeleton
            continue

        # Accept
        combined = trial
        instantiated += 1

        # Share constants for entity reuse
        for p, fs in facts.items():
            for a in fs:
                for i, c in enumerate(a):
                    key = f"_s_{ana.scc_id.get(p,0)}_{rng.randint(0,2)}"
                    shared[key] = c

    if verbose:
        print(f"    Instantiated {instantiated} skeletons, {db_size(combined)} facts",
              file=sys.stderr)
    return combined

# ═══════════════════════════════════════════════════════════════════════════
#  CONSTRAINT REPAIR + MINIMIZATION
# ═══════════════════════════════════════════════════════════════════════════

def repair(db, rules, ana, rng, max_attempts=50):
    """Repair constraint violations by targeted fact removal."""
    derived, _ = forward_chain_depth(db, rules, ana.strata)
    if not check_constraints(derived, rules): return True

    for attempt in range(max_attempts):
        # Find which predicates are involved in violations
        violation_preds = set()
        for r in rules:
            if not r.is_constraint: continue
            pos = r.positive_body
            if not pos: continue
            bindings = [{}]
            for lit in pos:
                if not lit.atom: continue
                new_b = []
                for b in bindings:
                    for f in derived.get(lit.atom.pred, set()):
                        nb = unify(b, lit.atom.args, f)
                        if nb is not None: new_b.append(nb)
                bindings = new_b
            for iq in r.inequalities:
                bindings = [b for b in bindings
                            if resolve(b, iq.ineq_left) != resolve(b, iq.ineq_right)]
            for n in r.negative_body:
                bindings = [b for b in bindings
                            if not has_fact(derived, n.atom.pred,
                                           tuple(resolve(b, a) for a in n.atom.args))]
            if bindings:
                for lit in pos:
                    if lit.atom: violation_preds.add(lit.atom.pred)

        # Prioritize removing base facts in violation predicates
        removable = [(p, a) for p in ana.seedable for a in db.get(p, set())
                     if p in violation_preds]
        if not removable:
            removable = [(p, a) for p in ana.seedable for a in db.get(p, set())]
        if not removable:
            break

        p, a = rng.choice(removable)
        db[p].discard(a)
        derived, _ = forward_chain_depth(db, rules, ana.strata)
        if not check_constraints(derived, rules):
            return True

    return not check_constraints(derived, rules)

def minimize(db, rules, ana, rng, max_removals=30):
    removed = 0
    cands = [(p, a) for p in db for a in list(db[p])]
    rng.shuffle(cands)
    for p, a in cands:
        if removed >= max_removals: break
        trial = copy_db(db)
        trial[p].discard(a)
        derived, _ = forward_chain_depth(trial, rules, ana.strata)
        if has_fact(derived, p, a) and not check_constraints(derived, rules):
            db[p].discard(a); removed += 1
    return removed

# ═══════════════════════════════════════════════════════════════════════════
#  SCORING
# ═══════════════════════════════════════════════════════════════════════════

def score_graph(db, rules, ana):
    derived, depth_map = forward_chain_depth(db, rules, ana.strata)
    if check_constraints(derived, rules): return -1000, {}
    depths = [d for d in depth_map.values() if d > 0]
    if not depths: return 0, {}
    bc = db_size(db); mx = max(depths); avg = sum(depths)/len(depths)
    d3 = sum(1 for d in depths if d >= 3); d5 = sum(1 for d in depths if d >= 5)
    ap = len({p for (p,_), d in depth_map.items() if d > 0})
    amp = len(depths) / max(bc, 1)
    score = mx*40 + avg*20 + d3*5 + d5*12 + ap*10 + amp*25 - bc*0.3
    return score, {"base": bc, "derived": len(depths), "max_depth": mx,
                   "avg_depth": avg, "deep3": d3, "deep5": d5,
                   "active_preds": ap, "amplification": amp}

# ═══════════════════════════════════════════════════════════════════════════
#  POPULATION SAMPLING
# ═══════════════════════════════════════════════════════════════════════════

def sample(rules, ana, n, pop_size, rng, verbose=False):
    universe = generate_universe(n, ana)

    if verbose:
        print(f"  Enumerating skeletons...", file=sys.stderr)
    skeletons = enumerate_skeletons(rules, ana, max_depth=6,
                                     max_skeletons=80, rng=rng)
    if verbose:
        depths = [s.depth for s in skeletons]
        print(f"    Found {len(skeletons)}, depths: "
              f"{min(depths) if depths else 0}-{max(depths) if depths else 0}",
              file=sys.stderr)

    if not skeletons:
        if verbose: print("    No skeletons! Falling back to random.", file=sys.stderr)
        return None, {}

    # Phase 1: Generate candidates with FAST proxy score (no forward chaining)
    candidates = []
    for i in range(pop_size):
        sub_rng = random.Random(rng.randint(0, 2**31))
        sub_skels = list(skeletons)
        sub_rng.shuffle(sub_skels)

        db = assemble_graph(sub_skels, rules, ana, universe, n, sub_rng,
                            target_proofs=min(12, len(sub_skels)))

        # Supplemental seedable facts
        for pred in ana.seedable:
            if pred not in ana.pred_arity: continue
            if db_size(db) > n * 5: break
            arity = ana.pred_arity[pred]
            for _ in range(sub_rng.randint(0, 2)):
                args = tuple(pick_const(pred, j, ana, universe, sub_rng) for j in range(arity))
                add_fact(db, pred, args)

        # Proxy score: just count facts and skeleton depth
        bc = db_size(db)
        num_preds = len(set(db.keys()))
        max_sk_depth = max((s.depth for s in sub_skels[:12]), default=0)
        proxy = num_preds * 5 + max_sk_depth * 20 - bc * 0.3
        candidates.append((db, proxy, sub_rng))

    candidates.sort(key=lambda x: x[1], reverse=True)
    if verbose:
        print(f"  Phase 1: {len(candidates)} candidates (proxy scored)",
              file=sys.stderr)

    # Phase 2: Full evaluation of top candidates only
    top_n = min(5, len(candidates))
    best_db = None; best_score = -1; best_details = {}

    for i, (db, proxy, sub_rng) in enumerate(candidates[:top_n]):
        ok = repair(db, rules, ana, sub_rng)
        if not ok:
            if verbose: print(f"    Top {i}: VIOLATED (proxy={proxy:.0f})", file=sys.stderr)
            continue

        sc, det = score_graph(db, rules, ana)
        if verbose:
            print(f"    Top {i}: real={sc:.0f} {det}", file=sys.stderr)

        if sc > best_score:
            best_score = sc; best_db = copy_db(db); best_details = det

    return best_db, best_details

# ═══════════════════════════════════════════════════════════════════════════
#  OUTPUT + MAIN
# ═══════════════════════════════════════════════════════════════════════════

def format_asp(db):
    lines = ["% === BASE FACTS (backward-planned v2) ===", ""]
    for pred in sorted(db.keys()):
        facts = sorted(db[pred])
        if not facts: continue
        lines.append(f"% {pred}")
        for args in facts: lines.append(f"{pred}({','.join(args)}).")
        lines.append("")
    return "\n".join(lines)

def main():
    parser = argparse.ArgumentParser(description="Backward proof-planning sampler v2")
    parser.add_argument("rules_file")
    parser.add_argument("num_vertices", type=int)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--population", type=int, default=20)
    parser.add_argument("--target-proofs", type=int, default=15)
    parser.add_argument("--max-depth", type=int, default=6)
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
        print(f"  {len(rules)} rules, {len(ana.seedable)} seedable preds",
              file=sys.stderr)
        print(f"  Seedable: {sorted(ana.seedable)[:10]}...", file=sys.stderr)

    best_db, details = sample(rules, ana, args.num_vertices,
                               args.population, rng, verbose=args.verbose)

    if best_db is None:
        print("ERROR: no viable graph found", file=sys.stderr); sys.exit(1)

    # Final minimization (light — avoid timeout on complex rule sets)
    if args.verbose: print(f"\n  Minimizing...", file=sys.stderr)
    removed = minimize(best_db, rules, ana, rng, max_removals=10)
    final_sc, final_det = score_graph(best_db, rules, ana)

    if args.verbose:
        print(f"  Removed {removed} facts", file=sys.stderr)
        print(f"  Final: score={final_sc:.0f} {final_det}", file=sys.stderr)

    report = ["% ═══════════════════════════════════════════",
              "% BACKWARD SAMPLER v2 (SCC-aware)",
              "% ═══════════════════════════════════════════"]
    for k, v in sorted(final_det.items()):
        report.append(f"% {k}: {v}")

    output = "\n".join(report) + "\n\n" + format_asp(best_db)
    if args.output:
        with open(args.output, "w") as f: f.write(output)
        if args.verbose: print(f"  Written to {args.output}", file=sys.stderr)
    else:
        print(output)

if __name__ == "__main__":
    main()
