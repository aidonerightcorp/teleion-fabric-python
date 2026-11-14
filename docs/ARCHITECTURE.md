<!-- Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md -->

# Design through package edges

```mermaid
flowchart TD
 Input[Input and acceptance] --> Profile[Task profiler package]
 Profile --> Retrieve[Task Object and memory retrieval]
 Retrieve --> Reuse{Admitted prior solution?}
 Reuse -->|adapt or compose| Plan[Typed versioned graph]
 Reuse -->|exact admitted reuse| Queue[Durable task queue]
 Plan --> Configure[Harness / model / context / skills / tools]
 Configure --> Queue
 Queue --> Worker[OmniNode executor]
 Worker --> Engines[Pure functions / models / remote engine clients]
 Engines --> Check[Task-specific checker]
 Check --> Store[Durable objects and evidence]
 Store --> Memory[Typed memory and vector index]
 Memory --> Retrieve
 Store --> Improve[Bounded candidate experiments]
 Improve --> Profile
 Improve --> Configure
 Improve --> Plan
```

```mermaid
flowchart LR
 I[Typed input + semantic constraints] --> B[Package engine: ID + version + settings]
 B --> O[Typed output + evidence]
 P[Permissions + resources] --> B
 B --> F[Failures + effects + recovery contract]
```

The planner works with the edges. An engine may implement a pure function or call a service in another language. Package installation, execution authorization, semantic compatibility and task acceptance are separate decisions. Compose only registered entrypoints; never import an arbitrary path suggested by model prose.

The bundled `contracts.compose` deliberately handles sequential pure engines only. Durable DAG execution, retries, leases and effect reconciliation belong to existing provider engines and are tracked as external dependencies. This avoids claiming a small linear example is a replacement for the full compiler/queue.

Each module receives an entry in the package manifest; settings are package resources. Each engine entry lists its input/output semantics, effects, version and qualification scope. Keep one cohesive distribution where modules share a release; split distributions only when dependencies, ownership or deployment require it.
