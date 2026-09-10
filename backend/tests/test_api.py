"""Catalog and boundary tests. No production database or provider calls."""
import sys
import unittest
from fastapi.testclient import TestClient
from backend.main import create_app
from scenario_library import get_scenario_by_id, get_scenario_categories


class ApiBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app())
        self.addCleanup(self.client.close)

    def test_liveness_and_side_effect_free_imports(self):
        response = self.client.get("/api/v1/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "service": "echorole-api"})
        for module in ("app", "ai_engine", "rag_engine", "streamlit"):
            self.assertNotIn(module, sys.modules)

    def test_scenario_contract_uses_existing_content_without_private_briefs(self):
        previews = self.client.get("/api/v1/scenarios").json()
        self.assertGreater(len(previews), 0)
        expected_fields = {"id", "title", "category", "context", "conflict", "opening_situation"}
        for preview in previews:
            self.assertEqual(set(preview), expected_fields)
            original = get_scenario_by_id(preview["id"])
            self.assertEqual(preview, {key: original[key] for key in expected_fields})
            self.assertEqual(self.client.get(f'/api/v1/scenarios/{preview["id"]}').json(), preview)

    def test_categories_filter_and_missing_scenario(self):
        categories = self.client.get("/api/v1/scenarios/categories").json()
        self.assertEqual(categories, get_scenario_categories())
        for category in categories:
            previews = self.client.get("/api/v1/scenarios", params={"category": category}).json()
            self.assertTrue(previews)
            self.assertTrue(all(item["category"] == category for item in previews))
        self.assertEqual(self.client.get("/api/v1/scenarios", params={"category": "missing"}).json(), [])
        self.assertEqual(self.client.get("/api/v1/scenarios/missing").status_code, 404)

    def test_stateful_endpoints_require_identity(self):
        self.assertEqual(self.client.post("/api/v1/rooms", json={}).status_code, 401)
        self.assertEqual(self.client.post("/api/v1/scenarios", json={}).status_code, 405)


if __name__ == "__main__":
    unittest.main()
