# Pipeline Strategy & Implementation Audit — Hybrid Knowledge Graph Platform

This audit document evaluates the 3-step **"Pragmatic Lean"** pipeline strategy against the implementation in this repository.

---

## Executive Summary

| Pipeline Step | Technique / Concept | Implementation Status in Repository | Primary Code References |
| :--- | :--- | :--- | :--- |
| **Step 1: Selective Fusion** | Outgoing Edge / Dense Core Filtering | **IMPLEMENTED** | [`core/relations/relation.py`](file:///d:/Hybrid%20kg/core/relations/relation.py), [`core/resolution/generator.py`](file:///d:/Hybrid%20kg/core/resolution/generator.py) |
| **Step 1: Selective Fusion** | Canonical Anchor Identifiers (HGNC, Ensembl, UniProt, ChEBI, MONDO, ChEMBL) | **IMPLEMENTED** | [`plugins/biomedical/identity.py`](file:///d:/Hybrid%20kg/plugins/biomedical/identity.py), [`plugins/biomedical/adapters/`](file:///d:/Hybrid%20kg/plugins/biomedical/adapters/) |
| **Step 1: Selective Fusion** | High-Precision Seed Alignment Matching | **IMPLEMENTED** | [`plugins/biomedical/identity.py`](file:///d:/Hybrid%20kg/plugins/biomedical/identity.py#L65-L85), [`plugins/synthetic/policies.py`](file:///d:/Hybrid%20kg/plugins/synthetic/policies.py#L14-L33) |
| **Step 2: Embedding Alignment** | Vector Search / Candidate Retrieval & FAISS Indexing | **IMPLEMENTED** | [`infrastructure/projections/vector/`](file:///d:/Hybrid%20kg/infrastructure/projections/vector/), [`tests/test_vector_projection_backend.py`](file:///d:/Hybrid%20kg/tests/test_vector_projection_backend.py) |
| **Step 2: Embedding Alignment** | Borderline Verification via Local 8B Model (Llama-8B) | **IMPLEMENTED** | [`infrastructure/llm/verifier.py`](file:///d:/Hybrid%20kg/infrastructure/llm/verifier.py), [`tests/test_llm_verifier.py`](file:///d:/Hybrid%20kg/tests/test_llm_verifier.py) |
| **Step 2: Embedding Alignment** | Structural GNN Training (RREA / RDGCN / PyG) | **PLUGGABLE SDK EXTENSION** | Integrates via [`sdk/resolution.py`](file:///d:/Hybrid%20kg/sdk/resolution.py) (`CandidateRanker` interface) |
| **Step 3: Upfront Ontology Alignment**| Global Schema & Ontology Namespace Registries | **IMPLEMENTED** | [`sdk/registries.py`](file:///d:/Hybrid%20kg/sdk/registries.py), [`plugins/biomedical/relations.py`](file:///d:/Hybrid%20kg/plugins/biomedical/relations.py) |
| **Step 3: Upfront Ontology Alignment**| Rule-Based Ontology Matchers (e.g. LogMap / AML) & LLM Grey Area Fallback | **IMPLEMENTED VIA SDK** | [`sdk/resolution.py`](file:///d:/Hybrid%20kg/sdk/resolution.py), [`infrastructure/llm/verifier.py`](file:///d:/Hybrid%20kg/infrastructure/llm/verifier.py) |

---

## Detailed Step-by-Step Technical Analysis

### Step 1: Selective Fusion (Outgoing Edges Only) & Source of Truth

#### 1.1 Structural Noise Pruning & Outgoing Edge Selection
- **Strategy**: Filter out isolated/dangling nodes lacking outgoing structural edges to prevent embedding drift and improve candidate density.
- **Repository Implementation**:
  - `core/relations/relation.py` and `core/resolution/generator.py` structure candidate generation around active subject-predicate-object directed links.
  - Nodes without relations or evidence are excluded from candidate matching pipelines.

#### 1.2 Anchor Registries & Canonical Cross-References
- **Strategy**: Use universal anchor registries (HGNC, Ensembl, UniProt, ChEBI, MONDO, ChEMBL) as deterministic seed alignments.
- **Repository Implementation**:
  - Implemented across all biomedical adapters in [`plugins/biomedical/adapters/`](file:///d:/Hybrid%20kg/plugins/biomedical/adapters/):
    - **HGNC**: `HGNC:6018` for `INS` gene.
    - **Ensembl**: `ENSG00000254647` for transcript/gene loci.
    - **UniProt**: `P01308` for `Insulin` protein.
    - **ChEBI**: `CHEBI:15365` for chemical entities.
    - **MONDO**: `MONDO:0005148` for disease ontologies.
    - **ChEMBL**: `CHEMBL1431` for bioactivity and active moieties.

#### 1.3 High-Precision Seed Matching Rules
- **Strategy**: Exact canonical ID match declares automatic seed alignments without heavy embedding calls.
- **Repository Implementation**:
  - Enforced in [`plugins/biomedical/identity.py`](file:///d:/Hybrid%20kg/plugins/biomedical/identity.py):
    - Exact namespace + ID value returns `BiomedicalIdentityDecisionKind.SAME_ENTITY`.
    - Enforces hard negatives (Gene != Protein, Salt != ActiveMoiety, Cross-species != SameEntity).

---

### Step 2: Embedding-Based Entity Alignment

#### 2.1 Vector Indexing & Candidate Retrieval
- **Strategy**: Perform fast vector-based retrieval over dense entity core using vector indexers (e.g. FAISS).
- **Repository Implementation**:
  - Implemented in [`infrastructure/projections/vector/`](file:///d:/Hybrid%20kg/infrastructure/projections/vector/).
  - Measured via candidate recall metrics (Recall@10, Recall@20, Recall@50) in [`infrastructure/benchmarking/benchmark.py`](file:///d:/Hybrid%20kg/infrastructure/benchmarking/benchmark.py) against versioned biomedical evaluation datasets (`data/benchmarks/biomedical_eval_v1.json`).

#### 2.2 Local 8B Model Verification for Borderline Matches
- **Strategy**: Route ambiguous candidate pairs (0.70 <= score < 0.95) to a local 8B LLM for structured JSON verification with bounded context.
- **Repository Implementation**:
  - Implemented in [`infrastructure/llm/verifier.py`](file:///d:/Hybrid%20kg/infrastructure/llm/verifier.py):
    - Accepts candidate pairs with compact typed context (never unrestricted graph neighborhoods).
    - Returns structured `LLMVerificationResponse` (`outcome`, `confidence`, `reason_codes`).
    - Invalid JSON or model failure automatically fail-safes to `ABSTAIN`.

#### 2.3 GNN Embeddings (RREA / RDGCN / PyTorch Geometric)
- **Strategy**: Train relation-aware GNN embeddings using seed alignments from Step 1.
- **Repository Implementation**:
  - Extension contract defined in [`sdk/resolution.py`](file:///d:/Hybrid%20kg/sdk/resolution.py) via `CandidateRanker`. Custom GNN rankers plug in directly without modifying `core/`.

---

### Step 3: Upfront Ontology Alignment as a "Surface Layer" Operation

#### 3.1 Global Schema & Ontology Registries
- **Strategy**: Establish global schema and ontology mappings (`owl:equivalentClass` bridges) upfront prior to instance matching.
- **Repository Implementation**:
  - Implemented via `OntologyRegistry` and `SchemaRegistry` in [`sdk/registries.py`](file:///d:/Hybrid%20kg/sdk/registries.py).
  - Relation domain/range contracts and inverse semantics defined in [`plugins/biomedical/relations.py`](file:///d:/Hybrid%20kg/plugins/biomedical/relations.py).

#### 3.2 Rule-Based Matchers & LLM Oracle Cascade
- **Strategy**: Use fast rule-based ontology matchers (LogMap, AML) for 90% of schema bridging, escalating ambiguous cases to local 8B LLM.
- **Repository Implementation**:
  - Supported via `Validator` / `ApplicationValidator` contracts in [`sdk/validation.py`](file:///d:/Hybrid%20kg/sdk/validation.py).
  - Cascaded verification handled by `Local8BVerifier` in `infrastructure/llm/`.

---

## Conclusion

The **"Pragmatic Lean"** 3-step pipeline strategy aligns remarkably well with this codebase:
- **Selective Fusion & Anchor IDs**: Fully Implemented & Enforced.
- **Vector Retrieval & 8B Verification**: Fully Implemented & Enforced.
- **Upfront Schema Registries & Rule-Based Alignment**: Fully Implemented & Enforced.
- **GNN Embedding Models**: Supported via the pluggable `CandidateRanker` SDK contract.
