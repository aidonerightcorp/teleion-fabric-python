<!-- Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md -->

# Public GitHub installation qualification

These notebooks contain only the test runner. They fetch implementation, tests and examples anonymously from the public GitHub release. Tested version:0.2.0, commit52095288673f4902fe794b4a448caf21bf75aee6.

The matrix tests pip from a Git tag, the release wheel with an expectedSHA256, and a commit-addressed source archive. Each route uses a separate venv with platform dependencies shared. The additional clean notebook resolves dependencies into a venv without system-site-packages. Both use host pip --python to target the venv, avoiding Kaggle ensurepip bootstrap failure.

Run notebooks on Kaggle CPU with internet enabled; no GPU or provider/model credentials are needed. Run each in a fresh working directory. Scripts default to /kaggle/working; TELEION_INSTALL_TEST_ROOT can select a fresh local root. Full regression tests and examples come from the pinned public checkout; Python -I and import-origin checks prevent checkout source from substituting for the installed primary package.

Recompute evidence locally with `python verify_results.py matrix-results.json` and, once the rate-limited clean artifact is retrieved, `python verify_clean.py clean-results.json`. The verifiers additionally require exactly21passing unittest methods, successful setup, expected interpreters and route-specific provenance. These checks are evidence consistency checks, not tamper-resistant supply-chain attestations.

The first failed environment-bootstrap attempt is preserved in attempt1-results.json. RESULTS.json summarizes the final observations. Shared-dependency routes do not establish independent dependency resolution, optional semantic/fitting extras or compatibility across all platforms. Primary package provenance is explicitly checked; per-file provenance of every secondary imported module is not independently attested. No model-performance or full-fabric claim follows from installation success.

Current outcome: all three matrix routes passed21tests and both examples each. The isolated-dependency notebook reached COMPLETE; detailed artifact retrieval hit HTTP429, so its dependency versions and full result checks remain pending. No retry bypass was attempted.
