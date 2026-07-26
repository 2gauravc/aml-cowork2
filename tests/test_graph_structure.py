"""Structural guarantees for the CDD graph ordering."""

from __future__ import annotations

import unittest

from src.agents.graph import build_cdd_graph


class CDDGraphStructureTests(unittest.TestCase):
    def test_digital_footprint_runs_after_idv_and_before_adverse_news(self) -> None:
        graph = build_cdd_graph().get_graph()
        edges = {(edge.source, edge.target) for edge in graph.edges}

        self.assertIn(("build_ownership_and_control", "establish_idv_requirements"), edges)
        self.assertIn(("extract_idv_documents", "digital_footprint_assessment"), edges)
        self.assertIn(("digital_footprint_assessment", "adverse_news_screening"), edges)
        self.assertIn(("adverse_news_screening", "evaluate_risk_flags"), edges)
        self.assertIn(("evaluate_risk_flags", "assess_cdd_completeness"), edges)
        self.assertIn(("assess_cdd_completeness", "assess_evidence_quality"), edges)
        self.assertIn(("assess_evidence_quality", "finalize_cdd"), edges)

    def test_graph_builds_with_pipeline_progress_enabled(self) -> None:
        build_cdd_graph(progress_callback=lambda progress: None)


if __name__ == "__main__":
    unittest.main()
