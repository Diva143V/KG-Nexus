"""Unit Tests for Stage 1: Data Normalization.

Verifies:
- Literals (values: 'Alice', 250, dates, booleans) remain typed values and NEVER become entity nodes.
- Entities (nodes: people, companies, places, genes) are properly recognized as nodes.
- Labels, formats, and identifiers are standardized (quote stripping, date ISO-8601, number casting).
- Text matching an entity label is never converted to an entity node if asserted as a literal predicate.
"""

from datetime import UTC, datetime

from core.assertions.assertion import Assertion
from core.fusion.normalizer import DataNormalizer, is_literal_value, normalize_label_text
from core.identifiers.identifier import Identifier
from core.provenance.provenance import Provenance
from sdk.domain_config import LiteralRuleConfig, get_general_agnostic_preset, get_synthetic_preset


def _make_test_assertion(a_id: str, subj: str, pred: str, obj: str) -> Assertion:
    return Assertion(
        id=Identifier(namespace="ASSERT", value=a_id),
        subject=Identifier(namespace="ENTITY", value=subj),
        predicate=pred,
        object=Identifier(namespace="ENTITY", value=obj),
        provenance=Provenance(
            agent_id=Identifier(namespace="SYS", value="test_agent"),
            activity_id=Identifier(namespace="SYS", value="test_act"),
            asserted_at=datetime.now(UTC),
        ),
    )


def test_literals_remain_typed_values_and_never_become_entity_nodes():
    config = get_synthetic_preset()
    normalizer = DataNormalizer(config)

    assertions = [
        _make_test_assertion("a1", "Alice", "name", "Alice"),
        _make_test_assertion("a2", "Alice", "age", "30"),
        _make_test_assertion("a3", "Alice", "birthDate", "1994-05-12"),
        _make_test_assertion("a4", "Alice", "worksAt", "TechCorp"),
        _make_test_assertion("a5", "TechCorp", "foundedYear", "2010"),
    ]

    norm = normalizer.normalize_graph(assertions, "graph_test")

    # Verify only true entities are in entities dict
    assert "Alice" in norm.entities
    assert "TechCorp" in norm.entities
    assert "30" not in norm.entities
    assert "1994-05-12" not in norm.entities
    assert "2010" not in norm.entities

    # Verify literal counts
    assert norm.normalized_literals_count == 4
    assert norm.normalized_entities_count == 2

    # Verify literal properties stored correctly
    assert norm.literal_properties[("Alice", "name")] == ["Alice"]
    assert norm.literal_properties[("Alice", "age")] == [30]
    assert norm.literal_properties[("Alice", "birthDate")] == ["1994-05-12"]
    assert norm.literal_properties[("TechCorp", "foundedYear")] == [2010]


def test_literal_predicate_detection():
    rules = LiteralRuleConfig()
    assert is_literal_value("name", "TechCorp", rules) is True
    assert is_literal_value("description", "A global tech company", rules) is True
    assert is_literal_value("score", "0.95", rules) is True
    assert is_literal_value("worksAt", "TechCorp", rules) is False
    assert is_literal_value("targets", "Insulin", rules) is False


def test_date_and_quote_normalization():
    config = get_general_agnostic_preset()
    normalizer = DataNormalizer(config)

    assertions = [
        _make_test_assertion("a1", "Bob", "birthDate", '"1985/10/25"'),
        _make_test_assertion("a2", "Bob", "score", "'98.5'"),
        _make_test_assertion("a3", "Bob", "status", '"active"'),
    ]

    norm = normalizer.normalize_graph(assertions, "graph_test")
    assert norm.literal_properties[("Bob", "birthDate")] == ["1985-10-25"]
    assert norm.literal_properties[("Bob", "score")] == [98.5]
    assert norm.literal_properties[("Bob", "status")] == ["active"]


def test_label_normalization_and_role_suffix_stripping():
    suffixes = ("drug", "gene", "protein", "inc", "corp")
    assert normalize_label_text("Metformin_Drug", suffixes) == "metformin"
    assert normalize_label_text("Apple Inc", suffixes) == "apple"
    assert normalize_label_text("http://example.org/bio/INS_Gene", suffixes) == "ins"
    assert normalize_label_text("<http://schema.org/Person#Alice>", suffixes) == "alice"
