<!-- Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md -->

# Current context

The public architecture catalog contains 73 family cards and 309 relationships; these summarize many concrete parts and are not the total component count. Private source-backed cards and prompt histories stay in the owning workspace. Public family IDs are stable aliases within this release.

Existing component evidence includes bounded durable-cycle and recorded-configuration Kaggle experiments. A profiler/persistence/retrieval notebook completed at https://www.kaggle.com/code/taylorsamarel/teleion-task-profiler-edges-v1 . It does not test every family or prove prospective configuration gains. The current OpenCode package is checked with offline subprocess fixtures and saved responses; a live qualification of this wrapper is still needed.

No operational month is claimed to have started. Every family needs explicit contract tests, provider-specific failures, and integration checks. The package tests cover a limited executable subset; MIGRATION.json preserves unbundled dependencies rather than hiding them.
