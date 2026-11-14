<!-- Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md -->

# OmniNode inherited authority repair

The installed0.2.0 baseline failed12 assertions across6 test methods: child model/store/cartridge allowlists could widen at spawn, and changed child configuration could bypass ancestor model/live limits. These are local authored counterexamples; no actual provider call occurred.

Candidate0.2.1 adds monotonic resource allowlists at spawn and checks actual attempted stages against each ancestor immediately before execution. Permitted narrowing, unrestricted-parent selection, child spawning and fallback after a failed step remain exercised. Configuration remains flexible inside the parent authority boundary.

Installed candidate results:6/6 new methods pass,27/27 total package tests pass, and10/10 composition regressions pass (including200 seeded graphs). Source/fixture/wheel identity is recorded in result.json. A separate checker reproduced all six new methods against the installed candidate and found no blocking defect in the bounded patch. The checker did not separately repeat the 27-package/10-composition runs.

Limitations: trusted Python implementations are not sandboxed. This repair does not prove hard prepaid budgets, enforce all storage APIs, qualify real model selection, or establish the entire adaptive fabric. Store/cartridge inheritance is checked as a declaration; actual access enforcement belongs to their adapters. All previous0.2.0 component evidence remains tied to that release.

Runtime authority checks occur before the selected sequence. In-flight mutation by trusted callbacks remains outside this patch’s qualification.
