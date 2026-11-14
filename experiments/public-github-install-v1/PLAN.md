<!-- Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md -->

# Public GitHub to Kaggle installation

2026-11-13T22:49:35.076358-05:00 — before first execution record.

Test three anonymous public download/install routes for teleion-fabric0.2.0: pip VCS tag pinned/checked against commit52095288673f4902fe794b4a448caf21bf75aee6; GitHub release wheel with expectedSHA256; GitHub commit source archive. No source bundle or local private files included in notebook. Obtain tests/examples from the verified public checkout. Each route gets a separate virtual environment with Kaggle system dependencies available; explicitly install the package into that environment and assert its import origin and version. Record dependency versions; this is package isolation, not fully isolated dependency resolution.

Run all21unittest methods and both examples, test CLI settings and packaged resources, verify source-context manifest. Score installation, provenance and behavior separately. Stop a failing route, continue independent routes, no fallback or hidden retry. Report duration/status/error class and limited public installer output. Internet-enabled CPU notebook,2threads, no GPU/model/provider calls. Preserve raw results and compare against the earlier embedded-source Kaggle runs. Final pass requires all three independent routes plus exact commit/wheel identities and behavioral checks. Budget: one notebook, at most15minutes; per-command timeouts cap installs/tests.

2026-11-13T22:52:55.276178-05:00 — attempt1 public clone/pinned commit/source-manifest pass; all3routes fail while venv bootstraps ensurepip, before installs. Preserve full outputs. Attempt2 uses venv --without-pip and the host pip --python target mechanism; no global installation or criteria relaxation. Record host pip version. All routes still require package origin inside their own venv, exact source identities and21passing tests.

2026-11-13T22:54:49.609189-05:00 — attempt2 all3routes pass,21tests each with system NumPy2.1.3/SciPy1.16.3. Add a separate fourth qualification: public Git tag into a venv without system-site-packages, resolving declared dependencies and build requirements normally. Verify package, NumPy and SciPy imports all originate inside the venv. Same21tests/examples/provenance gates. One additional CPU notebook, no GPU/model calls,15minute cap. Do not rerun the already-passing three-route matrix.
