<!-- Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md -->

# Packaging and execution tracker

Open `component-dashboard.html` in any browser. It works offline. Search components, filter status, and expand a row for checks and remaining scope. `TRACKING.md` is the compact table; `component-results.json` is the machine-readable snapshot.

Measured local results: **28 scoped passes, 3 packaging-only checks, 1 blocked module**, across 32 bundled modules. Another 20 external/pending modules remain visible. Architecture inventory: 73 families and 309 relationships; these are not total concrete-part counts.

`stepkit.live` remains blocked on historical toolsmith/benchmark/spec prerequisites. Actual provider execution, GPU work, whole-fabric integration, and Docker/OCI image qualification were not performed by this campaign. Earlier package-level Kaggle evidence is shown separately. Individual component Kaggle execution remains pending after API rate limiting.

One complete snapshot is required; the generator rejects missing/duplicate modules and multi-run merging. An earlier tier_ladder fixture failure remains in the private campaign log and is disclosed in the dashboard. Installed version and module origins were verified; this runner does not independently attest the installed wheel hash.

## Reproduce

With release 0.2.0 installed in an isolated virtual environment:

```sh
/path/to/venv/bin/python -I run_components.py --python /path/to/venv/bin/python --output /new/private/run-folder
python build_dashboard.py /new/private/run-folder/results.json
```

Run from this experiment directory in a checkout so the migration inventory and public family catalog resolve. Keep raw process logs private; publish only the generated sanitized projection. Each component has a 30-second limit and the campaign a 15-minute budget. Execution is sequential, CPU only, with two numerical-library threads.

A separate agent reviewed the first dashboard/runner source and identified evidence-handling improvements. Final measurements have not been independently rerun by that reviewer.
