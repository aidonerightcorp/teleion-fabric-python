<!-- Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md -->

# Composition and restart contract tests

2026-11-14T16:14:13.728672+00:00 — written before test execution.

Test the installed public 0.2.0 package, using existing compiler, profiler, prose, checked store and trace APIs. No provider, GPU, Kaggle or paid calls. CPU nice10, two numerical threads, one test process. Private run folders are append-only. Parent authors these new checks; independent reproduction of the previous 32-module campaign runs separately.

Frozen scenarios: 200 randomized single-input DAGs (two recorded seeds, 100 cases each; sizes 1–32), independent arithmetic reference outputs, shuffled serialization invariance; sibling mutation isolation; stop after failed producer; reject cycles, missing engines/versions/sources, incompatible semantic edges and declared effects before execution; nested validator refusal before consumer. Persist three authored task/plan objects then load and execute a retrieved plan in a fresh process; unchecked exact matches must not outrank checked reuse. Test cache invalidation on replace and trace restart with unsuccessful attempt costs retained. Exercise contact-cleaning string semantics including leading-zero identifiers using explicit acceptance expectations. Exercise profiling and prose as parallel registered engines on multilingual/markup input. No model selection or live queue claims.

Configuration and stop policy are in settings.json. Exact assertions determine pass/fail, not elapsed time. Preserve stdout/stderr and machine results on failures. No tuning on these cases; changing fixtures after execution requires dated amendment. Random cases are structural regressions, not a held-out optimization comparison. Store save/load is ordinary file persistence: it does not claim atomic commit, crash durability, concurrent writers or durable queue recovery. Package version/origin and source content hashes are recorded, not inferred from a version label.

2026-11-14T16:16:57.151514+00:00 — Independent reviewer reproduced all initial results and identified missing assertions for the composed prose output. Add literal heading/fence/paragraph expectations and a fenced input block, then rerun; preserve first results. Correct dashboard blocked-row execution wording. Trace test is a same-process round-trip; graph fan-out executes sequentially.
