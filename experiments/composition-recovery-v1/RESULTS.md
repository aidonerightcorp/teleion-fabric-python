<!-- Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md -->

# Composition and restart results

Measured locally on the installed 0.2.0 package: **10/10 test methods passed**, including 200 seeded DAG cases with arithmetic reference outputs and shuffled serialization checks. Each method and subcase scope is visible in `check_composition.py`; stdout and outcome metadata are retained alongside this report.

| Contract | Result | Scope |
|---|---|---|
| Registered graph execution | Passed | 200 generated single-input DAGs, sizes 1–32; two fixed seeds |
| Branch isolation | Passed | Mutation in one branch leaves sibling and caller values intact |
| Failed producer | Passed | Consumer never called; failed-node record preserved |
| Invalid graph admission | Passed | Seven malformed graph configurations rejected before execution |
| Nested input validator | Passed | Four invalid inputs blocked; valid input accepted |
| Saved-plan retrieval and execution | Passed | Fresh subprocess reloads JSONL store; unchecked exact match excluded |
| Search cache replacement | Passed | Replacing checked entry invalidates text/vector search eligibility |
| Trace serialization round-trip | Passed | Rejected attempt and its cost retained through serialization |
| Contact example | Passed | Explicit expected rows preserve leading-zero identifiers and empty fields |
| Profile/prose branches | Passed | Sequential fan-out with explicit profile and prose-output assertions |

All 42 installed source/data files matched the corresponding public source bytes. This excludes dependencies and distribution metadata; it is not a reproducible-build claim.

The contact normalizer is authored **test fixture code**, not a newly shipped production cleaning engine. Retrieval uses three authored entries and a lexical query; automatic task decomposition, general retrieval quality and model-directed composition remain unqualified. Persistence here is successful save/load, not crash durability, atomic replacement, concurrent writes or queue lease recovery. The compiler deliberately returns `task_accepted=False`; this test's explicit expected-output checker remains separate.

No model/provider/GPU calls, Kaggle jobs, model-selection gains or operational-month claims. Existing 32-module campaign statuses remain separate; these ten methods must not be added to the count of modules or architecture families.

Reproduce using an installed environment:

```sh
OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 nice -n 10 /path/to/venv/bin/python -I experiments/composition-recovery-v1/check_composition.py
```

The two fixed seeds are regression inputs, not a held-out optimization study. Independent reproduction status is recorded in REVIEW.md when available.
