#!/usr/bin/env python3
"""
Clingo-Based Query Generator
==============================

Generates queries by computing cautious consequences (intersection of
all answer sets) using clingo.  This mirrors the reference implementation
exactly:

    1. Combine rules + base facts into one ASP program
    2. Run clingo to enumerate ALL answer sets
    3. Intersect all answer sets → cautious consequences
    4. Subtract base facts → entailed (non-trivial) facts = queries

Each query is a derived fact that holds in EVERY answer set but is
not stated in the base graph.

Usage:
    # Sampler mode: generate base facts with a sampler, then derive queries
    python3 clingo_query_generator.py -s atlas_sampler.py -r rules.lp -n 6 -g 2 -o data.csv

    # Direct mode: self-contained .lp file with embedded facts
    python3 clingo_query_generator.py -p claude-1-se4.lp -o data.csv

    # Pipe mode: rules file + base facts from stdin or file
    python3 clingo_query_generator.py -r rules.lp -f base_facts.lp -o data.csv

Requires: pip install clingo
"""

import argparse, ast, collections, csv, functools, io, os, random, re
import subprocess, sys, tempfile
from dataclasses import dataclass
from typing import Dict, List, Set, Tuple

try:
    from clingo import Control
    HAS_CLINGO = True
except ImportError:
    HAS_CLINGO = False


# ═══════════════════════════════════════════════════════════════════════════
#  CORE: CLINGO INTERFACE (matches reference implementation exactly)
# ═══════════════════════════════════════════════════════════════════════════

def run_clingo(program):
    """
    Runs clingo on the given ASP program and returns a list of answer sets.
    Each answer set is represented as a set of clingo symbols.
    """
    def _noop(code, msg): pass
    try:
        ctl = Control(logger=_noop)
    except TypeError:
        ctl = Control()
    ctl.configuration.solve.models = 0  # generate all models
    ctl.add("base", [], program)
    ctl.ground([("base", [])])
    models = []
    with ctl.solve(yield_=True) as handle:
        for model in handle:
            models.append(set(model.symbols(shown=True)))
    return models


def compute_entailed_facts(program, explicit_story_facts):
    """
    Compute all cautious consequences that are NOT in the base story.
    This is the intersection of all answer sets minus the explicit facts.

    Args:
        program: Full ASP program string (rules + base facts).
        explicit_story_facts: Set of strings like {"parent(a,b).", "male(a)."}

    Returns:
        List of entailed fact strings like ["grandparent(a,c).", ...]
    """
    models = run_clingo(program)
    if not models:
        return []
    # Convert each model to a set of "pred(args)." strings
    model_fact_sets = [{str(atom) + "." for atom in model} for model in models]
    # Intersect all answer sets → cautious consequences
    intersection_facts = functools.reduce(lambda a, b: a & b, model_fact_sets)
    # Remove base facts
    non_trivial_entailed = intersection_facts - explicit_story_facts
    return list(non_trivial_entailed)


# ═══════════════════════════════════════════════════════════════════════════
#  FACT DB & ASP CONVERSION
# ═══════════════════════════════════════════════════════════════════════════

FactDB = Dict[str, Set[Tuple[str, ...]]]


def new_db():
    return collections.defaultdict(set)


def add_fact(db, pred, args):
    db[pred].add(args)


def db_size(db):
    return sum(len(fs) for fs in db.values())


def parse_fact_string(fact_str):
    """Parse 'pred(a,b).' into (pred, (a, b))."""
    fact_str = fact_str.strip().rstrip('.')
    m = re.match(r'([a-z][a-zA-Z0-9_]*)\(([^)]*)\)', fact_str)
    if not m:
        # Could be a 0-ary atom
        m2 = re.match(r'([a-z][a-zA-Z0-9_]*)', fact_str)
        if m2:
            return m2.group(1), ()
        return None, None
    pred = m.group(1)
    args = tuple(a.strip() for a in m.group(2).split(',') if a.strip())
    return pred, args


def db_to_fact_strings(db):
    """Convert FactDB to a set of 'pred(args).' strings for matching."""
    facts = set()
    for pred, arg_sets in db.items():
        for args in arg_sets:
            if len(args) == 2 and args[0] == args[1]:
                # Could be unary — include both forms
                facts.add(f"{pred}({args[0]}).")
                facts.add(f"{pred}({args[0]},{args[1]}).")
            elif len(args) == 1:
                facts.add(f"{pred}({args[0]}).")
            else:
                facts.add(f"{pred}({','.join(args)}).")
    return facts


def db_to_asp_text(db, unary_preds=None):
    """Convert FactDB to ASP text.

    If unary_preds is provided, predicates in that set are written in unary
    form (e.g. is_agent(a). for SpyNet). Otherwise binary predicates stored
    as (X,X) are written as binary (e.g. is_female(a,a). for NoRa)."""
    if unary_preds is None:
        unary_preds = set()
    lines = []
    for pred in sorted(db.keys()):
        for args in sorted(db[pred]):
            if len(args) == 0:
                lines.append(f"{pred}.")
            elif len(args) == 2 and args[0] == args[1] and pred in unary_preds:
                # Unary semantics in rules → write as unary
                lines.append(f"{pred}({args[0]}).")
            elif len(args) == 1:
                lines.append(f"{pred}({args[0]}).")
            else:
                lines.append(f"{pred}({','.join(args)}).")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
#  ASP PARSER (minimal, for base fact extraction)
# ═══════════════════════════════════════════════════════════════════════════

def parse_program_facts(text):
    """Extract ground facts from an ASP program text.
    Returns (rules_and_facts_text, base_db, fact_strings_set)."""
    db = new_db()
    fact_strings = set()

    lines = text.split('\n')
    cleaned = [l[:l.find('%')] if '%' in l else l for l in lines]
    full = ' '.join(cleaned)

    for part in full.split('.'):
        part = part.strip()
        if not part:
            continue
        if ':-' in part:
            continue  # rule or constraint — skip
        # Check if ground (no variables)
        has_var = bool(re.search(r'\b[A-Z][A-Za-z0-9]*\b', part))
        if has_var:
            continue
        # Parse as fact
        m = re.match(r'([a-z][a-zA-Z0-9_]*)\(([^)]*)\)', part.strip())
        if m:
            pred = m.group(1)
            args = tuple(a.strip() for a in m.group(2).split(',') if a.strip())
            if len(args) == 1:
                # Store as binary internally (our convention)
                add_fact(db, pred, (args[0], args[0]))
                fact_strings.add(f"{pred}({args[0]}).")
            else:
                add_fact(db, pred, args)
                fact_strings.add(f"{pred}({','.join(args)}).")
        else:
            # 0-ary fact
            name = part.strip()
            if re.match(r'^[a-z][a-zA-Z0-9_]*$', name):
                fact_strings.add(f"{name}.")

    return db, fact_strings


def parse_facts_lp(path):
    """Parse a .lp file containing only base facts into a FactDB."""
    with open(path) as f:
        text = f.read()
    db, _ = parse_program_facts(text)
    return db


# ═══════════════════════════════════════════════════════════════════════════
#  EDGE CONVERSION (for CSV output)
# ═══════════════════════════════════════════════════════════════════════════

def detect_rule_constants(rules_text):
    """Detect constants from ground facts in a rules file."""
    constants = set()
    for line in rules_text.split('\n'):
        line = line.strip()
        if not line or line.startswith('%') or line.startswith(':-') or ':-' in line:
            continue
        for m in re.finditer(r'([a-z_]\w*)\(([^)]+)\)', line):
            args = [a.strip() for a in m.group(2).split(',')]
            if all(a[0].islower() for a in args if a):
                constants.update(args)
    return constants


def detect_unary_preds(rules_text):
    """Detect predicates that appear with arity 1 in rules text."""
    unary = set()
    for m in re.finditer(r'([a-z_]\w*)\(([^)]+)\)', rules_text):
        args = [a.strip() for a in m.group(2).split(',')]
        if len(args) == 1:
            unary.add(m.group(1))
    return unary


def db_to_edges(db, rule_constants=None):
    """Convert FactDB → (edges, labels, node_map, reverse_map)."""
    if rule_constants is None:
        rule_constants = set()

    constants = set()
    for facts in db.values():
        for args in facts:
            for a in args:
                constants.add(a)

    entities = sorted(c for c in constants if c not in rule_constants)
    node_map = {c: i for i, c in enumerate(entities)}
    for rc in sorted(constants & rule_constants):
        node_map[rc] = rc

    rev_map = {v: k for k, v in node_map.items()}

    edges, labels = [], []
    for pred in sorted(db.keys()):
        for args in sorted(db[pred]):
            if len(args) == 2:
                if args[0] in node_map and args[1] in node_map:
                    edges.append((node_map[args[0]], node_map[args[1]]))
                    labels.append(pred)
            elif len(args) == 1:
                if args[0] in node_map:
                    edges.append((node_map[args[0]], node_map[args[0]]))
                    labels.append(pred)
    return edges, labels, node_map, rev_map


def compute_opec(src, tgt, edges, labels, max_path=4):
    """Compute OPEC score (edge path complexity)."""
    adj = collections.defaultdict(set)
    for (s, t), lb in zip(edges, labels):
        if s != t:
            adj[s].add((t, lb)); adj[t].add((s, lb))
    if src == tgt:
        return sum(0.5 for (s, t), lb in zip(edges, labels) if s == src and t == tgt)
    pc = collections.defaultdict(int); pd = collections.defaultdict(set)
    queue = [(src, 0, ())]
    vad = collections.defaultdict(set); vad[0].add(src)
    while queue:
        node, ln, ps = queue.pop(0)
        if ln >= max_path:
            continue
        for nb, pr in adj.get(node, set()):
            ns = ps + (pr,); nl = ln + 1
            if nb == tgt:
                pc[nl] += 1; pd[nl].add(ns)
            elif nl < max_path and nb not in vad[nl]:
                vad[nl].add(nb); queue.append((nb, nl, ns))
    opec = sum((1.0 / l) * (pc[l] * 0.5 + len(pd[l]) * 1.0) for l in range(1, max_path + 1))
    return round(opec, 3)


# ═══════════════════════════════════════════════════════════════════════════
#  QUERY SCORING & CLASSIFICATION
# ═══════════════════════════════════════════════════════════════════════════

def estimate_depth(fact_str, entailed_facts, base_facts, rules_text):
    """Rough depth estimate based on predicate dependency distance."""
    # Build dependency graph from rules
    dep = collections.defaultdict(set)
    body_preds = set()
    for line in rules_text.split('\n'):
        line = line.strip()
        if not line or line.startswith('%') or line.startswith(':-'):
            continue
        if ':-' not in line:
            continue
        head, body = line.split(':-', 1)
        head_preds = set(re.findall(r'([a-z][a-zA-Z0-9_]*)\(', head))
        bp = set(re.findall(r'([a-z][a-zA-Z0-9_]*)\(', body))
        body_preds |= bp
        for hp in head_preds:
            for b in bp:
                dep[hp].add(b)

    # BFS from base preds
    base_preds = set()
    for f in base_facts:
        m = re.match(r'([a-z][a-zA-Z0-9_]*)\(', f)
        if m:
            base_preds.add(m.group(1))

    dist = {p: 0 for p in base_preds}
    queue = list(base_preds)
    rev = collections.defaultdict(set)
    for h, bs in dep.items():
        for b in bs:
            rev[b].add(h)
    while queue:
        p = queue.pop(0)
        for hp in rev.get(p, set()):
            if hp not in dist:
                dist[hp] = dist[p] + 1
                queue.append(hp)

    # Get the predicate of this fact
    m = re.match(r'([a-z][a-zA-Z0-9_]*)\(', fact_str)
    if m:
        return dist.get(m.group(1), 1)
    return 1


def score_difficulty(depth, n_answer_sets):
    """Score difficulty based on depth and answer set count."""
    base = depth * 30
    if depth >= 5:
        base += 50
    if depth >= 3:
        base += 20
    if n_answer_sets > 1:
        base += n_answer_sets * 5  # more answer sets = harder
    return base


def difficulty_level(score):
    if score >= 200: return "extreme"
    if score >= 150: return "very_hard"
    if score >= 100: return "hard"
    if score >= 60: return "medium"
    if score >= 30: return "easy"
    return "trivial"


# ═══════════════════════════════════════════════════════════════════════════
#  SAMPLER INTERFACE
# ═══════════════════════════════════════════════════════════════════════════

SAMPLER_CMDS = {
    # ── General samplers (positional: rules_file, num_vertices) ──
    "general_hill_climbing_sampler.py": lambda r, n, s:
        ["python3", "_S_", r, str(n), "--seed", str(s), "--iterations", "80"],
    "general_sampler_v2.py": lambda r, n, s:
        ["python3", "_S_", r, str(n), "--seed", str(s), "--iterations", "80"],
    "general_evo_sampler.py": lambda r, n, s:
        ["python3", "_S_", r, str(n), "--seed", str(s), "--population", "30", "--generations", "3"],
    "evo_sampler.py": lambda r, n, s:
        ["python3", "_S_", r, str(n), "--seed", str(s), "--population", "30", "--generations", "3"],
    "general_backward_sampler.py": lambda r, n, s:
        ["python3", "_S_", r, str(n), "--seed", str(s), "--target-proofs", "15"],
    "backward_sampler.py": lambda r, n, s:
        ["python3", "_S_", r, str(n), "--seed", str(s), "--target-proofs", "15"],
    "general_atlas_sampler.py": lambda r, n, s:
        ["python3", "_S_", r, str(n), "--seed", str(s), "--candidates", "15", "--refine", "20"],
    "atlas_sampler.py": lambda r, n, s:
        ["python3", "_S_", r, str(n), "--seed", str(s), "--candidates", "15", "--refine", "20"],
    # ── Motif (positional: num_vertices, --rules as named) ──
    "general_motif_sampler.py": lambda r, n, s:
        ["python3", "_S_", str(n), "--rules", r, "--seed", str(s), "--population", "30"],
    "motif_sampler.py": lambda r, n, s:
        ["python3", "_S_", str(n), "--rules", r, "--seed", str(s), "--population", "30"],
    # ── NoRa-specific (positional: num_vertices, --rules as named) ──
    "nora_template_sampler.py": lambda r, n, s:
        ["python3", "_S_", str(n), "--rules", r, "--seed", str(s), "--population", "10"],
    "nora_sampler.py": lambda r, n, s:
        ["python3", "_S_", str(n), "--rules", r, "--seed", str(s), "--population", "10"],
    "nora_backward_sampler.py": lambda r, n, s:
        ["python3", "_S_", str(n), "--rules", r, "--seed", str(s)],
    "nora_greedy_sampler.py": lambda r, n, s:
        ["python3", "_S_", str(n), "--rules", r, "--seed", str(s), "--restarts", "5"],
    # ── Domain-specific ──
    "medieval-kingdom_sampler.py": lambda r, n, s:
        ["python3", "_S_", str(n), "--seed", str(s)],
}


def run_sampler(abs_sampler, abs_rules, n, seed):
    """Run a sampler and return the base FactDB, or None on failure."""
    out = tempfile.mktemp(suffix='.lp', prefix='cqg_')
    key = os.path.basename(abs_sampler)
    if key in SAMPLER_CMDS:
        cmd = SAMPLER_CMDS[key](abs_rules, n, seed) + ["--output", out]
        cmd[1] = abs_sampler
    else:
        cmd = ["python3", abs_sampler, abs_rules, str(n),
               "--seed", str(seed), "--output", out]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0 or not os.path.exists(out):
            return None
        db = parse_facts_lp(out)
        return db if db_size(db) > 0 else None
    except:
        return None
    finally:
        try:
            os.remove(out)
        except:
            pass


def count_entities(base_db, rule_constants):
    """Count entity nodes only (exclude rule constants)."""
    entities = set()
    for pred, facts in base_db.items():
        for args in facts:
            for a in args:
                if a not in rule_constants:
                    entities.add(a)
    return len(entities)


def canonical_fingerprint(base_db, rule_constants):
    """Isomorphism-aware fingerprint: renames entities to canonical IDs."""
    sorted_facts = sorted((p, a) for p in base_db for a in base_db[p])
    seen = {}; counter = 0
    for pred, args in sorted_facts:
        for a in args:
            if a not in rule_constants and a not in seen:
                seen[a] = f"_e{counter}"; counter += 1
    canon = tuple(
        (pred, tuple(seen.get(a, a) for a in args))
        for pred, args in sorted_facts)
    return canon


def parse_vertex_range(vertex_arg):
    """Parse vertex argument: '6' → (6,6), '5-8' → (5,8)."""
    s = str(vertex_arg)
    if '-' in s:
        parts = s.split('-', 1)
        return int(parts[0]), int(parts[1])
    v = int(s)
    return v, v


# ═══════════════════════════════════════════════════════════════════════════
#  MAIN PIPELINE
# ═══════════════════════════════════════════════════════════════════════════

def generate_queries_clingo(rules_text, base_db, unary_preds=None, verbose=False):
    """Generate all queries using clingo (cautious consequences).

    This is the core function that mirrors the reference implementation:
      1. Build program = rules_text + base facts as ASP
      2. Run clingo → all answer sets
      3. Intersect → cautious consequences
      4. Subtract base facts → queries

    Returns list of query dicts.
    """
    if not HAS_CLINGO:
        print("ERROR: clingo is required. pip install clingo", file=sys.stderr)
        return []

    if unary_preds is None:
        unary_preds = set()

    # Build the explicit story facts as strings (for subtraction)
    explicit_facts = db_to_fact_strings(base_db)

    # Build the full program — use unary_preds to emit correct arity
    base_asp = db_to_asp_text(base_db, unary_preds=unary_preds)
    program = rules_text + "\n" + base_asp

    if verbose:
        print(f"    Program: {len(program)} chars, {db_size(base_db)} base facts",
              file=sys.stderr)

    # Run clingo and compute entailed facts
    entailed = compute_entailed_facts(program, explicit_facts)

    if verbose:
        print(f"    Entailed: {len(entailed)} non-trivial facts", file=sys.stderr)

    # Get number of answer sets for difficulty scoring
    models = run_clingo(program)
    n_models = len(models) if models else 1

    # Parse each entailed fact and build query objects
    queries = []
    for fact_str in sorted(entailed):
        pred, args = parse_fact_string(fact_str)
        if pred is None:
            continue
        # Skip unary predicates (type facts like is_person)
        if pred in unary_preds:
            continue
        # Normalise args for our internal representation
        if len(args) == 1:
            args = (args[0], args[0])

        depth = estimate_depth(fact_str, entailed, explicit_facts, rules_text)
        sc = score_difficulty(depth, n_models)
        lv = difficulty_level(sc)

        queries.append({
            "pred": pred, "args": args,
            "fact_str": fact_str,
            "depth": depth, "score": sc, "level": lv,
        })

    return queries


def generate_dataset_sampler(abs_sampler, abs_rules, vertices, num_graphs,
                              base_seed=42, verbose=False, vertex_mode="discard",
                              max_edges=None):
    """Sampler mode: generate base facts via sampler, queries via clingo."""
    with open(abs_rules) as f:
        rules_text = f.read()

    rule_constants = detect_rule_constants(rules_text)
    unary_preds = detect_unary_preds(rules_text)

    # Check for self-contained programs
    _, prog_facts = parse_program_facts(rules_text)
    n_choice = rules_text.count('{')
    if len(prog_facts) > 10 and n_choice > 0:
        if verbose:
            print(f"  Self-contained program detected → direct mode", file=sys.stderr)
        return generate_dataset_direct(abs_rules, verbose=verbose)

    rng = random.Random(base_seed)
    v_min, v_max = parse_vertex_range(vertices)
    n_attempt = max(num_graphs * 6, 20)
    seeds = [rng.randint(0, 2**31) for _ in range(n_attempt)]

    if verbose:
        v_label = f"{v_min}-{v_max}" if v_min != v_max else str(v_max)
        me_label = f", max_edges={max_edges}" if max_edges else ""
        print(f"  Sampling up to {n_attempt} graphs (target {num_graphs} unique, "
              f"entities {v_label}, mode={vertex_mode}{me_label})...", file=sys.stderr)

    seen_fps = set()
    seen_hashes = set()
    rows = []
    story_id = 0
    duplicates = 0; discarded_verts = 0; discarded_edges = 0

    for gi, seed in enumerate(seeds):
        if story_id >= num_graphs:
            break

        base_db = run_sampler(abs_sampler, abs_rules, v_max, seed)
        if base_db is None:
            continue

        # Vertex enforcement
        n_ents = count_entities(base_db, rule_constants)
        n_edges = db_size(base_db)
        if vertex_mode == "discard":
            if n_ents > v_max or n_ents < v_min:
                discarded_verts += 1
                continue

        # Edge limit
        if max_edges is not None and n_edges > max_edges:
            discarded_edges += 1
            continue

        # Dedup: canonical fingerprint
        fp = canonical_fingerprint(base_db, rule_constants)
        if fp in seen_fps:
            duplicates += 1
            continue
        # Backup hash
        raw_hash = hash(tuple(sorted((p, a) for p in base_db for a in base_db[p])))
        if raw_hash in seen_hashes:
            duplicates += 1
            continue
        seen_fps.add(fp)
        seen_hashes.add(raw_hash)

        # Generate queries via clingo
        queries = generate_queries_clingo(rules_text, base_db, unary_preds,
                                           verbose=verbose)
        if not queries:
            if verbose:
                print(f"    Graph {gi}: 0 queries, skipping", file=sys.stderr)
            continue

        # Convert to CSV rows
        edges, labels, node_map, rev_map = db_to_edges(base_db, rule_constants)

        if verbose:
            print(f"    Graph {story_id+1}: {n_ents} entities, {len(edges)} edges, "
                  f"{len(queries)} queries", file=sys.stderr)

        # Group queries by (src, tgt) edge
        edge_queries = collections.defaultdict(list)
        for q in queries:
            src_name, tgt_name = q["args"][0], q["args"][1]
            if src_name in node_map and tgt_name in node_map:
                key = (node_map[src_name], node_map[tgt_name])
                edge_queries[key].append(q)

        for (src_id, tgt_id), qs in edge_queries.items():
            all_labels = sorted(set(q["pred"] for q in qs))
            best = max(qs, key=lambda q: q["score"])
            opec = compute_opec(src_id, tgt_id, edges, labels)

            rows.append({
                "edges": str(edges),
                "edge_labels": str(labels),
                "query_edge": str((src_id, tgt_id)),
                "query_label": str(all_labels),
                "story_id": story_id,
                "categories": "[]",
                "difficulty": best["score"],
                "difficulty_level": best["level"],
                "opec": opec,
                "explanation": f"depth={best['depth']}, "
                               f"labels={all_labels}",
            })

        story_id += 1

    if verbose:
        if duplicates:
            print(f"  Deduplicated: {duplicates} identical/isomorphic graphs",
                  file=sys.stderr)
        if discarded_verts:
            print(f"  Discarded: {discarded_verts} graphs outside vertex range "
                  f"[{v_min},{v_max}]", file=sys.stderr)
        if discarded_edges:
            print(f"  Discarded: {discarded_edges} graphs exceeding {max_edges} edges",
                  file=sys.stderr)
        if story_id < num_graphs:
            print(f"  WARNING: only {story_id}/{num_graphs} unique graphs",
                  file=sys.stderr)

    return rows


def generate_dataset_direct(abs_program, verbose=False):
    """Direct mode: self-contained .lp program."""
    with open(abs_program) as f:
        rules_text = f.read()

    rule_constants = detect_rule_constants(rules_text)
    unary_preds = detect_unary_preds(rules_text)

    # Extract base facts
    base_db, _ = parse_program_facts(rules_text)

    if verbose:
        print(f"  Direct mode: {db_size(base_db)} base facts", file=sys.stderr)

    queries = generate_queries_clingo(rules_text, base_db, unary_preds,
                                       verbose=verbose)
    if not queries:
        return []

    edges, labels, node_map, rev_map = db_to_edges(base_db, rule_constants)

    if verbose:
        print(f"  {len(node_map)} nodes, {len(edges)} edges, "
              f"{len(queries)} queries", file=sys.stderr)

    edge_queries = collections.defaultdict(list)
    for q in queries:
        src_name, tgt_name = q["args"][0], q["args"][1]
        if src_name in node_map and tgt_name in node_map:
            key = (node_map[src_name], node_map[tgt_name])
            edge_queries[key].append(q)

    rows = []
    for (src_id, tgt_id), qs in edge_queries.items():
        all_labels = sorted(set(q["pred"] for q in qs))
        best = max(qs, key=lambda q: q["score"])
        opec = compute_opec(src_id, tgt_id, edges, labels)

        rows.append({
            "edges": str(edges),
            "edge_labels": str(labels),
            "query_edge": str((src_id, tgt_id)),
            "query_label": str(all_labels),
            "story_id": 0,
            "categories": "[]",
            "difficulty": best["score"],
            "difficulty_level": best["level"],
            "opec": opec,
            "explanation": f"depth={best['depth']}, labels={all_labels}",
        })

    return rows


def write_csv(rows, output_path=None):
    """Write rows to CSV file or stdout."""
    fieldnames = ["edges", "edge_labels", "query_edge", "query_label",
                  "story_id", "categories", "difficulty", "difficulty_level",
                  "opec", "explanation"]
    if output_path:
        with open(output_path, 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
            w.writeheader()
            w.writerows(rows)
    else:
        f = io.StringIO()
        w = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
        w.writeheader()
        w.writerows(rows)
        print(f.getvalue())


# ═══════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Clingo-based query generator for ASP reasoning benchmarks.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Modes:
  Sampler:  -s sampler.py -r rules.lp -n 6 [-g 2]
  Direct:   -p program.lp  (self-contained with embedded facts)
  Facts:    -r rules.lp -f base_facts.lp

Vertex range:  -n 6  or  -n 5-8
Vertex mode:   --vertex-mode discard (default) | soft
Edge limit:    --max-edges 20  (discard graphs exceeding this)

Requires clingo: pip install clingo
""")
    parser.add_argument("--sampler", "-s", default=None,
                        help="Path to sampler script")
    parser.add_argument("--rules", "-r", default=None,
                        help="Path to ASP rules file")
    parser.add_argument("--vertices", "-n", type=str, default=None,
                        help="Number of entity vertices: '6' or range '5-8'")
    parser.add_argument("--num-graphs", "-g", type=int, default=10)
    parser.add_argument("--program", "-p", default=None,
                        help="Self-contained ASP program (direct mode)")
    parser.add_argument("--facts", "-f", default=None,
                        help="Base facts file (use with --rules)")
    parser.add_argument("--vertex-mode", default="discard",
                        choices=["discard", "soft"],
                        help="'discard' rejects graphs outside vertex range (default), "
                             "'soft' accepts all")
    parser.add_argument("--max-edges", type=int, default=None,
                        help="Discard graphs with more than this many base edges")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", "-o", default=None)
    parser.add_argument("--verbose", "-v", action="store_true")
    # Strict output filters
    parser.add_argument("--max-num-edges", type=int, default=None,
                        help="Filter output: max edges per graph")
    parser.add_argument("--max-num-vertices", type=int, default=None,
                        help="Filter output: max entity vertices per graph")
    parser.add_argument("--min-num-vertices", type=int, default=None,
                        help="Filter output: min entity vertices per graph")
    args = parser.parse_args()

    if not HAS_CLINGO:
        print("ERROR: clingo is required. Install with: pip install clingo",
              file=sys.stderr)
        sys.exit(1)

    if args.program:
        # Direct mode
        abs_prog = os.path.abspath(args.program)
        if args.verbose:
            print(f"{'═'*60}", file=sys.stderr)
            print(f"  Clingo Query Generator (direct mode)", file=sys.stderr)
            print(f"{'═'*60}", file=sys.stderr)
            print(f"  Program: {args.program}", file=sys.stderr)
        rows = generate_dataset_direct(abs_prog, verbose=args.verbose)

    elif args.facts and args.rules:
        # Facts + rules mode
        with open(args.rules) as f:
            rules_text = f.read()
        base_db = parse_facts_lp(args.facts)
        unary_preds = detect_unary_preds(rules_text)
        rule_constants = detect_rule_constants(rules_text)

        if args.verbose:
            print(f"{'═'*60}", file=sys.stderr)
            print(f"  Clingo Query Generator (facts mode)", file=sys.stderr)
            print(f"{'═'*60}", file=sys.stderr)
            print(f"  Rules: {args.rules}", file=sys.stderr)
            print(f"  Facts: {args.facts}", file=sys.stderr)

        queries = generate_queries_clingo(rules_text, base_db, unary_preds,
                                           verbose=args.verbose)
        edges, labels, node_map, _ = db_to_edges(base_db, rule_constants)

        rows = []
        edge_queries = collections.defaultdict(list)
        for q in queries:
            sn, tn = q["args"][0], q["args"][1]
            if sn in node_map and tn in node_map:
                edge_queries[(node_map[sn], node_map[tn])].append(q)
        for (si, ti), qs in edge_queries.items():
            all_labels = sorted(set(q["pred"] for q in qs))
            best = max(qs, key=lambda q: q["score"])
            opec = compute_opec(si, ti, edges, labels)
            rows.append({
                "edges": str(edges), "edge_labels": str(labels),
                "query_edge": str((si, ti)), "query_label": str(all_labels),
                "story_id": 0, "categories": "[]",
                "difficulty": best["score"], "difficulty_level": best["level"],
                "opec": opec,
                "explanation": f"depth={best['depth']}, labels={all_labels}",
            })

    elif args.sampler and args.rules and args.vertices is not None:
        # Sampler mode
        abs_sampler = os.path.abspath(args.sampler)
        abs_rules = os.path.abspath(args.rules)
        if args.verbose:
            print(f"{'═'*60}", file=sys.stderr)
            print(f"  Clingo Query Generator (sampler mode)", file=sys.stderr)
            print(f"{'═'*60}", file=sys.stderr)
            print(f"  Sampler: {args.sampler}", file=sys.stderr)
            print(f"  Rules:   {args.rules}", file=sys.stderr)
            print(f"  N={args.vertices}, G={args.num_graphs}, "
                  f"mode={args.vertex_mode}"
                  f"{'  max_edges=' + str(args.max_edges) if args.max_edges else ''}",
                  file=sys.stderr)
        rows = generate_dataset_sampler(
            abs_sampler, abs_rules, args.vertices, args.num_graphs,
            base_seed=args.seed, verbose=args.verbose,
            vertex_mode=args.vertex_mode, max_edges=args.max_edges)

    else:
        parser.error("Use --program, or --sampler + --rules + --vertices, "
                      "or --rules + --facts")

    # ── Post-generation strict filters ──
    has_filters = (args.max_num_edges is not None or
                   args.max_num_vertices is not None or
                   args.min_num_vertices is not None)
    if has_filters:
        filtered_rows = []
        n_filt = 0
        for row in rows:
            try:
                edges = ast.literal_eval(row["edges"])
                nodes = set()
                for s, t in edges: nodes.add(s); nodes.add(t)
                n_edges = len(edges)
                n_ents = sum(1 for x in nodes if isinstance(x, int))

                if args.max_num_edges is not None and n_edges > args.max_num_edges:
                    n_filt += 1; continue
                if args.max_num_vertices is not None and n_ents > args.max_num_vertices:
                    n_filt += 1; continue
                if args.min_num_vertices is not None and n_ents < args.min_num_vertices:
                    n_filt += 1; continue
                filtered_rows.append(row)
            except:
                filtered_rows.append(row)

        if args.verbose and n_filt:
            print(f"  Filtered: {n_filt} rows removed by size constraints",
                  file=sys.stderr)
        rows = filtered_rows

    write_csv(rows, args.output)

    if args.verbose:
        print(f"\n  Total rows: {len(rows)}", file=sys.stderr)
        if args.output:
            print(f"  Written to: {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
