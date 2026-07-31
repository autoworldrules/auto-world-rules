#!/usr/bin/env python3
"""
ASP Benchmark Pipeline — Integration Test Suite
=================================================

Runs every relevant combination of sampler × rule set through the
dataset generator, then validates each output with the clingo-based
validator.  Summarises all results in a single table.

Usage:
    python3 test_pipeline.py --generator dataset_generator.py
    python3 test_pipeline.py --generator dataset_generator.py --validator validate_dataset.py
    python3 test_pipeline.py --generator dataset_generator.py -v          # verbose
    python3 test_pipeline.py --generator dataset_generator.py --quick     # fewer graphs

The script auto-discovers samplers and rule sets in the current
directory (or you can override with --sampler-dir / --rules-dir).
"""

import argparse, csv, os, subprocess, sys, tempfile, time
from pathlib import Path

# ═══════════════════════════════════════════════════════════════════════════
#  TEST MATRIX
# ═══════════════════════════════════════════════════════════════════════════

# (sampler, rules, vertices, num_graphs, mode)
#   mode = "sampler" or "direct"
# Domain-specific samplers are only tested with their target domain.
# General samplers are tested with ALL compatible rule sets.

TESTS = [
    # ── NoRa domain ──
    ("nora_template_sampler.py",       "nora_rules.lp",   6, 2, "sampler"),
    ("nora_backward_sampler.py",       "nora_rules.lp",   6, 2, "sampler"),
    ("nora_greedy_sampler.py",         "nora_rules.lp",   6, 2, "sampler"),
    ("general_hill_climbing_sampler.py","nora_rules.lp",   6, 2, "sampler"),
    ("general_evo_sampler.py",         "nora_rules.lp",   6, 2, "sampler"),
    ("general_motif_sampler.py",       "nora_rules.lp",   6, 2, "sampler"),
    ("general_backward_sampler.py",    "nora_rules.lp",   6, 2, "sampler"),
    ("general_atlas_sampler.py",       "nora_rules.lp",   6, 1, "sampler"),

    # ── SpyNet domain (NAF rules) ──
    ("general_hill_climbing_sampler.py","spynet_rules.lp", 8, 2, "sampler"),
    ("general_evo_sampler.py",         "spynet_rules.lp", 8, 2, "sampler"),
    ("general_motif_sampler.py",       "spynet_rules.lp", 8, 2, "sampler"),
    ("general_backward_sampler.py",    "spynet_rules.lp", 8, 2, "sampler"),
    ("general_atlas_sampler.py",       "spynet_rules.lp", 8, 1, "sampler"),

    # ── Medieval domain ──
    ("general_hill_climbing_sampler.py","rules.lp",        8, 1, "sampler"),
    ("general_evo_sampler.py",         "rules.lp",        8, 1, "sampler"),
    ("general_motif_sampler.py",       "rules.lp",        8, 1, "sampler"),
    ("general_backward_sampler.py",    "rules.lp",        8, 1, "sampler"),
    ("general_atlas_sampler.py",       "rules.lp",        8, 1, "sampler"),

    # ── Iron Coast domain (multi-type, deep chains) ──
    ("general_hill_climbing_sampler.py","ironcoast.lp",   10, 1, "sampler"),
    ("general_evo_sampler.py",         "ironcoast.lp",   10, 1, "sampler"),
    ("general_motif_sampler.py",       "ironcoast.lp",   10, 1, "sampler"),
    ("general_backward_sampler.py",    "ironcoast.lp",   10, 1, "sampler"),
    ("general_atlas_sampler.py",       "ironcoast.lp",   10, 1, "sampler"),

    # ── Veranthos (self-contained with choice rules) ──
    (None,                             "claude-1-se4.lp",  0, 0, "direct"),
    ("general_hill_climbing_sampler.py","claude-1-se4.lp",10, 1, "sampler"),
]


# ═══════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def find_file(name, search_dirs):
    """Search for a file in a list of directories."""
    for d in search_dirs:
        p = os.path.join(d, name)
        if os.path.exists(p):
            return os.path.abspath(p)
    return None


def run_generator(generator, sampler, rules, vertices, num_graphs, mode,
                  output_csv, verbose=False):
    """Run the dataset generator and return (success, rows, stderr)."""
    if mode == "direct":
        cmd = ["python3", generator, "--program", rules,
               "--output", output_csv, "--verbose"]
    else:
        cmd = ["python3", generator,
               "--sampler", sampler, "--rules", rules,
               "--vertices", str(vertices), "--num-graphs", str(num_graphs),
               "--output", output_csv, "--verbose"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        stderr = result.stderr + result.stdout
        if result.returncode != 0:
            return False, 0, stderr
        if os.path.exists(output_csv):
            with open(output_csv) as f:
                rows = sum(1 for _ in csv.DictReader(f))
            return True, rows, stderr
        return False, 0, stderr
    except subprocess.TimeoutExpired:
        return False, 0, "TIMEOUT (180s)"
    except Exception as e:
        return False, 0, str(e)


def run_validator(validator, rules, dataset, verbose=False):
    """Run the clingo-based validator. Returns (total, valid, errors, details)."""
    cmd = ["python3", validator, "--rules", rules, "--dataset", dataset,
           "--no-filter"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        output = result.stdout + result.stderr
        # Parse summary — validator prints "Total rows:" and "Valid:"
        total = valid = 0
        for line in output.split('\n'):
            line = line.strip()
            if line.startswith('Total rows:'):
                try: total = int(line.split(':', 1)[1].strip())
                except ValueError: pass
            elif line.startswith('Validated:'):
                try:
                    v = int(line.split(':', 1)[1].strip())
                    # "Validated" is the count excluding skipped rows — use as total
                    # when "Total rows:" includes filtered ones
                    if total == 0: total = v
                except ValueError: pass
            elif line.startswith('Valid:'):
                try:
                    # Format: "Valid:       10 (100%)"
                    valid = int(line.split(':', 1)[1].strip().split()[0])
                except (ValueError, IndexError): pass
        errors = max(0, total - valid)
        return total, valid, errors, output
    except subprocess.TimeoutExpired:
        return 0, 0, 0, "TIMEOUT (120s)"
    except Exception as e:
        return 0, 0, 0, str(e)


# ═══════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Integration test suite for ASP benchmark pipeline.")
    parser.add_argument("--generator", "-g", required=True,
                        help="Path to dataset_generator.py")
    parser.add_argument("--validator", default=None,
                        help="Path to validate_dataset.py (auto-detect if omitted)")
    parser.add_argument("--sampler-dir", default=None,
                        help="Directory containing sampler scripts")
    parser.add_argument("--rules-dir", default=None,
                        help="Directory containing rule files")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--quick", "-q", action="store_true",
                        help="Reduce graph count for faster testing")
    args = parser.parse_args()

    generator = os.path.abspath(args.generator)
    if not os.path.exists(generator):
        print(f"ERROR: generator not found: {generator}"); sys.exit(1)

    # Auto-detect validator
    gen_dir = os.path.dirname(generator)
    cwd = os.getcwd()
    search = [cwd, gen_dir, os.path.dirname(os.path.abspath(__file__))]

    if args.validator:
        validator = os.path.abspath(args.validator)
    else:
        validator = find_file("validate_dataset.py", search)
    has_validator = validator and os.path.exists(validator)

    # Search directories for samplers and rules
    sampler_dirs = [args.sampler_dir, cwd, gen_dir] if args.sampler_dir else [cwd, gen_dir]
    rules_dirs = [args.rules_dir, cwd, gen_dir] if args.rules_dir else [cwd, gen_dir]
    sampler_dirs = [d for d in sampler_dirs if d]
    rules_dirs = [d for d in rules_dirs if d]

    # Header
    print(f"{'═'*75}")
    print(f"  ASP Benchmark Pipeline — Integration Test Suite")
    print(f"{'═'*75}")
    print(f"  Generator:  {generator}")
    print(f"  Validator:  {validator or 'NOT FOUND (skipping validation)'}")
    print(f"  Samplers:   searching {sampler_dirs}")
    print(f"  Rules:      searching {rules_dirs}")
    print(f"{'═'*75}")
    print()

    results = []
    tmpdir = tempfile.mkdtemp(prefix="asp_test_")
    n_pass = n_fail = n_skip = 0

    for test_idx, (sampler_name, rules_name, vertices, num_graphs, mode) in enumerate(TESTS):
        if args.quick and num_graphs > 1:
            num_graphs = 1

        # Resolve paths
        rules_path = find_file(rules_name, rules_dirs)
        if not rules_path:
            label = f"{sampler_name or 'DIRECT'} × {rules_name}"
            results.append((label, "SKIP", 0, 0, 0, "rules file not found"))
            n_skip += 1
            continue

        if mode == "sampler":
            sampler_path = find_file(sampler_name, sampler_dirs)
            if not sampler_path:
                label = f"{sampler_name} × {rules_name}"
                results.append((label, "SKIP", 0, 0, 0, "sampler not found"))
                n_skip += 1
                continue
            label = f"{sampler_name:<26} × {rules_name}"
        else:
            sampler_path = None
            label = f"{'DIRECT':<26} × {rules_name}"

        csv_path = os.path.join(tmpdir, f"test_{test_idx}.csv")

        # ── Generate ──
        if args.verbose:
            print(f"  [{test_idx+1}/{len(TESTS)}] {label}")

        t0 = time.time()
        ok, rows, stderr = run_generator(
            generator, sampler_path, rules_path, vertices, num_graphs,
            mode, csv_path, verbose=args.verbose)
        gen_time = time.time() - t0

        if not ok or rows == 0:
            status = "FAIL"
            reason = "no output" if rows == 0 else stderr.strip().split('\n')[-1][:60]
            # Check if it specifically requires clingo (not just mentions it)
            if "requires clingo" in stderr.lower() or "ERROR: This program requires clingo" in stderr:
                status = "SKIP"
                reason = "needs clingo"
                n_skip += 1
            elif rows == 0 and "no viable graph" in stderr.lower():
                status = "WARN"
                reason = "sampler found no viable graphs"
                n_skip += 1
            else:
                n_fail += 1
            results.append((label, status, rows, 0, 0, reason))
            if args.verbose:
                print(f"    → {status}: {reason}")
            continue

        # ── Validate ──
        if has_validator and rows > 0:
            total, valid, errors, val_output = run_validator(
                validator, rules_path, csv_path, verbose=args.verbose)
            val_rate = f"{valid}/{total}" if total > 0 else "—"
        else:
            total = valid = errors = 0
            val_rate = "—"

        if total > 0 and errors == 0:
            status = "PASS"
            n_pass += 1
        elif total > 0:
            status = "FAIL"
            n_fail += 1
        elif not has_validator:
            status = "GEN OK"
            n_pass += 1
        else:
            status = "FAIL"
            n_fail += 1

        reason = f"gen={gen_time:.1f}s" if status in ("PASS", "GEN OK") else f"{errors} validation errors"
        results.append((label, status, rows, valid, total, reason))

        if args.verbose:
            sym = "✓" if status in ("PASS", "GEN OK") else "✗"
            print(f"    → {sym} {rows} rows, validate {val_rate}, {gen_time:.1f}s")

    # ── Summary table ──
    print()
    print(f"{'═'*75}")
    print(f"  TEST RESULTS")
    print(f"{'═'*75}")
    print(f"  {'Test':<48} {'Status':>6} {'Rows':>5} {'Valid':>7}  Notes")
    print(f"  {'─'*48} {'─'*6} {'─'*5} {'─'*7}  {'─'*20}")

    for label, status, rows, valid, total, reason in results:
        val_str = f"{valid}/{total}" if total > 0 else "—"
        sym = {"PASS": "✓", "GEN OK": "~", "FAIL": "✗", "SKIP": "○", "WARN": "⚠"}
        s = sym.get(status, "?")
        print(f"  {s} {label:<47} {status:>6} {rows:>5} {val_str:>7}  {reason}")

    print(f"  {'─'*75}")
    print(f"  PASS: {n_pass}   FAIL: {n_fail}   SKIP: {n_skip}   TOTAL: {len(results)}")

    verdict = "ALL PASS" if n_fail == 0 else f"{n_fail} FAILURES"
    print(f"  {verdict}")
    print(f"{'═'*75}")

    # Cleanup
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)

    sys.exit(0 if n_fail == 0 else 1)


if __name__ == "__main__":
    main()
