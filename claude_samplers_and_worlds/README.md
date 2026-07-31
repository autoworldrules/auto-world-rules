# Claude Samplers and Worlds

Graph samplers and ASP rule sets ("worlds") for generating reasoning benchmarks.
A *sampler* takes a rule set and a target number of vertices and returns one
graph of base facts chosen to make the derived facts hard to infer. A *dataset
generator* runs a sampler repeatedly and turns each graph into a set of queries.

Queries are entailed facts that do not appear in the story.

The generated queries are used to evaluate the ability of Graph Neural Networks to answer them and to investigate which kinds of reasoning query give GNNs difficulty.

---

## Provenance

The handcrafted inputs are the prompts, and within them:

1. Two Python functions — `compute_entailed_facts` and `run_clingo` in
   `clingo_dataset_generator.py` — supplied as a clean reference for query
   completeness and correctness. They are identical to the ones used for query
   generation in the Auto world rules project.
2. A precise description of the Gelfond-Lifschitz reduct method for handling
   negation as failure correctly.
3. The [NoRa rule set](https://arxiv.org/abs/2510.23532).

The samplers were improved iteratively across successive prompts. Sampling
strategies were proposed by the model, with one exception: the motif method was
suggested in a single sentence early in the conversation as a hint. The model
also designed the difficulty and diversity metrics on its own initiative, and
attempted to derive proofs when asked to categorise queries by reasoning type.

The three NoRa-specific samplers were produced in a separate conversation. The
*template* sampler and the NoRa rules were given as context, and the model was
asked to produce new samplers different from that one and from each other.

Refinement was largely error-driven: run the scripts against a rule set, paste
the failure back into the conversation, and ask for both a fix and a script that
would have caught it. `chat-history/SAMPLER_CHANGELOG.md` records the thirteen
resulting fixes.

---

## Requirements to test the samplers

```bash
pip install clingo
```

`clingo_dataset_generator.py` and `validate_dataset.py` both require it.

---

## Layout

```
Claude_Samplers_and_worlds/
├── samplers/                       8 samplers, one graph per invocation
│   ├── general_atlas_sampler.py
│   ├── general_backward_sampler.py
│   ├── general_evo_sampler.py
│   ├── general_hill_climbing_sampler.py
│   ├── general_motif_sampler.py
│   ├── nora_backward_sampler.py
│   ├── nora_greedy_sampler.py
│   └── nora_template_sampler.py
├── worlds/
│   ├── ironcoast.lp
│   └── worlds-used-for-sampler-robustness-generated-by-various-models/
│       ├── claude-opus-4.6-spynet_rules.lp
│       ├── claude-opus4.6-medieval-kingdom-rules.lp
│       ├── claude-0-se4.lp, claude-1-se4.lp
│       ├── chatgpt-0-se4.lp, chatgpt-1-se4.lp
│       ├── geminipro-0-se4.lp, geminipro-1-se4.lp, geminipro-3-se4.lp
│       ├── deepseekv32speciale-0-se4.lp
│       └── prompt-se4.txt
└── chat-history/
    ├── prompts.md
    ├── conversation_export__worlds_and_samplers_generation.md
    ├── SAMPLER_CHANGELOG.md
    └── generated_sampler_test_scripts/
        ├── clingo_dataset_generator.py
        ├── validate_dataset.py
        └── test_pipeline.py
```

---

## Worlds

Ironcoast is used as a benchmark world. The
remaining worlds exist to test sampler robustness.


| Rule set | Rules | Constraints | NAF | Choice | Prompt |
|---|---:|---:|---:|---:|---|
| **NoRa** | — | — | no | no | manually created and refined |
| **Ironcoast** | 85 | 16 | no | no | harder than NoRa and different, without disjunction or negation |
| **SpyNet** | 238 | 56 | 52 | no | harder than NoRa and different |
| **Medieval Kingdom** | 60 | 6 | 10 | 2 | create a challenging set |
| claude-0-se4 | 72 | 10 | 5 | 11 | create a challenging set |
| claude-1-se4 | 58 | 8 | 10 | 19 | " |
| chatgpt-0-se4 | 49 | 7 | 4 | 1 | " |
| chatgpt-1-se4 | 43 | 13 | 12 | 2 | " |
| geminipro-0-se4 | 63 | 10 | 0 | 7 | " |
| geminipro-1-se4 | 46 | 8 | 0 | 6 | " |
| geminipro-3-se4 | 50 | 10 | 0 | 3 | " |
| deepseekv32speciale-0-se4 | 42 | 15 | 5 | 3 | " |

The `-se4` sets were produced by ChatGPT, Gemini Pro 3.1, Claude Sonnet 4.6 and
DeepSeek V3.2 Speciale from the prompt in `prompt-se4.txt`. They appear easier
than the Opus 4.6 sets, particularly the ones written after NoRa was included in
the prompt as an example.

---

## Samplers

Each sampler outputs a single story — a graph of base facts — as an `.lp` file.
All take a target vertex count and a rule set; the remaining flags depend on the
algorithm.

| Sampler | Strategy | CLI |
|---|---|---|
| `general_hill_climbing` | SCC-aware incremental growth, then hill climbing | `rules.lp N --seed S --iterations 80` |
| `general_evo` | Population-based evolutionary search | `rules.lp N --seed S --population 30 --generations 3` |
| `general_motif` | Stitches rule-body motifs together | `N --rules rules.lp --seed S --population 30` |
| `general_backward` | SCC-aware backward skeleton construction | `rules.lp N --seed S --target-proofs 15` |
| `general_atlas` | Hybrid: backward targeting, joins, chains, batched constraint checking, hill climbing | `rules.lp N --seed S --candidates 15 --refine 20` |
| `nora_template` | Family-tree templates | `N --rules rules.lp --seed S --population 30` |
| `nora_backward` | Recipe-based backward composition | `N --rules rules.lp --seed S` |
| `nora_greedy` | Greedy beam-search growth | `N --rules rules.lp --seed S --restarts R` |

Atlas was produced last, from a prompt asking the model to study the other four
general samplers and design a new one — combining their ideas or trying new
ones — with the knowledge that the downstream evaluator is a GNN.

Note the inconsistent argument order: the general samplers take the rules file
positionally, the NoRa samplers and `general_motif` take `--rules`. The dataset
generators paper over this via a `SAMPLER_CMDS` table.

Most samplers also accept `--verbose` and `--viz`.

---

## Generating a dataset

`clingo_dataset_generator.py` derives queries purely with clingo, which
guarantees the query set is both correct and complete:

1. Combine rules and base facts into one ASP program
2. Enumerate all answer sets
3. Intersect them to obtain the cautious consequences
4. Subtract the base facts — what remains are the queries

Every query therefore holds in *every* answer set and is not stated in the base
graph.

```bash
python clingo_dataset_generator.py \
    --sampler samplers/general_evo_sampler.py \
    --rules worlds/ironcoast.lp \
    --vertices 7 \
    --num-graphs 2 \
    --output ironcoast_evo.csv \
    --vertex-mode soft
```

Samplers do not always hit the requested vertex count exactly — asking for 5 may
yield 6 on NoRa, though later versions improved this. `--vertex-mode` decides
what happens then, and `--vertices` accepts a range:

```bash
# discard (default): reject graphs outside the requested size
python clingo_dataset_generator.py -s sampler.py -r rules.lp -n 7   -g 5 --vertex-mode discard
python clingo_dataset_generator.py -s sampler.py -r rules.lp -n 6-8 -g 5 --vertex-mode discard

# soft: accept whatever comes back; 6 is passed to the sampler as a target
python clingo_dataset_generator.py -s sampler.py -r rules.lp -n 6   -g 5 --vertex-mode soft
```

Add `--max-edges N` to discard graphs above an edge budget, and `--verbose` for
per-graph summaries. Two further modes bypass the sampler: `--program` for a
self-contained `.lp`, `--facts` for a rules file plus a separate fact file.

---

## Validating a dataset

`validate_dataset.py` re-checks every query with clingo and reports any that
violate the rules. With `--output` it writes a filtered CSV containing only
validated rows.

```bash
# default filters: 5-8 vertices, <= 25 edges
python validate_dataset.py -r rules.lp -d data.csv

# custom filters, writing a clean copy
python validate_dataset.py -r rules.lp -d data.csv \
    --min-num-vertices 5 --max-num-vertices 6 --max-num-edges 15 \
    --output filtered.csv

# no filtering, validate everything
python validate_dataset.py -r rules.lp -d data.csv --no-filter
```

`test_pipeline.py` runs every sampler against every rule set and validates the
result, to confirm the combinations still work after a change:

```bash
python test_pipeline.py --generator clingo_dataset_generator.py \
                        --sampler-dir samplers/ --rules-dir worlds/
```



---

## chat-history

- **`prompts.md`** — the 53 prompts that produced the files in this repository, with bare
  "continue" turns removed.
- **`conversation_export__worlds_and_samplers_generation.md`** — the full
  conversation, prompts and replies.
- **`SAMPLER_CHANGELOG.md`** — the thirteen fixes made across the development
  cycle, each with the failure that triggered it. Worth reading before modifying
  a sampler: several fixes are non-obvious, in particular self-referential
  predicate handling for SpyNet and predicate arity handling for NoRa.
- **`generated_sampler_test_scripts/`** — the tooling described above.
