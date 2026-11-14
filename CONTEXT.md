<!-- Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md -->

# Current context

The public architecture catalog contains 73 family cards and 309 relationships; these summarize many concrete parts and are not the total component count. Private source-backed cards and prompt histories stay in the owning workspace. Public family IDs are stable aliases within this release.

Existing component evidence includes bounded durable-cycle and recorded-configuration Kaggle experiments. A profiler/persistence/retrieval notebook completed at https://www.kaggle.com/code/taylorsamarel/teleion-task-profiler-edges-v1 . It does not test every family or prove prospective configuration gains. The current OpenCode package is checked with offline subprocess fixtures and saved responses; a live qualification of this wrapper is still needed.

No operational month is claimed to have started. Every family needs explicit contract tests, provider-specific failures, and integration checks. The package tests cover a limited executable subset; MIGRATION.json preserves unbundled dependencies rather than hiding them.

Candidate 0.2.1 repairs inherited OmniNode resource limits while preserving permitted child configuration and fallback. Six new authority tests, 27 total package tests and 10 composition tests pass locally against the installed wheel; a separate checker reproduced the six authority tests. See experiments/omninode-authority-v1. Existing 0.2.0 evidence remains tied to that release.

Version 0.2.2 adds permission/resource/budget proposal validation while preserving adaptive narrowing. Installed-wheel checks passed 35 package methods and 10 composition methods before adding six independently checked reviewer regressions. Independent authority review passed 20 methods; see experiments/omninode-contract-authority-v1 for exact scope and remaining gaps.

Candidate0.2.3 protects own-task forms, required output checks and task-text permission while preserving explicit child contracts and adaptive added checks. A frozen effective_policy is recorded separately from the declaration. Installed-wheel validation:53package methods,10composition/restart methods, example and context check pass locally; independent review pending. Private writer/data-use override and redaction remain separate.

The first0.2.3candidate was rejected by independent composed-answer/list-form cases. The amended candidate adds central final-answer validation and existing list-form narrowings:58package methods,10composition/restart methods and all7copied reviewer cases now pass locally. Prior failed source/wheel/results remain retained; independent recheck pending.

Version0.2.4 adds mandatory declared-budget stops alongside flexible strategy stops. Independent review reproduced10diagnostics and12test methods; full installed package63methods and composition10methods pass before the release-version consistency test. See experiments/omninode-budget-stops-v1. This does not add per-call reservations or intra-callback interruption.

Version0.2.5 adds independently reviewed sequential ancestor accounting:8baseline checks and27reviewmethods pass on reviewedsourcececa1554. Retains exactfallback, failedcandidatehistory and explicitlimits; see experiments/ancestor-accounting-v1. Release gates below are run against a freshly installed wheel.
