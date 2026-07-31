#!/usr/bin/env python3
"""
Motif-Stitching ASP Sampler
=============================
A rule-aware sampler that builds graphs by composing "motifs" —
minimal sets of base facts that trigger specific derivation rules.

Strategy (different from all other samplers):
  1. MOTIF EXTRACTION: For each rule, find the smallest set of seedable
     base facts that triggers it. Each motif is a tiny self-contained
     proof step.
  2. MOTIF CHAINING: Connect motifs by sharing entity names, building
     layered derivation chains where one motif's output feeds the next.
  3. DEPTH-FIRST CONSTRUCTION: Prioritise motifs that produce deep proofs.
     Build the skeleton top-down from a target derived predicate, then
     instantiate the base facts needed at the leaves.
  4. POPULATION DIVERSITY: Generate multiple configurations with different
     target predicates and chain structures, keep the best.

Why this is different:
  - nora_sampler: template-based (hardcoded family structures)
  - evo_sampler:  random mutation + selection (no rule awareness)
  - v2_sampler:   incremental random seeding + hill climbing
  - backward:     skeleton enumeration from dependency graph
  - THIS:         composes verified building blocks from rule analysis

Usage:
    python3 motif_sampler.py 6 --rules nora_rules.lp --seed 42 --verbose
    python3 motif_sampler.py 8 --rules nora_rules.lp --population 30 -o graph.lp
"""

import argparse, collections, copy, os, random, re, sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

# ═══════════════════════════════════════════════════════════════════════════
#  INLINED ASP ENGINE
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
    head: list; body: list
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
    s = db[p]; r = a not in s; s.add(a); return r
def has_fact(db, p, a): return a in db.get(p, set())
def db_size(db): return sum(len(v) for v in db.values())
def _isvar(s): return bool(s) and s[0].isupper()
def _res(b, a): return b.get(a, a) if _isvar(a) else a

def _split(text, sep=','):
    parts, d, c = [], 0, []
    for ch in text:
        if ch == '(': d += 1
        elif ch == ')': d -= 1
        elif ch == sep and d == 0: parts.append(''.join(c).strip()); c = []; continue
        c.append(ch)
    t = ''.join(c).strip()
    if t: parts.append(t)
    return parts

def _patom(text):
    text = text.strip()
    if not text: return None
    if '(' not in text:
        if re.match(r'^[a-z_]\w*$', text): return Atom(pred=text, args=(text, text))
        return None
    m = re.match(r'^([a-z_]\w*)\((.+)\)$', text, re.DOTALL)
    if not m: return None
    args = [a.strip() for a in _split(m.group(2))]
    if len(args) == 1: args = [args[0], args[0]]
    return Atom(pred=m.group(1), args=tuple(args))

def parse_program(text):
    lines = text.split('\n')
    cleaned = [l[:l.find('%')] if '%' in l else l for l in lines]
    text = ' '.join(cleaned); rules = []; idx = 0
    for part in text.split('.'):
        part = part.strip()
        if not part: continue
        def pbody(t):
            lits = []
            for p in _split(t):
                p = p.strip()
                if not p: continue
                for op in ['!=', '\\=']:
                    if op in p:
                        sides = p.split(op, 1)
                        lits.append(Literal(ineq_left=sides[0].strip(), ineq_right=sides[1].strip())); break
                else:
                    neg = p.startswith('not ')
                    if neg: p = p[4:].strip()
                    a = _patom(p)
                    if a: lits.append(Literal(atom=a, negated=neg))
            return lits
        if part.startswith(':-'):
            rules.append(Rule(head=[], body=pbody(part[2:].strip()), is_constraint=True, index=idx)); idx += 1
        elif ':-' in part:
            ht, bt = part.split(':-', 1)
            ht = ht.strip(); ic = ht.startswith('{')
            if ic: ht = ht[1:]
            if '}' in ht: ht = ht[:ht.rindex('}')]
            hatoms = [_patom(a.strip()) for a in _split(ht)]
            rules.append(Rule(head=[a for a in hatoms if a], body=pbody(bt.strip()), is_choice=ic, index=idx)); idx += 1
        else:
            a = _patom(part)
            if a: rules.append(Rule(head=[a], body=[], index=idx)); idx += 1
    return rules, []

def _unify(b, args, fact):
    b2 = dict(b)
    for a, v in zip(args, fact):
        if _isvar(a):
            if a in b2:
                if b2[a] != v: return None
            else: b2[a] = v
        elif a != v: return None
    return b2

def forward_chain_depth(base_db, rules):
    """Forward chain with depth tracking. Returns (db, depth_map)."""
    strata = {}
    for r in rules:
        for a in (r.head or []): strata.setdefault(a.pred, 0)
        for l in r.body:
            if l.atom: strata.setdefault(l.atom.pred, 0)
    for _ in range(len(strata) + 2):
        ch = False
        for r in rules:
            if r.is_constraint: continue
            for ha in r.head:
                ms = max((strata.get(l.atom.pred, 0) + (1 if l.negated else 0)
                          for l in r.body if l.atom), default=0)
                if ms > strata.get(ha.pred, -1): strata[ha.pred] = ms; ch = True
        if not ch: break

    db = copy_db(base_db)
    dm = {(p, a): 0 for p in base_db for a in base_db[p]}
    max_s = max(strata.values()) if strata else 0
    by_s = collections.defaultdict(list)
    for r in rules:
        if r.is_constraint: continue
        if r.head:
            s = max(strata.get(a.pred, 0) for a in r.head)
            by_s[s].append(r)
    for s in range(max_s + 1):
        for _ in range(25):
            changed = False
            for r in by_s.get(s, []):
                pos = r.positive_body
                if not pos: continue
                bd = []
                for f in db.get(pos[0].atom.pred, set()):
                    b = _unify({}, pos[0].atom.args, f)
                    if b is not None: bd.append((b, dm.get((pos[0].atom.pred, f), 0)))
                for lit in pos[1:]:
                    if not bd: break
                    fp = db.get(lit.atom.pred, set())
                    new = []
                    for b, md in bd:
                        for f in fp:
                            nb = _unify(b, lit.atom.args, f)
                            if nb is not None:
                                new.append((nb, max(md, dm.get((lit.atom.pred, f), 0))))
                    bd = new
                for iq in r.inequalities:
                    bd = [(b,d) for b,d in bd if _res(b, iq.ineq_left) != _res(b, iq.ineq_right)]
                for neg in r.negative_body:
                    bd = [(b,d) for b,d in bd
                          if not has_fact(db, neg.atom.pred,
                                         tuple(_res(b, a) for a in neg.atom.args))]
                for b, md in bd:
                    for ha in r.head:
                        g = tuple(_res(b, a) for a in ha.args)
                        if all(not _isvar(x) for x in g):
                            nd = md + 1; key = (ha.pred, g)
                            if add_fact(db, ha.pred, g):
                                changed = True; dm[key] = nd
                            elif key in dm and nd < dm[key]:
                                dm[key] = nd
            if not changed: break
    return db, dm

def check_constraints(db, rules):
    for r in rules:
        if not r.is_constraint: continue
        pos = r.positive_body
        if not pos: continue
        bd = []
        for f in db.get(pos[0].atom.pred, set()):
            b = _unify({}, pos[0].atom.args, f)
            if b is not None: bd.append(b)
        for lit in pos[1:]:
            if not bd: break
            fp = db.get(lit.atom.pred, set())
            new = []
            for b in bd:
                for f in fp:
                    nb = _unify(b, lit.atom.args, f)
                    if nb is not None: new.append(nb)
            bd = new
        for iq in r.inequalities:
            bd = [b for b in bd if _res(b, iq.ineq_left) != _res(b, iq.ineq_right)]
        for neg in r.negative_body:
            bd = [b for b in bd
                  if not has_fact(db, neg.atom.pred, tuple(_res(b, a) for a in neg.atom.args))]
        if bd: return True
    return False

# ═══════════════════════════════════════════════════════════════════════════
#  MOTIF EXTRACTION
# ═══════════════════════════════════════════════════════════════════════════

def detect_seedable(rules):
    """Auto-detect predicates safe to use as base facts."""
    head_preds = set(); body_preds = set()
    for r in rules:
        for a in r.head: head_preds.add(a.pred)
        for l in r.body:
            if l.atom: body_preds.add(l.atom.pred)

    # Pure base: in body, never in head
    pure_base = body_preds - head_preds

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

    if pure_base or symmetric_base:
        seedable = set(pure_base) | symmetric_base
    else:
        # SCC-based detection with take limiting
        dep = collections.defaultdict(set)
        fanout = collections.Counter()
        for r in rules:
            if r.is_constraint: continue
            for ha in r.head:
                for l in r.positive_body:
                    if l.atom: dep[ha.pred].add(l.atom.pred)
            for l in r.positive_body:
                if l.atom: fanout[l.atom.pred] += 1

        # Tarjan's SCC
        all_p = set(dep.keys())
        for vs in dep.values(): all_p |= vs
        idx_c = [0]; stack = []; on_stack = set()
        index = {}; lowlink = {}; sccs = []
        old_limit = sys.getrecursionlimit()
        sys.setrecursionlimit(max(5000, len(all_p) * 3))
        def _sc(v):
            index[v] = lowlink[v] = idx_c[0]; idx_c[0] += 1
            stack.append(v); on_stack.add(v)
            for w in dep.get(v, set()):
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

        # Predicates with simple (1-body) derivation rules
        has_simple = set()
        for r in rules:
            if r.is_constraint: continue
            pb = r.positive_body
            if len(pb) == 1 and len(r.head) == 1:
                has_simple.add(r.head[0].pred)
                has_simple.add(pb[0].atom.pred)

        # Pick top fan-out from each SCC (limited count)
        seedable = set()
        for scc in sccs:
            body_m = [(p, fanout[p]) for p in scc
                      if fanout[p] > 0 and p in has_simple]
            if not body_m: continue
            body_m.sort(key=lambda x: -x[1])
            take = max(2, len(scc) // 8)
            for p, _ in body_m[:take]: seedable.add(p)

    # Filter out closed-world and type predicates
    seedable = {p for p in seedable
                if not p.startswith('no_') and not p.startswith('not_')
                and p not in ('is_person', 'is_place', 'is_agent',
                              'is_asset', 'is_level', 'living_in_same_place')}

    # ── Rule constant detection ──
    rule_constants = set()
    rc_slots = set()
    for r in rules:
        if r.body or not r.head: continue
        a = r.head[0]
        if all(not _isvar(x) for x in a.args):
            for i, arg in enumerate(a.args):
                rc_slots.add((a.pred, i))
                rule_constants.add(arg)
    # Propagate through variable sharing
    for _ in range(10):
        changed = False
        for r in rules:
            if r.is_constraint: continue
            var_pos = collections.defaultdict(set)
            all_atoms = list(r.head) + [l.atom for l in r.body if l.atom]
            for a in all_atoms:
                for i, arg in enumerate(a.args):
                    if _isvar(arg): var_pos[arg].add((a.pred, i))
            for var, positions in var_pos.items():
                if any(p in rc_slots for p in positions):
                    for p in positions:
                        if p not in rc_slots: rc_slots.add(p); changed = True
        if not changed: break

    # Exclude predicates fully defined by ground facts in the rules (e.g. outranks)
    ground_fact_preds = {r.head[0].pred for r in rules
                         if not r.body and r.head
                         and all(not _isvar(x) for x in r.head[0].args)}
    seedable -= ground_fact_preds

    # Detect self-referential predicates (binary preds always used as p(X,X))
    pred_arity = {}
    for r in rules:
        for a in r.head:
            if a.pred not in pred_arity: pred_arity[a.pred] = len(a.args)
        for l in r.body:
            if l.atom and l.atom.pred not in pred_arity:
                pred_arity[l.atom.pred] = len(l.atom.args)

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
        if seen and always_same:
            self_ref.add(p)

    return seedable, rule_constants, rc_slots, self_ref


PERSON_NAMES = ["alice","bob","carl","diana","emma","frank","george",
                "hannah","ivan","julia","kevin","laura","mark","nora"]
PLACE_NAMES = ["london","paris","rome","berlin"]
LEVEL_NAMES = ["junior","senior","top"]

@dataclass
class Motif:
    """A minimal set of base facts that triggers a specific rule."""
    rule_index: int
    head_pred: str
    base_preds: Set[str]
    var_roles: Dict[str, str]
    body_pattern: list
    head_pattern: tuple
    depth_contribution: int

def extract_motifs(rules, seedable):
    """Extract motifs: rules whose positive body uses only seedable preds."""
    motifs = []
    for r in rules:
        if r.is_constraint: continue
        pb = r.positive_body
        if not pb or not r.head: continue
        body_preds = {l.atom.pred for l in pb if l.atom}
        if body_preds <= seedable:
            for ha in r.head:
                pattern = [(l.atom.pred, l.atom.args) for l in pb if l.atom]
                var_roles = {}
                for l in pb:
                    if l.atom:
                        for i, a in enumerate(l.atom.args):
                            if _isvar(a): var_roles[a] = f"{l.atom.pred}_{i}"
                motifs.append(Motif(
                    rule_index=r.index, head_pred=ha.pred,
                    base_preds=body_preds, var_roles=var_roles,
                    body_pattern=pattern, head_pattern=(ha.pred, ha.args),
                    depth_contribution=1))
    return motifs


def extract_deep_motifs(rules, base_motifs, seedable):
    """Find 2-step motifs: rules needing 1 derived pred producible by base motifs."""
    derived_by_base = {m.head_pred for m in base_motifs}
    deep = []
    for r in rules:
        if r.is_constraint: continue
        pb = r.positive_body
        if not pb or not r.head: continue
        body_preds = {l.atom.pred for l in pb if l.atom}
        derived_needed = body_preds - seedable
        seedable_present = body_preds & seedable
        if len(derived_needed) == 1 and derived_needed <= derived_by_base:
            dp = list(derived_needed)[0]
            for ha in r.head:
                if ha.pred == dp: continue
                pattern = [(l.atom.pred, l.atom.args) for l in pb if l.atom]
                var_roles = {}
                for l in pb:
                    if l.atom:
                        for i, a in enumerate(l.atom.args):
                            if _isvar(a): var_roles[a] = f"{l.atom.pred}_{i}"
                deep.append(Motif(
                    rule_index=r.index, head_pred=ha.pred,
                    base_preds=seedable_present, var_roles=var_roles,
                    body_pattern=pattern, head_pattern=(ha.pred, ha.args),
                    depth_contribution=2))
    return deep

# ═══════════════════════════════════════════════════════════════════════════
#  MOTIF INSTANTIATION & STITCHING
# ═══════════════════════════════════════════════════════════════════════════

def instantiate_motif(motif, rng, name_pool, place_pool, seedable,
                      rule_constants=None, rc_slots=None, shared_bindings=None,
                      self_ref=None):
    """Ground a motif into concrete base facts, sharing names where possible."""
    binding = dict(shared_bindings or {})
    if rule_constants is None: rule_constants = set()
    if rc_slots is None: rc_slots = set()
    if self_ref is None: self_ref = set()
    rc_pool = sorted(rule_constants) if rule_constants else []

    for lit_pred, lit_args in motif.body_pattern:
        for i, arg in enumerate(lit_args):
            if _isvar(arg) and arg not in binding:
                if (lit_pred, i) in rc_slots and rc_pool:
                    binding[arg] = rng.choice(rc_pool)
                elif lit_pred in ('living_in', 'stationed_at') and i == 1:
                    binding[arg] = rng.choice(place_pool)
                elif lit_pred in self_ref and i == 1 and len(lit_args) == 2:
                    # Self-ref predicate: position 1 must equal position 0
                    if lit_args[0] in binding:
                        binding[arg] = binding[lit_args[0]]
                    else:
                        v = rng.choice(name_pool)
                        binding[arg] = v
                        binding[lit_args[0]] = v
                elif lit_pred.startswith('is_') and i == 1:
                    if lit_args[0] in binding:
                        binding[arg] = binding[lit_args[0]]
                    else:
                        binding[arg] = rng.choice(name_pool)
                        binding[lit_args[0]] = binding[arg]
                elif lit_pred in ('has_clearance', 'classified_as') and i == 1:
                    binding[arg] = rng.choice(LEVEL_NAMES)
                else:
                    binding[arg] = rng.choice(name_pool)

    facts = new_db()
    for pred, args in motif.body_pattern:
        grounded = tuple(_res(binding, a) for a in args)
        if pred in seedable:
            # Self-ref safety net: force both args equal
            if pred in self_ref and len(grounded) == 2 and grounded[0] != grounded[1]:
                grounded = (grounded[0], grounded[0])
            add_fact(facts, pred, grounded)

    return facts, binding


def stitch_motifs(motif_sequence, n, rng, rules, seedable,
                  rule_constants=None, rc_slots=None, self_ref=None, verbose=False):
    """Stitch a sequence of motifs into one graph, sharing entities."""
    n_places = max(2, n // 3)
    n_persons = max(2, n - n_places)
    name_pool = PERSON_NAMES[:n_persons]
    # Exclude rule constants from name pool
    if rule_constants:
        name_pool = [nm for nm in name_pool if nm not in rule_constants]
    place_pool = PLACE_NAMES[:n_places]
    combined = new_db()
    all_bindings = {}

    for mi, motif in enumerate(motif_sequence):
        # Share some bindings with previous motifs to create connections
        shared = {}
        if all_bindings:
            existing_names = [v for v in all_bindings.values() if v in name_pool]
            if existing_names:
                # Share 1-2 variables with existing entities (40% chance each)
                for pred, args in motif.body_pattern:
                    for i, arg in enumerate(args):
                        if _isvar(arg) and arg not in shared:
                            if rng.random() < 0.4 and existing_names:
                                shared[arg] = rng.choice(existing_names)
                                break

        facts, binding = instantiate_motif(motif, rng, name_pool, place_pool,
                                          seedable, rule_constants, rc_slots,
                                          shared, self_ref=self_ref)
        for p, fs in facts.items():
            for a in fs: add_fact(combined, p, a)
        all_bindings.update(binding)

    # Validate constraints
    derived, dm = forward_chain_depth(combined, rules)
    if check_constraints(derived, rules):
        return None, {}, True

    return combined, dm, False


# ═══════════════════════════════════════════════════════════════════════════
#  SCORING
# ═══════════════════════════════════════════════════════════════════════════

def score_graph(db, rules):
    derived, dm = forward_chain_depth(db, rules)
    if check_constraints(derived, rules):
        return -1000, {}
    depths = [d for d in dm.values() if d > 0]
    if not depths: return 0, {}
    bc = db_size(db); mx = max(depths); avg = sum(depths)/len(depths)
    d3 = sum(1 for d in depths if d >= 3)
    d5 = sum(1 for d in depths if d >= 5)
    ap = len({p for (p,_), d in dm.items() if d > 0})
    amp = len(depths) / max(bc, 1)
    score = mx*40 + avg*20 + d3*5 + d5*12 + ap*10 + amp*25 - bc*0.3
    return score, {"base": bc, "derived": len(depths), "max_depth": mx,
                   "avg_depth": round(avg, 2), "deep3": d3, "deep5": d5,
                   "active_preds": ap, "amplification": round(amp, 2)}


# ═══════════════════════════════════════════════════════════════════════════
#  POPULATION SAMPLING WITH MOTIF STRATEGIES
# ═══════════════════════════════════════════════════════════════════════════

def sample(rules, n, pop_size, rng, verbose=False):
    seedable, rule_constants, rc_slots, self_ref = detect_seedable(rules)
    if verbose:
        print(f"  Seedable: {sorted(seedable)[:8]}{'...' if len(seedable)>8 else ''}",
              file=sys.stderr)
        if rule_constants:
            print(f"  Rule constants: {sorted(rule_constants)}", file=sys.stderr)
        print("  Extracting motifs...", file=sys.stderr)
    base_motifs = extract_motifs(rules, seedable)
    deep_motifs = extract_deep_motifs(rules, base_motifs, seedable)
    all_motifs = base_motifs + deep_motifs

    if verbose:
        print(f"    Base motifs (depth-1): {len(base_motifs)}", file=sys.stderr)
        print(f"    Deep motifs (depth-2): {len(deep_motifs)}", file=sys.stderr)
        preds = sorted({m.head_pred for m in all_motifs})
        print(f"    Derive: {preds[:10]}{'...' if len(preds)>10 else ''}", file=sys.stderr)

    if not all_motifs:
        if verbose: print("    No motifs found!", file=sys.stderr)
        return None, {}

    by_head = collections.defaultdict(list)
    for m in all_motifs: by_head[m.head_pred].append(m)

    best_db = None; best_score = -1; best_details = {}

    for ci in range(pop_size):
        sub_rng = random.Random(rng.randint(0, 2**31))
        strategy = ci % 4

        if strategy == 0:
            seq = list(deep_motifs); sub_rng.shuffle(seq)
            seq = seq[:min(15, len(seq))]
            extras = list(base_motifs); sub_rng.shuffle(extras)
            seq.extend(extras[:min(10, len(extras))])
        elif strategy == 1:
            used_preds = set(); seq = []
            pool = list(all_motifs); sub_rng.shuffle(pool)
            for m in pool:
                if m.head_pred not in used_preds:
                    seq.append(m); used_preds.add(m.head_pred)
                if len(seq) >= 20: break
        elif strategy == 2:
            seq = []; targets = list(deep_motifs); sub_rng.shuffle(targets)
            for target in targets[:6]:
                seq.append(target)
                needed = target.base_preds - seedable
                for np in needed:
                    providers = [m for m in base_motifs if m.head_pred == np]
                    if providers: seq.append(sub_rng.choice(providers))
            extras = list(base_motifs); sub_rng.shuffle(extras)
            seq.extend(extras[:min(10, len(extras))])
        else:
            pool = list(all_motifs); sub_rng.shuffle(pool)
            seq = pool[:min(20, len(pool))]

        db, dm, violated = stitch_motifs(seq, n, sub_rng, rules, seedable, rule_constants, rc_slots, self_ref=self_ref)
        if violated or db is None:
            for trim in range(len(seq) - 1, 2, -1):
                db, dm, violated = stitch_motifs(seq[:trim], n, sub_rng, rules, seedable, rule_constants, rc_slots, self_ref=self_ref)
                if not violated and db is not None: break
            if violated or db is None: continue

        sc, det = score_graph(db, rules)
        if verbose and ci < 5:
            print(f"    Candidate {ci} (strat={strategy}): score={sc:.0f} {det}",
                  file=sys.stderr)
        if sc > best_score:
            best_score = sc; best_db = copy_db(db); best_details = det

    # Post-processing: greedily add more motifs to the best graph
    if best_db is not None:
        if verbose: print(f"  Post-processing: augmenting best graph...", file=sys.stderr)
        for attempt in range(60):
            trial = copy_db(best_db)
            m = rng.choice(all_motifs)
            existing = sorted({c for p in trial for a in trial[p] for c in a
                               if c in PERSON_NAMES})
            if not existing: break
            shared = {}
            for pred, args in m.body_pattern:
                for i, arg in enumerate(args):
                    if _isvar(arg) and arg not in shared and existing:
                        shared[arg] = rng.choice(existing)
                        if rng.random() < 0.5: break
            facts, _ = instantiate_motif(m, rng, existing, PLACE_NAMES[:2],
                                         seedable, rule_constants, rc_slots, shared,
                                         self_ref=self_ref)
            for p, fs in facts.items():
                for a in fs: add_fact(trial, p, a)
            sc, det = score_graph(trial, rules)
            if sc > best_score:
                best_score = sc; best_db = trial; best_details = det
        if verbose:
            print(f"  Final: score={best_score:.0f} {best_details}", file=sys.stderr)

    return best_db, best_details


# ═══════════════════════════════════════════════════════════════════════════
#  OUTPUT & MAIN
# ═══════════════════════════════════════════════════════════════════════════

def format_asp(db):
    lines = ["% === BASE FACTS (motif-stitched) ===", ""]
    for pred in sorted(db.keys()):
        facts = sorted(db[pred])
        if not facts: continue
        lines.append(f"% {pred}")
        for args in facts: lines.append(f"{pred}({','.join(args)}).")
        lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Motif-stitching ASP sampler")
    parser.add_argument("num_vertices", type=int)
    parser.add_argument("--rules", "-r", required=True, help="ASP rules file")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--population", type=int, default=30)
    parser.add_argument("--output", "-o", type=str, default=None)
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    rng = random.Random(args.seed)
    rules_path = os.path.abspath(args.rules)
    if not os.path.exists(rules_path):
        print(f"ERROR: rules file not found: {rules_path}", file=sys.stderr)
        sys.exit(1)

    with open(rules_path) as f: rules_text = f.read()
    rules, _ = parse_program(rules_text)

    if args.verbose:
        n_rules = sum(1 for r in rules if not r.is_constraint)
        n_constr = sum(1 for r in rules if r.is_constraint)
        print(f"Motif sampler: {args.num_vertices} vertices, "
              f"pop={args.population}", file=sys.stderr)
        print(f"  Rules: {n_rules} + {n_constr} constraints", file=sys.stderr)

    best_db, details = sample(rules, args.num_vertices, args.population,
                               rng, verbose=args.verbose)

    if best_db is None:
        print("ERROR: no valid graph found", file=sys.stderr)
        sys.exit(1)

    if args.verbose:
        print(f"\n=== BEST ===", file=sys.stderr)
        for k, v in sorted(details.items()): print(f"  {k}: {v}", file=sys.stderr)

    report = ["% ═══════════════════════════════════════════",
              "% MOTIF-STITCHING SAMPLER",
              "% ═══════════════════════════════════════════"]
    for k, v in sorted(details.items()): report.append(f"% {k}: {v}")
    output = "\n".join(report) + "\n\n" + format_asp(best_db)

    if args.output:
        with open(args.output, "w") as f: f.write(output)
        if args.verbose: print(f"  Written to {args.output}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
