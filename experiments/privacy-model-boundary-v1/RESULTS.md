<!-- Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md -->

# Privacy, runtime model authority and boundary diagnostics results (0.2.6)

Candidate `0.2.6` integrates three bounded component capabilities on top of `0.2.5`:

1. **Fail-closed record retention and `data_use` authority (`stepkit.retention`, `stepkit.omninode`)**:
   - `NodeRecordSink` sanitizes stored records before building `l0_summary`, preventing raw, truncated or nested task-text leakage through summary previews when `records.task_text=False`.
   - Missing, empty, non-string or unrecognized task context and malformed `effective_policy` fail closed across both `execution_report`/`submit` and `value_of`/`write`, while functional `submit` return values and explicit `records.task_text=True` controls remain preserved.
   - `records.data_use` enforces monotonic narrowing (`open` -> `benchmark: no training`) across own-policy resolution, child derivation and writer overrides (`5` `test_record_privacy_redaction` methods covering positive, negative and boundary subtests).
2. **Ancestor-chain and runtime part/connector model allowlists (`stepkit.omninode`)**:
   - Child derivation, spawn and execution enforce monotonic narrowing of `resources.models` and `permissions.models` across all active ancestors.
   - Pre-invocation runtime checks validate `Part.model`, `Part.required_model`, `Part.info`, `part.model`, `part.<part>.model`, retrieved evidence, empty `[]` model allowlists on probe-backed parts, malformed model metadata, and `budget.model_calls` exhaustion before any probe or callable executes (`6` `test_model_allowlist_runtime` methods).
3. **Body-only boundary provenance and fail-closed strict-output diagnostics (`teleion_fabric.boundary_provenance`, `teleion_fabric.prose_tools`, `teleion_fabric.opencode_omninode`)**:
   - `BoundaryProvenance` computes body-only SHA-256 digests under grid-governed byte limits with optional `{digest, size_bytes}` content-addressed sink verification and scrubbed fail-closed sink errors.
   - `strict_json` remains fail-closed on contaminated outputs while `diagnose_json_boundary` distinguishes clean JSON, `<system-reminder>` / instruction-envelope prefixes, markdown code fences, prose-plus-fence wrappers, literal tags inside valid JSON strings, ambiguous candidates, and malformed JSON (`5` `test_boundary_provenance` methods).
4. **Declarative grids and conformance gates (`test_v026_conformance_gates`)**:
   - `retention` and `boundary` grids resolve through `teleion_fabric.settings`, mechanical AST/naming conformance checks pass, and a repository-wide public-hygiene regression check scans all tracked files (`4` `test_v026_conformance_gates` methods).

## Validation and limits

- Installed-wheel CPU gates: `114` package test methods (`94` inherited + `20` new), `10` composition/restart test methods, `examples/compose_prose.py`, and `tools/sync_context.py --check` pass locally outside the source checkout.
- Scope limits: local CPU execution over deterministic fixtures and in-memory ports only; no live model/provider calls, no remote database or queue service qualification, no sandboxing of trusted Python callables, no concurrent budget reservation, and no claim that operational month observation has started. Maker validation only; independent checker review is required before publication.
