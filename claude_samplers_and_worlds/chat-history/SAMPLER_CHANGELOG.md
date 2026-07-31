# ASP Sampler Pipeline — Iterative Improvement Changelog

## Overview

This document tracks every bug fix and improvement made to the 8 samplers
(3 NoRa-specific + 5 general) and the pipeline tools across the full
development cycle. Each fix was discovered through testing, user feedback
from real clingo runs, or analysis of validation failures.

---

## 1. Entity Contamination in Validator

**Discovered:** Validator was feeding the FULL rules text (including embedded
ground facts like `noble(arthur)`) to clingo alongside sampled edges
(`noble(n0)`). Clingo saw both entity sets, derived cross-world relations,
and constraints fired on 100% of rows.

**Fix:** `validate_dataset.py` — new `strip_embedded_facts(rules_text, base_asp)`
function. Before feeding rules to clingo, strips ground facts whose constants
don't appear in the reconstructed edges. Preserves structural constants
(SpyNet's `outranks(senior,junior)` — because `senior` appears in sampled
edges) while stripping entity data (`noble(arthur)` — because `arthur`
doesn't appear).

**Affected:** All self-contained rule sets (claude-\*.lp, geminipro-\*.lp, deepseek-\*.lp)

---

## 2. Vertex Limit Enforcement

**Discovered:** User requested 5–8 vertex graphs but samplers were producing
graphs with 10–19 entities. Each sampler allocated entities differently and
the vertex budget wasn't being respected.

**Fix:** Two-mode system implemented across ALL 8 samplers + both generators:

- `--vertex-mode discard` (default): reject graphs outside vertex range
- `--vertex-mode soft`: accept all graphs regardless of vertex count
- Removed a proposed "pruning" mode (user feedback: pruning edges to reduce
  vertices breaks semantic coherence)

**Per-sampler vertex budget fixes:**

| Sampler | Before | After |
|---|---|---|
| general_hc/evo/atlas | `target = max(2, n//(1+rank))` | Proportional budget summing to N |
| general_backward | Unbounded | `persons[:max(2, n-2)]` (reserves 2 for places) |
| general_motif | Unbounded | `name_pool[:n - n_places]` |
| nora_template | `n_persons = max(3, n - 2)` | `n_reserve = 1 if n<=5 else 2` (adaptive) |
| nora_backward | Fixed 2 reserved | `remaining = max(3, target_n - 2)` |
| nora_greedy | Fixed 2 reserved | `person_target = max(3, target_n - 2)` |

---

## 3. Graph Deduplication

**Discovered:** User noticed identical edge/query counts across all graphs
from a sampler. Suspected duplicates.

**Fix:** Added canonical isomorphism fingerprinting to `dataset_generator.py`
and `clingo_query_generator.py`:

- Canonical fingerprint via sorted relabeled facts (entities → `_e0, _e1...`
  by appearance order, rule constants preserved)
- Raw hash backup for fast rejection
- Over-sampling 6× target to compensate for duplicates/discards
- WARNING when not enough unique graphs found

**Analysis proved:** Graphs with identical counts ARE diverse — NoRa's
regularity (a family of N persons always needs ~21 edges) produces equal
counts but different family structures (Jaccard similarity 0.06–0.23).

---

## 4. Self-Referential Predicate Handling (SpyNet)

**Discovered:** SpyNet has 50+ binary predicates used only as `p(X,X)`
(e.g., `captured`, `flagged_hostile`, `compromised`, `is_agent`, `reliable`).
Samplers were generating `captured(b0, a0)` instead of `captured(a0, a0)`.
This caused 76+ validation errors on SpyNet.

**Fix applied to ALL 5 general samplers:**

1. **Detection:** Added `self_ref: Set[str]` to each sampler's Analysis
   dataclass. Scans all rules: a binary predicate is self-ref if EVERY
   occurrence has identical args.

2. **Fact generation:** `gen_fact()` / `gen_random_fact()` returns `(c, c)`
   when `pred in self_ref`.

3. **Guards:** `safe_add()` rejects `p(X, Y)` where `X != Y` for self-ref
   predicates.

4. **Per-sampler details:**

| Sampler | Changes |
|---|---|
| `general_backward` | `safe_add` guard + leaf/root instantiation force `(c,c)` |
| `general_hill_climbing` | `gen_random_fact` returns `(c,c)` for self-ref |
| `general_evo` | `gen_fact` returns `(c,c)` + `inject_join` forces equal args |
| `general_motif` | Replaced `is_*` heuristic with proper `self_ref` check, threaded through `stitch_motifs` → `instantiate_motif` |
| `general_atlas` | Already had detection, added `safe_add` guard + `build_chains` skips self-ref preds |

---

## 5. Arity Mismatch Bug (clingo_query_generator)

**Discovered:** ALL NoRa samplers failed validation (26–56 errors each)
when using `clingo_query_generator.py`. Manual runs with the same data
worked fine.

**Root cause:** `db_to_asp_text()` was writing ALL self-loop facts
`p(X,X)` as unary form `p(X).`. But NoRa rules use binary form
`is_female(X,X)`. Clingo treats `is_female/1` and `is_female/2` as
**different predicates**, so no rules fired.

**Fix:** `db_to_asp_text(db, unary_preds=None)` now accepts a `unary_preds`
set (detected by `detect_unary_preds(rules_text)`). Only emits unary form
when the predicate actually appears with arity 1 in the rules.

| Rule set | Predicate | In rules | Now emitted as |
|---|---|---|---|
| NoRa | `is_female` | `is_female(X,X)` | `is_female(a,a).` ✓ |
| NoRa | `is_person` | `is_person(X)` | `is_person(a).` ✓ |
| SpyNet | `is_agent` | `is_agent(X)` | `is_agent(a).` ✓ |
| SpyNet | `captured` | `captured(X,X)` | `captured(b,b).` ✓ |

**Note:** `dataset_generator.py` already had this correct via its
`original_arity` dict. Only `clingo_query_generator.py` was affected.

---

## 6. Rule Constants Preservation

**Discovered:** SpyNet uses ground constants in rule facts (`senior`,
`junior`, `top` in `outranks(senior,junior).`). Samplers were treating
these as entity nodes, inflating vertex counts and breaking type inference.

**Fix:** Added `rule_constants` detection to all general samplers. Constants
found in ground rule facts are:

- Preserved as string node IDs (not mapped to integer entities)
- Excluded from entity name pools
- Handled in `rc_slots` for correct type placement

---

## 7. Atlas Sampler: SCC-Aware Seedable Detection

**Discovered:** On NoRa (292 rules, all predicates cyclically dependent),
the atlas sampler's naive seedable detection returned either too many or
zero predicates. Constraint violations on 100% of candidates.

**Fix:** Replaced simple `pure_base` detection with Tarjan SCC analysis:

- Compute SCCs of the dependency graph
- Within each SCC, rank predicates by fanout (how often used in rule bodies)
- Take top `max(2, |SCC|/8)` per SCC as seedable
- Exclude `no_*`, `not_*`, and utility predicates
- Fixed deep_targets to use BFS distance from seedable set (not strata,
  which was 0 for all NoRa predicates due to cyclic dependencies)

---

## 8. Atlas Sampler: Batch Constraint Checking

**Discovered:** Atlas's diversity spray was adding facts one-by-one.
A single bad fact (e.g., `is_female(a1,a1)` + `is_male(a1,a1)`) would
violate constraints, but the damage was already done.

**Fix:** Generate candidate facts in a pool, add them in batches of 3,
check constraints after each batch. Undo the entire batch if any constraint
fires. This prevents cascading violations while allowing rapid growth.

---

## 9. Symmetric Base Predicate Handling

**Discovered:** Predicates like `spouse_of`, `sibling_of` whose ONLY
derivation rules are symmetry rules (`spouse_of(Y,X) :- spouse_of(X,Y)`)
were not detected as seedable.

**Fix:** All general samplers now detect symmetric base predicates and
include them in the seedable set. Detection checks: predicate appears in
both head and body, ALL rules for it are purely symmetric (1 body literal,
same predicate, args swapped).

---

## 10. `--max-edges` Parameter

**Discovered:** User wanted to control edge count without modifying
sampler internals.

**Decision:** NOT modifying samplers — edges are structurally necessary
for semantic coherence. Instead, added `--max-edges` as a discard filter
to both `dataset_generator.py` and `clingo_query_generator.py`.

```bash
python3 dataset_generator.py -s sampler.py -r rules.lp -n 6 -g 5 --max-edges 15
```

Graphs exceeding the limit are silently discarded before query generation.
Over-sampling (6×) ensures enough graphs survive.

---

## 11. Test Pipeline Script Bug

**Discovered:** User ran `test_pipeline.py` and saw 18/18 failures. But
manual runs of the same commands worked fine.

**Root cause:** Three bugs in `test_pipeline.py`:

1. **Wrong field names:** Script parsed `Total:` but validator prints `Total rows:`
   → `total` always stayed at 0 → every test hit the else-branch → FAIL
2. **Missing `--no-filter`:** Validator's default filters (max 20 edges,
   5-8 vertices) skipped rows → `total=0` even when validation passed
3. **Negative error counts:** `errors = total - valid = 0 - valid = -valid`

**Interpretation of user's output:**
- `FAIL 38 — 0 validation errors` = actually PASS (test logic bug)
- `FAIL 52 — -52 validation errors` = actually 52/52 valid (parsing bug)

**Fix:** Updated `run_validator` to parse `Total rows:` / `Validated:` /
`Valid:`, added `--no-filter`, and used `max(0, total - valid)`.

---

## 12. CLI Standardization

Both generators now share identical CLI parameters:

```
-s SAMPLER -r RULES -n VERTICES -g NUM_GRAPHS
-n supports "6" or range "5-8"
--vertex-mode {discard,soft}
--max-edges N
--output CSV
--verbose
```

---

## 13. Analysis Tools Enhanced

**`graph_analyzer.py`** — Now accepts directories and glob patterns:
```bash
python3 graph_analyzer.py dir1/ dir2/ --viz dashboard.html
```

**`sampler_comparator.py`** (new) — Side-by-side sampler comparison with
named groups, HTML dashboard with radar/bar charts, JSON export:
```bash
python3 sampler_comparator.py atlas=dir1/ hc=dir2/ --viz report.html
```

---

## Timeline of Fixes by Trigger

| # | Trigger | What broke | Fix |
|---|---|---|---|
| 1 | Self-contained rules validation | Entity contamination | `strip_embedded_facts` context-aware |
| 2 | User: graphs too large | 10-19 entities for N=6 | Per-sampler vertex budgets |
| 3 | User: identical counts | Suspected duplicates | Canonical fingerprint dedup |
| 4 | User: SpyNet 76 errors | `captured(b0,a0)` | Self-ref detection in 5 samplers |
| 5 | User: NoRa all fail | `is_female(a).` vs `is_female(a,a).` | Arity-aware `db_to_asp_text` |
| 6 | SpyNet rule constants | `senior`/`junior` as entities | Rule constant detection |
| 7 | Atlas × NoRa: 0 score | Cyclic deps → bad seedable | SCC Tarjan + take limits |
| 8 | Atlas × NoRa: constraints | Random facts violate | Batch constraint checking |
| 9 | Empty seedable on some rules | Symmetric preds excluded | Symmetric base detection |
| 10 | User: want edge control | No edge parameter | `--max-edges` discard filter |
| 11 | User: 18/18 test failures | Test script parsing bug | Fixed field names + `--no-filter` |
