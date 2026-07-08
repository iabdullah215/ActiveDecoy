"""Documentation and OpenAPI metadata smoke tests."""

from __future__ import annotations

import unittest
from pathlib import Path

from app.main import OPENAPI_TAGS, app


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOCS = PROJECT_ROOT / "docs"


class DocumentationFilesTests(unittest.TestCase):
    def test_required_docs_exist(self) -> None:
        required = [
            "README.md",
            "ARCHITECTURE.md",
            "RUNBOOK.md",
            "TROUBLESHOOTING.md",
            "ONBOARDING.md",
            "API.md",
        ]
        for name in required:
            path = DOCS / name if name != "README.md" else DOCS / "README.md"
            self.assertTrue(path.exists(), f"missing {path}")

    def test_demo_script_exists(self) -> None:
        script = PROJECT_ROOT / "scripts" / "demo_walkthrough.sh"
        self.assertTrue(script.exists())
        self.assertTrue(script.stat().st_mode & 0o111, "demo_walkthrough.sh should be executable")


class OpenApiMetadataTests(unittest.TestCase):
    def test_openapi_has_tags_and_version(self) -> None:
        schema = app.openapi()
        self.assertEqual(schema["info"]["title"], "ActiveDecoy")
        self.assertEqual(schema["info"]["version"], "0.12.0")
        tag_names = {item["name"] for item in schema.get("tags", [])}
        expected = {item["name"] for item in OPENAPI_TAGS}
        self.assertTrue(expected.issubset(tag_names))

    def test_health_route_documented(self) -> None:
        schema = app.openapi()
        health = schema["paths"].get("/api/health", {}).get("get", {})
        self.assertEqual(health.get("summary"), "Liveness and subsystem status")
        self.assertIn("system", health.get("tags", []))


if __name__ == "__main__":
    unittest.main()
