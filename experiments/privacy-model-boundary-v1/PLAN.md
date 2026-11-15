<!-- Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md -->

# Privacy, runtime model authority and boundary diagnostics (0.2.6)

Plan frozen `2026-11-15T00:17:40Z` before candidate implementation or test execution records.

## Scope and hypotheses

1. **Record retention and `data_use` boundaries (`stepkit.retention`, `stepkit.omninode`)**:
   - Sanitize `NodeRecord` payloads before constructing `l0_summary` so echoed, long-truncated, and nested task-text answers do not leak through summary previews when `records.task_text` is denied.
   - Fail closed on absent, empty, non-string, or unrecognized task context and on non-mapping `effective_policy` across both `execution_report`/`submit` and `value_of`/`write`, while preserving functional `submit` delivery outputs and explicit `records.task_text=True` controls.
   - Enforce monotonic `records.data_use` authority (`open` may narrow to `benchmark: no training`; `benchmark: no training` may never widen to `open` via parameters, evidence, exploration, child derivation, or writer `data_use` overrides).
2. **Ancestor and runtime part/connector model allowlists (`stepkit.omninode`)**:
   - Enforce monotonic allowlist and permission narrowing across the full ancestor chain in `derive`, `spawn`, and `run`.
   - Validate all effective part model declarations and resolved settings (`Part.model`, `Part.required_model`, `Part.info`, `part.model`, `part.<part>.model`, and retrieved evidence) plus probe-backed parts under empty model allowlists (`[]` or exhausted `budget.model_calls`) before invoking any probe or part callable.
3. **Body-only boundary provenance and fail-closed strict-output diagnostics (`teleion_fabric.boundary_provenance`, `teleion_fabric.prose_tools`, `teleion_fabric.opencode_omninode`)**:
   - Record body-only byte digests (and optional `{digest, size_bytes}` content-addressed store references) without headers, paths, or credentials, failing closed on sink errors or truncated/oversized payloads.
   - Keep `strict_json` whole-output checking fail-closed by default while `diagnose_json_boundary` attributes `<system-reminder>` / instruction-envelope prefixes, markdown code fences, surrounding prose, ambiguous embedded candidates, and malformed JSON without authorizing execution or semantic task acceptance.

## Scoring and limits

- Verify all inherited package tests, composition-recovery tests, new positive/negative unit tests, AST/naming conformance gates, and all six focused portable CPU component notebooks against a freshly built and installed `0.2.6` wheel outside the source checkout.
- Scope is deterministic local CPU execution with in-memory ports and offline fixtures; no live model inference, remote service mutation, sandboxing of trusted Python callables, or operational observation time is claimed. Independent review is required before publication.
