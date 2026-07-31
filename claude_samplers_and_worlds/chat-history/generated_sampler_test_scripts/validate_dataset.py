#!/usr/bin/env python3
"""
ASP Dataset Validator (clingo-based)
=====================================
Validates every query in a dataset CSV against ASP rules using clingo.

For each row, checks:
  1. BASE CONSISTENCY: base facts + rules have a stable model.
  2. QUERY DERIVABILITY: each query_label is in the stable model.
  3. QUERY NOT STATED: query facts are not already in the base graph.

Usage:
    python3 validate_dataset.py --rules nora_rules.lp --dataset data.csv
    python3 validate_dataset.py --rules rules.lp --dataset data.csv -v
    python3 validate_dataset.py --rules rules.lp --dataset data.csv -o filtered.csv
"""

import argparse, ast, csv, os, re, sys
from collections import defaultdict

try:
    from clingo import Control
    HAS_CLINGO = True
except ImportError:
    HAS_CLINGO = False

# ═══════════════════════════════════════════════════════════════════════════

def _make_ctl():
    """Create a clingo Control that suppresses info-level messages."""
    def _noop_logger(code, msg): pass
    try:
        return Control(logger=_noop_logger)
    except TypeError:
        # Older clingo without logger kwarg
        return Control()

def run_clingo(program):
    """Run clingo and return list of answer sets (set of symbols)."""
    ctl = _make_ctl()
    ctl.configuration.solve.models = 0
    ctl.add("base", [], program)
    ctl.ground([("base", [])])
    models = []
    with ctl.solve(yield_=True) as handle:
        for model in handle:
            models.append(set(model.symbols(shown=True)))
    return models

def check_sat(program):
    """Check if program has at least one stable model."""
    ctl = _make_ctl()
    ctl.configuration.solve.models = 1
    ctl.add("base", [], program)
    ctl.ground([("base", [])])
    return ctl.solve().satisfiable

def derive_facts(rules_text, base_text):
    """Get all facts in the first stable model. Returns set of (pred, args)."""
    program = rules_text + "\n" + base_text
    ctl = _make_ctl()
    ctl.configuration.solve.models = 1
    ctl.add("base", [], program)
    ctl.ground([("base", [])])
    derived = set()
    with ctl.solve(yield_=True) as handle:
        for model in handle:
            for sym in model.symbols(shown=True):
                derived.add((sym.name, tuple(str(a) for a in sym.arguments)))
            break
    return derived

# ═══════════════════════════════════════════════════════════════════════════

def edges_to_asp(edges, labels, rules_text=""):
    """Convert edges+labels → ASP text + name map.

    Node IDs can be integers (entity nodes, mapped to nX) or strings
    (rule constants like 'senior', kept as-is).
    Detects truly-unary predicates from rules_text and writes them correctly.
    """
    nodes = set()
    for s, t in edges:
        nodes.add(s); nodes.add(t)

    # Build name map: integers → nX, strings → keep as-is
    names = {}
    for nid in sorted(nodes, key=lambda x: (isinstance(x, str), str(x))):
        if isinstance(nid, int):
            names[nid] = f"n{nid}"
        else:
            # String node = rule constant (e.g. "senior"), keep as-is
            names[nid] = str(nid)

    # Detect unary predicates from rules text
    unary_preds = set()
    if rules_text:
        for m in re.finditer(r'([a-z_]\w*)\(([^)]+)\)', rules_text):
            pred = m.group(1)
            args = [a.strip() for a in m.group(2).split(',')]
            if len(args) == 1:
                unary_preds.add(pred)

    facts = []
    for (s, t), lb in zip(edges, labels):
        if s == t and lb in unary_preds:
            facts.append(f"{lb}({names[s]}).")
        else:
            facts.append(f"{lb}({names[s]},{names[t]}).")
    return "\n".join(facts), names

def strip_embedded_facts(rules_text, base_asp=""):
    """Remove ground facts from rules text that would cause entity contamination.

    Keeps:
      - All rules and constraints (lines with ':-')
      - Ground facts whose constants appear in the sampled base edges
      - Ground facts whose predicate appears in rule bodies (structural facts
        like outranks(senior,junior) that rules depend on)
    Strips:
      - Entity-definition facts like noble(arthur) when 'arthur' doesn't
        appear in any sampled edge
    """
    # Collect constants from the sampled edges
    base_constants = set()
    if base_asp:
        for m in re.finditer(r'([a-z_]\w*)', base_asp):
            base_constants.add(m.group(1))

    # Collect predicates that appear in rule bodies (structural dependencies)
    body_preds = set()
    for line in rules_text.split('\n'):
        s = line.strip()
        if not s or s.startswith('%'): continue
        if ':-' in s:
            body = s.split(':-', 1)[1]
            for m in re.finditer(r'([a-z_]\w*)\(', body):
                body_preds.add(m.group(1))

    lines = rules_text.split('\n')
    kept = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('%') or ':-' in stripped:
            kept.append(line); continue
        has_var = bool(re.search(r'\b[A-Z][A-Za-z0-9]*\b', stripped))
        if has_var: kept.append(line); continue

        # Ground fact — check if we should keep it
        # Extract predicate name
        pred_match = re.match(r'([a-z_]\w*)\(', stripped)
        pred_name = pred_match.group(1) if pred_match else ""

        # Keep if: predicate is used in rule bodies (structural)
        if pred_name in body_preds:
            kept.append(line); continue

        # Keep if: any constant overlaps with sampled edges
        fact_consts = set(re.findall(r'([a-z_]\w*)', stripped))
        for m in re.finditer(r'([a-z_]\w*)\(', stripped):
            fact_consts.discard(m.group(1))
        if fact_consts & base_constants:
            kept.append(line); continue

        # Entity fact with no structural use and no overlap → strip

    return '\n'.join(kept)


def validate_row(idx, row, rules_text, verbose=False):
    """Validate one CSV row. Returns (valid, errors).

    Strips embedded facts from rules_text that don't overlap with the
    row's edge constants, preventing entity contamination when validating
    sampler-generated graphs against self-contained rule files.
    """
    errors = []
    try:
        edges = ast.literal_eval(row["edges"])
        labels = ast.literal_eval(row["edge_labels"])
        qedge = ast.literal_eval(row["query_edge"])
        qlabels = ast.literal_eval(row["query_label"])
    except Exception as e:
        return False, [f"PARSE ERROR: {e}"]

    if len(edges) != len(labels):
        errors.append(f"MISMATCH: {len(edges)} edges vs {len(labels)} labels")
        return False, errors

    base_asp, names = edges_to_asp(edges, labels, rules_text)
    rules_only_text = strip_embedded_facts(rules_text, base_asp)

    # Map query endpoints: integers → nX, strings → keep as-is
    qs, qt = qedge
    qsn = names.get(qs, f"n{qs}" if isinstance(qs, int) else str(qs))
    qtn = names.get(qt, f"n{qt}" if isinstance(qt, int) else str(qt))

    if not HAS_CLINGO:
        if not edges: errors.append("EMPTY GRAPH")
        if not qlabels: errors.append("NO QUERY LABELS")
        return len(errors) == 0, errors

    # Check 1: Base consistency
    program = rules_only_text + "\n" + base_asp
    try:
        if not check_sat(program):
            errors.append("CONSTRAINT VIOLATION: base facts have no stable model")
    except Exception as e:
        errors.append(f"CLINGO ERROR (base): {e}")

    # Check 2: Query derivability
    try:
        derived = derive_facts(rules_only_text, base_asp)
        for ql in qlabels:
            # Try both binary and unary forms
            found = False
            if (ql, (qsn, qtn)) in derived:
                found = True
            elif qs == qt and (ql, (qsn,)) in derived:
                found = True  # unary form
            if not found:
                errors.append(f"NOT DERIVABLE: {ql}({qsn},{qtn})")
    except Exception as e:
        errors.append(f"CLINGO ERROR (derive): {e}")

    # Check 3: Query not already stated
    base_set = set()
    for (s, t), lb in zip(edges, labels):
        base_set.add((lb, (names.get(s, f"n{s}"), names.get(t, f"n{t}"))))
    for ql in qlabels:
        if (ql, (qsn, qtn)) in base_set:
            errors.append(f"ALREADY STATED: {ql}({qsn},{qtn})")

    return len(errors) == 0, errors

# ═══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Validate ASP dataset with clingo.")
    parser.add_argument("--rules", "-r", required=True, help="ASP rules file")
    parser.add_argument("--dataset", "-d", required=True, help="CSV dataset file")
    parser.add_argument("--output", "-o", default=None,
                        help="Output CSV with only valid rows (filtered)")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--stop-on-error", action="store_true")
    parser.add_argument("--max-rows", type=int, default=None)
    # Strict graph size filters
    parser.add_argument("--max-num-edges", type=int, default=25,
                        help="Maximum number of edges per graph (default: 25)")
    parser.add_argument("--max-num-vertices", type=int, default=8,
                        help="Maximum number of entity vertices per graph (default: 8)")
    parser.add_argument("--min-num-vertices", type=int, default=5,
                        help="Minimum number of entity vertices per graph (default: 5)")
    parser.add_argument("--no-filter", action="store_true",
                        help="Disable all size filters")
    args = parser.parse_args()

    if not HAS_CLINGO:
        print("WARNING: clingo not installed. pip install clingo", file=sys.stderr)
        print("Running structural checks only.\n", file=sys.stderr)

    with open(args.rules) as f: rules_text = f.read()
    with open(args.dataset) as f: rows = list(csv.DictReader(f))

    if not rows:
        print("ERROR: empty dataset"); sys.exit(1)

    fieldnames = list(rows[0].keys())
    rows = rows[:args.max_rows] if args.max_rows else rows

    print(f"{'═'*60}")
    print(f"  ASP Dataset Validator {'(clingo)' if HAS_CLINGO else '(limited)'}")
    print(f"{'═'*60}")
    print(f"  Rules:   {args.rules}")
    print(f"  Dataset: {args.dataset}  ({len(rows)} rows)")
    if args.output:
        print(f"  Output:  {args.output}")
    if not args.no_filter:
        print(f"  Filters: vertices=[{args.min_num_vertices},{args.max_num_vertices}], "
              f"edges≤{args.max_num_edges}")
    print(f"{'═'*60}\n")

    total = valid = 0
    filtered_edges = 0; filtered_verts_max = 0; filtered_verts_min = 0
    etypes = defaultdict(int)
    all_errors = []
    valid_rows = []

    for i, row in enumerate(rows):
        total += 1

        # ── Size filters (applied before clingo validation) ──
        if not args.no_filter:
            try:
                edges = ast.literal_eval(row["edges"])
                # Count edges
                n_edges = len(edges)
                if n_edges > args.max_num_edges:
                    filtered_edges += 1
                    if args.verbose:
                        print(f"  Row {i+1:>4}: FILTERED ({n_edges} edges > {args.max_num_edges})")
                    continue
                # Count entity vertices (integers = entities, strings = rule constants)
                nodes = set()
                for s, t in edges: nodes.add(s); nodes.add(t)
                n_ents = sum(1 for x in nodes if isinstance(x, int))
                if n_ents > args.max_num_vertices:
                    filtered_verts_max += 1
                    if args.verbose:
                        print(f"  Row {i+1:>4}: FILTERED ({n_ents} vertices > {args.max_num_vertices})")
                    continue
                if n_ents < args.min_num_vertices:
                    filtered_verts_min += 1
                    if args.verbose:
                        print(f"  Row {i+1:>4}: FILTERED ({n_ents} vertices < {args.min_num_vertices})")
                    continue
            except Exception:
                pass  # let validate_row handle parse errors

        ok, errs = validate_row(i+1, row, rules_text, args.verbose)
        if ok:
            valid += 1
            valid_rows.append(row)
            if args.verbose:
                ql = row.get("query_label","?")[:50]
                print(f"  Row {i+1:>4} [story={row.get('story_id','?')}]: ✓  {ql}")
        else:
            for e in errs:
                et = e.split(":")[0]
                etypes[et] += 1
                all_errors.append((i+1, e))
                if args.verbose:
                    print(f"  Row {i+1:>4} [story={row.get('story_id','?')}]: ✗ {e}")
            if args.stop_on_error:
                print(f"\n  Stopped at row {i+1}"); break

    # Write filtered output
    if args.output and valid_rows:
        with open(args.output, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
            writer.writeheader()
            writer.writerows(valid_rows)

    n_filtered = filtered_edges + filtered_verts_max + filtered_verts_min
    n_errors = total - valid - n_filtered

    print(f"\n{'═'*60}")
    print(f"  VALIDATION SUMMARY")
    print(f"{'═'*60}")
    print(f"  Total rows:  {total}")
    if n_filtered:
        print(f"  Filtered:    {n_filtered}")
        if filtered_edges:
            print(f"    edges > {args.max_num_edges}:     {filtered_edges}")
        if filtered_verts_max:
            print(f"    vertices > {args.max_num_vertices}:   {filtered_verts_max}")
        if filtered_verts_min:
            print(f"    vertices < {args.min_num_vertices}:   {filtered_verts_min}")
    validated = total - n_filtered
    print(f"  Validated:   {validated}")
    print(f"  Valid:       {valid} ({valid*100//max(validated,1)}%)")
    print(f"  Errors:      {n_errors} ({n_errors*100//max(validated,1)}%)")

    if etypes:
        print(f"\n  Error breakdown:")
        for et, c in sorted(etypes.items(), key=lambda x: -x[1]):
            print(f"    {et:<35} {c:>4}")

    if all_errors and not args.verbose:
        print(f"\n  First errors:")
        for ri, e in all_errors[:10]:
            print(f"    Row {ri}: {e}")

    if n_errors == 0 and validated > 0:
        verdict = f"✓ ALL VALID ({valid} rows)"
        if n_filtered:
            verdict += f", {n_filtered} filtered out"
    elif validated == 0 and n_filtered > 0:
        verdict = f"⚠ All {n_filtered} rows filtered out (none validated)"
    else:
        verdict = f"✗ {n_errors} ERRORS"
        if n_filtered:
            verdict += f", {n_filtered} filtered out"
    print(f"\n  {verdict}")
    if args.output and valid_rows:
        print(f"  Written {len(valid_rows)} valid rows to {args.output}")
    print(f"{'═'*60}")
    sys.exit(0 if n_errors == 0 else 1)

if __name__ == "__main__":
    main()
