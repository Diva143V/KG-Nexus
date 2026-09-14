# Universal Implementation Philosophy — Hybrid Knowledge Graph Platform

The Hybrid Knowledge Graph Platform is built on a fundamental architectural separation: **Core provides universal, domain-neutral mechanics**, while **all application domains, ontologies, and policies exist strictly as pluggable add-on domains**. 

Core is engineered to serve as a lightweight, robust, and embeddable knowledge graph dependency for **any general application purpose**—including life sciences, clinical healthcare, financial systems, legal analysis, cybersecurity, supply chain intelligence, materials science, and enterprise knowledge management.

---

## 1. Architectural Separation: Core vs. Add-On Domains

```
┌────────────────────────────────────────────────────────────────────────┐
│                        ADD-ON DOMAINS (PLUGINS)                        │
│  Biomedical • Clinical • Financial • Legal • Cyber • Enterprise • ...  │
│  (Custom Entities, Ontologies, Identifiers, Domain Validators, Rules)  │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Extends via Contracts
┌───────────────────────────────────▼────────────────────────────────────┐
│                        EXTENSION SDK & CONTRACTS                       │
│     Plugin Interfaces • Domain Configs • Schemas • Policy Engines      │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Implements
┌───────────────────────────────────▼────────────────────────────────────┐
│                        HYBRID KG CORE (UNIVERSAL)                      │
│   Immutable Assertions • Append-Only State Events • Multi-Source Lineage│
│   Deterministic Fusion • Cryptographic Digests • Authority Storage     │
└────────────────────────────────────────────────────────────────────────┘
```

1. **Core = Universal Mechanics**: `core/` contains pure graph logic, immutable assertions, state machines, algebraic reconciliation, confidence deciders, provenance tracking, and storage authority contracts.
2. **Add-Ons = Domain Semantics**: All entity classes, domain ontologies, predicate hierarchies, external identifier formats, and domain-specific validation rules enter exclusively through the `sdk/` and `plugins/` interfaces.
3. **Zero Domain Coupling in Core**: Core must **never** import, reference, or hardcode domain-specific concepts (biomedical, financial, legal, or other). Core treats all knowledge as typed entities, relational triples, and typed literals.
4. **Universal Dependency Purpose**: Any external software application or domain workflow can import and embed `core` as a standalone graph engine dependency without taking on unwanted domain-specific baggage.

---

## 2. Pluggability & Changeability: Everything is Configurable

To ensure the platform adapts to any enterprise or research use case, all domain-specific behavior is fully externalized and dynamically configurable:

- **Entity & Concept Typing**: Domain packs declare their own entity kinds, namespaces, display rules, and color palettes without touching Core.
- **Identifier & URI Schemes**: Custom identifier patterns, authority registries, and URI resolution schemes (e.g., DOIs, patent numbers, tax IDs, internal URLs) plug in via declarative domain configurations.
- **Ontology & Vocabulary Mappings**: Directional equivalence (`EQUIVALENT`), subsumption (`DIRECTED_A_TO_B`), and disjointness invariants (`DISJOINT_CLASSES`) are defined via `DomainFusionConfig` presets or runtime JSON specifications.
- **Selective Fusion & Match Strategy**: Matching weights (exact ID, label similarity, semantic vector embeddings, structural topology) and confidence thresholds are fully tuneable per application domain.
- **Conflict Resolution & Precedence**: Rules for opposing predicates (e.g., `treats` vs `contraindicates`, `owns` vs `divested`) and source authorities are pluggable policies.
- **Projection Backends**: Graph projections (Neo4j property graphs, vector search indices, full-text Elasticsearch/OpenSearch, columnar Parquet analytics) are pluggable consumers that can be swapped or customized at will.

---

## 3. The Non-Negotiable Core Invariants (Fundamental Laws)

Throughout all current and future implementations, every component and AI contributor must uphold these core laws:

### I. Immutable Knowledge
- No `Assertion` may ever be modified, edited, or overwritten in place after creation (`frozen = True`).
- Knowledge in the graph is strictly write-once.

### II. Append-Only State Evolutions
- Lifecycle transitions (promotion, candidate review, soft-deprecation, policy rejection) are recorded as append-only `AssertionStateEvent` records.
- Graph state at any point in history is 100% deterministically reconstructible via event replay.

### III. Authoritative Ground Truth & Rebuildable Projections
- The canonical graph store (RDF Authority) is the primary, cryptographic source of truth.
- Auxiliary stores (e.g., Neo4j, vector databases, search indices) are **derived projections**. They are disposable and must remain 100% rebuildable from authoritative release snapshots.
- Projections must never be treated as the source of truth.

### IV. Universal, Uncompromising Provenance
- Every promoted assertion must have cryptographically auditable lineage linking to:
  $$\text{Assertion} \longrightarrow \text{Activity} \longrightarrow \text{Agent} \longrightarrow \text{Source Release} \longrightarrow \text{Input Resources}$$
- Every derived assertion must explicitly declare its `derivation_method`, `input_assertion_refs`, and `activity_id`.

### V. Deterministic Behavior Over Clever AI
- AI models, LLMs, and statistical neural embeddings are **optional acceleration utilities**.
- Model outputs can **never** bypass structural validators, schema contracts, or security policies.
- When an AI component is absent, uncalibrated, or encounters an error, the engine must safely and deterministically fall back to strict rules or trigger an explicit human review queue (`ABSTAIN`).

### VI. Selective, Safe Graph Fusion
- Graph fusion must never perform destructive or blind merges.
- The 3-tier confidence decider strictly segregates:
  1. **Automatic Merge** ($\ge T_{\text{high}}$) $\rightarrow$ canonical entity creation and edge redirection.
  2. **Coexist / Keep-Separate** ($< T_{\text{review}}$ or disjoint class violation) $\rightarrow$ distinct nodes preserved side-by-side with zero data loss.
  3. **Abstain / Flag for Review** ($[T_{\text{review}}, T_{\text{high}})$) $\rightarrow$ non-blocking triage queue for domain experts.

### VII. Reproducible Platform Releases
- Every platform release must be fully reproducible.
- Each release is governed by an immutable `ExecutionManifest` containing cryptographic hashes (SHA-256) of input datasets, plugin versions, policy files, and runtime environment specifications.

### VIII. Contract Verification & Backward Compatibility
- Every add-on domain pack and plugin must pass the standardized Core Contract test suite (`sdk/registries.py`).
- Existing public interfaces and core contracts must maintain strict backward compatibility.

### IX. Parsimony in Implementation
- Do not implement future phases or speculative features early.
- Do not introduce unnecessary abstractions without a concrete, documented phase requirement.