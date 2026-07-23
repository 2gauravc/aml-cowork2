"""Tests for the credential-free, fixture-backed local demo."""

from __future__ import annotations

import asyncio
import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from src.backend.app import DemoLoadRequest, PipelineRequest, SESSIONS, load_demo_case, run_pipeline


class DemoModeTests(unittest.TestCase):
    def setUp(self) -> None:
        SESSIONS.clear()

    def tearDown(self) -> None:
        SESSIONS.clear()

    def test_load_demo_case_uses_fixture_without_external_services(self) -> None:
        with patch.dict(os.environ, {"DEMO_MODE": "true"}, clear=False), patch(
            "src.backend.app.run_cdd_agent_state"
        ) as run_graph, patch("src.backend.app.find_documents_in_s3") as find_s3:
            response = asyncio.run(load_demo_case(DemoLoadRequest()))

        self.assertEqual(response["status"], "complete")
        self.assertTrue(response["demo_mode"])
        self.assertEqual(response["customer_name"], "Northstar Trading Ltd")
        self.assertTrue(response["case_review_summary"]["demo_fixture"])
        self.assertEqual(len(response["document_requirements"]), 2)
        self.assertEqual(response["document_requirements"][0]["document_type"], "registry_document")
        self.assertTrue(response["document_requirements"][0]["demo_url"].endswith("northstar-registry-business-profile.html"))
        maya = response["cdd"]["individual_identity_verification"]["required_individuals"][0]
        self.assertEqual(maya["document"]["document_number"], "P-DEMO-48291")
        self.assertEqual(maya["document"]["nationality"], "Singaporean")
        run_graph.assert_not_called()
        find_s3.assert_not_called()

    def test_pipeline_loads_demo_fixture_without_running_graph(self) -> None:
        with patch.dict(os.environ, {"DEMO_MODE": "1"}, clear=False), patch(
            "src.backend.app.run_cdd_agent_state"
        ) as run_graph:
            response = asyncio.run(
                run_pipeline(
                    request=PipelineRequest(
                        customer_name="Ignored in Demo Mode",
                        jurisdiction="GB",
                    ),
                    background_tasks=None,
                )
            )

        self.assertEqual(response["status"], "complete")
        self.assertTrue(response["demo_mode"])
        run_graph.assert_not_called()

    def test_demo_endpoint_is_unavailable_when_demo_mode_is_disabled(self) -> None:
        with patch.dict(os.environ, {"DEMO_MODE": "false"}, clear=False), self.assertRaises(HTTPException) as raised:
            asyncio.run(load_demo_case(DemoLoadRequest()))

        self.assertEqual(raised.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
