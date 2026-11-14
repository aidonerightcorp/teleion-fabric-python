<!-- Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md -->

# Agent entry

Read CHARTER.md, CONSTITUTION.md, CONTEXT.md, docs/ARCHITECTURE.md and the complete packaged data/capabilities.json inventory. Use teleion_fabric.context.packet for complete public family/relationship context; retrieve relevant implementation contracts from data/engines.json. Check MIGRATION.json before assuming an engine is installed. External provider integration requires its owning instructions.

Write an experiment plan before records. Keep failures. Test changes through an installed wheel outside the source checkout. Never call a model or deploy merely by importing a package or running offline tests. Keep credentials out of source and logs. Preserve raw outcomes privately, distinguish shape validation from acceptance, and use a task-specific checker.

After charter changes run tools/sync_context.py --write then --check. The manifest binds every distributed source/settings/document file to the charter. Do not insert headers into frozen results or rewrite third-party providers. This is an enforceable repository check, not a way to force arbitrary agents to understand text.
