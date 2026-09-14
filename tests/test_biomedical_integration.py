"""Comprehensive Biomedical Integration Tests for RDFLib Parsing & Fusion Attribution."""

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from core.fusion.models import ConflictMode, GraphFusionRequest
from core.fusion.service import GraphFusionService
from core.identifiers.identifier import Identifier
from core.parsing.parsers import TurtleParser

TESTDATA_DIR = Path(__file__).resolve().parent.parent / "testdata"


def test_rdflib_turtle_parsing_complex_syntax():
    """Verify RDFLib parser handles @prefix, quoted strings with dots, decimals, semicolons, and commas."""
    turtle_content = """
    @prefix exa: <http://biomed.example.org/a/> .
    @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

    exa:P001 exa:name "Dr. Anita Rao" ;
             exa:similarityScore "0.91"^^xsd:decimal ;
             exa:knows exa:P002, exa:P003 .
    """
    parser = TurtleParser()
    parsed_at = datetime.now(UTC)
    artifact_id = Identifier(namespace="artifact", value="art_complex_turtle")

    records = parser.parse(
        turtle_content.encode("utf-8"), artifact_id=artifact_id, parsed_at=parsed_at
    )
    assert len(records) == 4

    payloads = [r.payload for r in records if r.payload]
    subjects = [p["subject"] for p in payloads]
    [p["predicate"] for p in payloads]
    objects = [p["object"] for p in payloads]

    assert "http://biomed.example.org/a/P001" in subjects
    assert "Dr. Anita Rao" in objects
    assert "0.91" in objects
    assert "http://biomed.example.org/a/P002" in objects
    assert "http://biomed.example.org/a/P003" in objects


def test_graph_a_and_graph_b_content_attribution():
    """Assert Graph A input (exa:) produces exa: assertions, Graph B (exb:) produces exb: assertions, and hashes are distinct."""
    graph_a_str = """
    @prefix exa: <http://biomed.example.org/a/> .
    exa:INS exa:encodes exa:Insulin_Protein .
    """
    graph_b_str = """
    @prefix exb: <http://pharm.example.org/b/> .
    exb:Metformin exb:targets exb:Insulin_Protein .
    """

    hash_a = hashlib.sha256(graph_a_str.encode("utf-8")).hexdigest()
    hash_b = hashlib.sha256(graph_b_str.encode("utf-8")).hexdigest()
    assert hash_a != hash_b

    service = GraphFusionService()
    act_id = Identifier(namespace="activity", value="act_attribution_test")
    g_a_id = Identifier(namespace="release", value="rel_graph_a")
    g_b_id = Identifier(namespace="release", value="rel_graph_b")

    a_assertions = service.parse_content_to_assertions(graph_a_str, "turtle", g_a_id, act_id)
    b_assertions = service.parse_content_to_assertions(graph_b_str, "turtle", g_b_id, act_id)

    assert len(a_assertions) == 1
    assert len(b_assertions) == 1

    a_subj = str(a_assertions[0].subject.value)
    b_subj = str(b_assertions[0].subject.value)

    assert "http://biomed.example.org/a/INS" in a_subj or "exa:INS" in a_subj
    assert "http://pharm.example.org/b/Metformin" in b_subj or "exb:Metformin" in b_subj
    assert "http://pharm.example.org/b/" not in a_subj
    assert "http://biomed.example.org/a/" not in b_subj


def test_sample_biomedical_file_parsing_and_fusion():
    """Verify parsing real biomedical sample file, triple counts, no node_N placeholders, and candidate generation."""
    sample_file = TESTDATA_DIR / "biomedical_sample_graph.ttl"
    assert sample_file.exists()

    content = sample_file.read_text(encoding="utf-8")
    service = GraphFusionService()
    act_id = Identifier(namespace="activity", value="act_file_test")
    g_id = Identifier(namespace="release", value="rel_sample")

    assertions = service.parse_content_to_assertions(content, "turtle", g_id, act_id)
    assert len(assertions) >= 8

    for a in assertions:
        subj_str = str(a.subject.value)
        pred_str = str(a.predicate)
        obj_str = str(a.object.value)

        assert not subj_str.startswith("node_")
        assert not obj_str.startswith("target_")
        assert "_;_" not in obj_str
        assert "node_" not in pred_str

    req = GraphFusionRequest(
        graph_a_content=content,
        graph_a_format="turtle",
        graph_b_content="subject,predicate,object\nhttp://identifiers.org/chembl/CHEMBL1431,targets,http://identifiers.org/uniprot/P01308",
        graph_b_format="csv",
        conflict_mode=ConflictMode.CONFLICT_PRESERVE,
    )

    res = service.execute_fusion(req)
    assert res.total_input_assertions >= 9
    assert res.derived_assertions_count >= 9
    assert len(res.nodes) >= 5
