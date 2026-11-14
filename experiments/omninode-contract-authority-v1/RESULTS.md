<!-- Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md -->

# Adaptive settings within declared authority

Installed 0.2.1 failed four of five new execution tests: parameters, stored evidence and exploration could widen declared live permission or model access. The permitted arrangement-selection control passed. No real model/provider call occurred.

Candidate 0.2.2 checks each resolved proposal against declared permissions, resource lists and numerical budget limits before returning it. Valid narrowing remains adaptive. A proposal that widens authority raises ContractError and remains visible in the resolver choices. This intentionally refuses invalid proposals instead of silently choosing the original declaration. Other parameters, including admitted arrangements and fallbacks, retain their existing selection behavior.

Eight new methods, 35 total package methods and 10 composition methods pass against the installed candidate. A separate checker passed 20 methods: the eight new methods, six inherited-authority methods and six additional reviewer methods. Those six additional methods are included in the public regression suite. Source/test/wheel identity and environment limits are in result.json.

These checks do not establish prepaid or concurrent budget reservations, complete storage/cartridge access enforcement, sandboxing of trusted Python, every contract field's authority policy, real-model adaptation or operational optimization gains. Child shared-budget policy remains separate from aggregate parent accounting.

Resolver choice entries retain proposed values even when refused. Consumers must retain the refusal outcome; a choice entry alone is not an authority grant.
