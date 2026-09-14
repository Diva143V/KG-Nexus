# AI CODING RULES — KG PLATFORM

## 1. Architecture

Core = mechanics.
Domain Pack = semantics.

Never invert this relationship.

## 2. Core isolation

core/ must not import:

- plugins.biomedical
- Neo4j-specific implementation
- specific LLM implementation
- biomedical ontology libraries
- biomedical identifier libraries

## 3. Immutable knowledge

Assertions are immutable.

Never update an Assertion in place.

State changes create AssertionStateEvent.

## 4. Provenance

Every promoted assertion must be traceable to:

Assertion
→ Activity
→ Agent
→ Input
→ Artifact
→ SourceRelease

## 5. Derived knowledge

Every derived assertion must contain:

- input_assertion_refs
- input_resource_refs
- derivation_method
- activity_id
- agent_id

## 6. RDF authority

RDF is authoritative.

Neo4j is derived.

Never make Neo4j the source of truth.

## 7. LLM

LLM is optional.

LLM cannot:

- promote assertions
- bypass validators
- bypass policies
- write RDF directly
- delete assertions

## 8. Reproducibility

Every release must identify:

- source artifacts
- source adapter versions
- parser versions
- plugin versions
- ontology versions
- policy versions
- matcher versions
- model versions
- reasoner versions
- projection versions
- runtime version

## 9. Testing

Every feature requires tests.

Every biomedical rule requires:

- positive fixture
- negative fixture
- hard negative where applicable

## 10. No speculative abstraction

Do not implement infrastructure merely because it may be useful later.

Implement only what the current phase requires.

## 11. No silent semantic loss

Projection transformations must be declared.

Unsupported semantics must be reported.

Never silently discard semantic information.

## 12. Determinism

Where deterministic behavior is required:

- sort inputs
- canonicalize identifiers
- canonicalize literals
- pin versions
- pin model configuration
- generate reproducible digests

## 13. Security

Never log:

- secrets
- tokens
- credentials
- unrestricted sensitive model context

## 14. Phase discipline

Never implement future phases without explicit authorization.

Every phase must pass its gate before continuing.
