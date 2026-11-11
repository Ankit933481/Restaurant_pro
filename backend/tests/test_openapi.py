import os
import re

from tests.base import ApiTest

SPEC = os.path.join(os.path.dirname(__file__), "..", "openapi.yaml")


class OpenApiTests(ApiTest):
    def test_every_route_is_documented(self):
        import yaml
        with open(SPEC, encoding="utf-8") as fh:
            spec = yaml.safe_load(fh)
        documented = {(m.upper(), p) for p, ops in spec["paths"].items() for m in ops if m in ("get", "post", "put", "patch", "delete")}
        actual = set()
        for rule in self.app.url_map.iter_rules():
            if not rule.rule.startswith("/api/v1/") or rule.rule.endswith("openapi.yaml"):
                continue
            path = re.sub(r"<int:(\w+)>", r"{\1}", rule.rule)[len("/api/v1"):]
            for method in rule.methods - {"HEAD", "OPTIONS"}:
                actual.add((method, path))
        self.assertEqual(sorted(actual - documented), [], "routes missing from openapi.yaml")
        self.assertEqual(sorted(documented - actual), [], "openapi.yaml documents routes that do not exist")

    def test_docs_are_served(self):
        self.assertIn("openapi", self.c.get("/api/v1/openapi.yaml").get_data(as_text=True)[:40])
        self.assertEqual(self.c.get("/api/docs").status_code, 200)
