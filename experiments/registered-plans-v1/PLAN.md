<!-- Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md -->

# Registered package plans

2026-11-13T22:25:37.343513-05:00 — before first new test record.

Goal: move composition from Python glue to data that names pre-registered versioned engines and typed edges. Reuse Engine/Port and reject invalid complete plans before execution. Scope: pure single-input engines with branching; no new durable queue, arbitrary imports, automatic optimization or effect replay. Freeze compiler fixtures before first run: valid branches and reordered nodes; cycles; unknown engines and versions; duplicate IDs; semantic/type mismatches; unsupported effects; bad output shape; downstream not run after failure; caller plan mutation; sibling input mutation; malformed plan keys. Exercise numeric chains across100 deterministic inputs and a contact-ID/prose example. Settings must not treat True as1 or alias caller-owned mutable data. Baseline is existing callable compose; compare output equivalence, not LLM performance. Test installed wheel outside source; no paid/model/GPU calls. Preserve failures and review findings.

2026-11-13T22:28:47.479842-05:00 — review-driven extension after first15passing tests: add optional versioned port validators for nested payload checks; test invalid nested data blocks consumers. Make malformed settings schemas fail explicitly and retain the distinction between raw design catalogs and executable selection grids. These additional cases are engineering regressions, not held-out efficacy evidence.

2026-11-13T22:33:06.345395-05:00 — independent review found dict-key equality confusion and custom nested copy hooks defeating isolation. Before rerun add a shared plain-JSON boundary: exact built-in types, string keys, finite numbers, cycle/depth rejection before copying. Add regression fixtures; preserve earlier passing runs and stale-wheel failure.
