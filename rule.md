# AI IMPLEMENTATION RULES — UNIVERSAL HYBRID KNOWLEDGE GRAPH PLATFORM

## 1. Core Architecture & General Application Purpose

The Hybrid Knowledge Graph platform is architected as a **universal, domain-neutral graph engine** (`core/`) surrounded by **modular, pluggable add-on domains** (`plugins/`, `sdk/`, `policies/`).

Core is designed to serve as a standalone, embeddable graph dependency for **any general application purpose** (healthcare, clinical, finance, legal, cybersecurity, enterprise intelligence, science, e-commerce, materials physics, etc.).

### Architecture Boundaries

```
core/           = Universal domain-neutral mechanics (zero domain coupling)
sdk/            = Extension contracts, plugin interfaces, and domain config schemas
plugins/        = Add-on domain semantics (biomedical, finance, legal, cyber, etc.)
contracts/      = Machine-readable API contracts and shared schemas
policies/       = Executable, versioned policy configuration (thresholds, matching, conflicts)
infrastructure/ = Pluggable technology implementations (RDF, Neo4j, API, vector, search)
```

---

## 2. Universal Pluggability: Everything is Configurable

All domain-specific and application-specific semantics are modular add-ons and must remain completely changeable without modifying `core/`:

1. **Entity & Concept Types**: Declared via domain plugins and `DomainFusionConfig` schemas.
2. **Identifier & URI Schemes**: Custom URN/URI schemes (DOIs, patents, tax IDs, internal URLs) plug in declaratively.
3. **Ontology & Meaning Mappings**: Concept equivalence, subsumption, and disjointness rules are externalized in domain configs.
4. **Matching & Fusion Strategies**: Weights for exact IDs, label similarity, semantic embeddings, and graph topology are per-domain configurations.
5. **Conflict Resolution & Precedence**: Opposing predicate definitions and source authority hierarchies are pluggable policies.
6. **Projections**: Read projections (Neo4j, vector databases, Elasticsearch, Parquet) are disposable, pluggable consumers rebuildable from RDF authority.

---

## 3. Strict Boundary & Isolation Rules

The coding AI must strictly enforce the following isolation rules at all times:

1. **Zero Domain Leakage into Core**:
   - `core/` must **never** import, reference, or hardcode domain-specific concepts, ontologies, entity names, or identifiers (biomedical, financial, legal, or other).
   - `core/` must **never** import from `plugins/`.
2. **Zero Technology Locking in Core**:
   - `core/` must not import specific database drivers (e.g. Neo4j, Elasticsearch, Qdrant) or specific LLM SDKs (OpenAI, Anthropic, LangChain, Transformers).
   - Core interacts with storage and projection layers solely via abstract interfaces defined in `sdk/`.
3. **Biomedical & Domain Semantics Belong in Plugins**:
   - Specific ontologies (HGNC, UniProt, ChEMBL, MONDO, FIBO, etc.) must enter strictly through `plugins/<domain_name>/`.

---

## 4. Fundamental Implementation Invariants

Every modification, extension, and new feature must honor these invariants:

1. **Assertions are Immutable**:
   - Never update or mutate an `Assertion` after creation (`frozen = True`).
2. **State Evolutions are Append-Only**:
   - State transitions (promotion, review, deprecation, rejection) append `AssertionStateEvent` records.
   - Never delete or overwrite historical state events.
3. **RDF is Authoritative, Projections are Derived**:
   - RDF authority is the single cryptographic source of truth.
   - Neo4j, search indices, and vector stores are downstream projections and must remain 100% rebuildable from authoritative event logs.
4. **Strict Provenance Lineage**:
   - Every promoted assertion must be traceable to its Agent, Activity, Source Release, and Artifact.
   - Every derived assertion must declare its `input_assertion_refs`, `derivation_method`, and `activity_id`.
5. **Deterministic Fail-Safe Over Statistical AI**:
   - LLMs and embedding models are optional acceleration utilities.
   - AI outputs can never bypass schema validators or policies.
   - In the absence or failure of an AI component, the engine must deterministically fall back to strict rules or trigger an explicit human review queue (`ABSTAIN`).
6. **Selective, Calibrated Fusion**:
   - Never perform destructive blind merges.
   - Use the 3-tier confidence decider: Auto-Merge ($\ge T_{\text{high}}$), Coexist/Keep-Separate ($< T_{\text{review}}$ or disjoint violation), and Review/Abstain ($[T_{\text{review}}, T_{\text{high}})$).

---

## 5. Development & Contribution Discipline

Before modifying or adding code:

1. **Check Existing Interfaces**: Reuse established contracts in `sdk/` and models in `core/`.
2. **Preserve Backward Compatibility**: Ensure existing public APIs, domain presets, and test suites continue to pass.
3. **Add Tests Alongside Implementation**: Every new capability or domain rule must include unit tests with positive and negative fixtures.
4. **No Speculative Abstractions**: Implement only what is required for the concrete task. Avoid speculative future-phase bloat.
5. **Reproducibility**: Ensure all outputs, identifiers, and serialization digests are deterministic.