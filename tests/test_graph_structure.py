"""Structural guarantees for the CDD graph ordering."""

from __future__ import annotations

import unittest

from src.agents.graph import build_cdd_graph


class CDDGraphStructureTests(unittest.TestCase):
    def test_red_flags_run_after_idv_document_processing(self) -> None:
        graph = build_cdd_graph().get_graph()
        edges = {(edge.source, edge.target) for edge in graph.edges}

        self.assertIn(("build_ownership_and_control", "establish_idv_requirements"), edges)
        self.assertIn(("extract_idv_documents", "evaluate_risk_flags"), edges)
        self.assertIn(("evaluate_risk_flags", "finalize_cdd"), edges)


if __name__ == "__main__":
    unittest.main()
