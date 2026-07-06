import json
import sys
import unittest
from pathlib import Path

# scripts/ is not a package — add it to path
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import generate_openapi as gen  # noqa: E402

from emhass.command_line import EMHASS_SCHEMA_VERSION  # noqa: E402


def _resolve_schema_ref(openapi_doc, schema):
    if "$ref" not in schema:
        return schema
    ref = schema["$ref"]
    assert ref.startswith("#/")
    resolved = openapi_doc
    for part in ref.removeprefix("#/").split("/"):
        resolved = resolved[part]
    return resolved


class TestInputToSchema(unittest.TestCase):
    def test_select_becomes_string_enum(self):
        p = {
            "input": "select",
            "select_options": ["a", "b"],
            "default_value": "a",
            "friendly_name": "F",
            "Description": "D",
            "unit": "none",
        }
        s = gen._input_to_schema("select", p)
        self.assertEqual(s["type"], "string")
        self.assertEqual(s["enum"], ["a", "b"])
        self.assertEqual(s["default"], "a")

    def test_int_and_float(self):
        self.assertEqual(
            gen._input_to_schema("int", {"input": "int", "default_value": 5})["type"], "integer"
        )
        self.assertEqual(
            gen._input_to_schema("float", {"input": "float", "default_value": 1.0})["type"],
            "number",
        )

    def test_array_float_wraps_items_with_scalar_default(self):
        p = {
            "input": "array.float",
            "default_value": 3000,
            "unit": "W",
            "friendly_name": "N",
            "Description": "D",
        }
        s = gen._input_to_schema("array.float", p)
        self.assertEqual(s["type"], "array")
        self.assertEqual(s["items"]["type"], "number")
        self.assertEqual(s["items"]["default"], 3000)  # per-element template default
        self.assertNotIn("default", s)  # not on the array itself
        self.assertEqual(s["x-unit"], "W")  # unit annotation on the property

    def test_nested_array_array_float(self):
        s = gen._input_to_schema(
            "array.array.float", {"input": "array.array.float", "default_value": None}
        )
        self.assertEqual(s["type"], "array")
        self.assertEqual(s["items"]["type"], "array")
        self.assertEqual(s["items"]["items"]["type"], "number")

    def test_object_and_time(self):
        self.assertEqual(
            gen._input_to_schema("object", {"input": "object", "default_value": None})["type"],
            "object",
        )
        self.assertEqual(
            gen._input_to_schema("array.time", {"input": "array.time", "default_value": None})[
                "items"
            ]["type"],
            "string",
        )

    def test_unknown_input_raises(self):
        with self.assertRaises(SystemExit):
            gen._input_to_schema("widget", {"input": "widget"})

    def test_null_default_omitted(self):
        s = gen._input_to_schema("float", {"input": "float", "default_value": None})
        self.assertNotIn("default", s)


class TestConfigComponent(unittest.TestCase):
    def _defs(self):
        return {
            "SectionA": {
                "costfun": {
                    "input": "select",
                    "select_options": ["profit", "cost"],
                    "default_value": "profit",
                    "friendly_name": "Cost",
                    "Description": "d",
                    "unit": "none",
                }
            },
            "SectionB": {
                "battery_power": {
                    "input": "int",
                    "default_value": 5,
                    "friendly_name": "BP",
                    "Description": "d",
                    "unit": "W",
                }
            },
        }

    def test_flattens_all_sections_into_properties(self):
        comp = gen.build_config_component(self._defs())
        self.assertEqual(comp["type"], "object")
        self.assertIn("costfun", comp["properties"])
        self.assertIn("battery_power", comp["properties"])

    def test_duplicate_key_across_sections_raises(self):
        defs = self._defs()
        defs["SectionB"]["costfun"] = {"input": "int", "default_value": 1}
        with self.assertRaises(SystemExit):
            gen.build_config_component(defs)


class TestRouteGuard(unittest.TestCase):
    def test_undocumented_route_raises(self):
        routes = {("/healthz", "GET"), ("/brand-new", "GET")}
        curated = {"/healthz": {"GET"}}
        skip = {"/"}
        with self.assertRaises(SystemExit):
            gen.assert_no_undocumented(routes, curated, skip)

    def test_skiplisted_and_curated_ok(self):
        routes = {("/healthz", "GET"), ("/", "GET")}
        curated = {"/healthz": {"GET"}}
        skip = {"/"}
        gen.assert_no_undocumented(routes, curated, skip)  # no raise

    def test_discovered_routes_returns_pairs(self):
        routes = gen.discovered_routes()
        self.assertTrue(all(isinstance(p, tuple) and len(p) == 2 for p in routes))
        # the curated API routes must be discoverable (proves url_map import works)
        paths = {p for p, _ in routes}
        self.assertIn("/api/v1/last-run", paths)

    def test_curated_union_skip_covers_live_routes(self):
        # the live route set must be fully partitioned by CURATED ∪ SKIP
        gen.assert_no_undocumented(gen.discovered_routes(), gen.CURATED, gen.SKIP)

    def test_normalise_path_converts_converters_and_args(self):
        self.assertEqual(gen._normalise_path("/action/<action_name>"), "/action/{action_name}")
        self.assertEqual(gen._normalise_path("/action/<int:action_id>"), "/action/{action_id}")
        self.assertEqual(gen._normalise_path("/static/<path:filename>"), "/static/{filename}")
        self.assertEqual(gen._normalise_path("/healthz"), "/healthz")  # no params untouched


class TestBuildSpec(unittest.TestCase):
    def test_spec_info_version_matches_schema_version(self):
        spec = gen.build_spec()

        self.assertEqual(spec["info"]["version"], EMHASS_SCHEMA_VERSION)

    def test_build_spec_filters_paths_to_live_routes(self):
        # only routes present in the passed-in live set survive; other curated paths drop
        spec = gen.build_spec(routes={("/get-config", "GET"), ("/healthz", "GET")})
        self.assertEqual(set(spec["paths"]), {"/get-config", "/healthz"})
        self.assertNotIn("/get-json", spec["paths"])

    def test_spec_has_core_shape_and_curated_paths(self):
        spec = gen.build_spec()
        self.assertEqual(spec["openapi"], "3.1.0")
        self.assertEqual(spec["info"]["title"], "EMHASS API")
        self.assertTrue(spec["info"]["version"])  # EMHASS_SCHEMA_VERSION
        for p in (
            "/get-config",
            "/set-config",
            "/get-json",
            "/action/{action_name}",
            "/api/v1/last-run",
            "/healthz",
        ):
            self.assertIn(p, spec["paths"], f"missing {p}")
        # HTML/UI routes absent
        for p in ("/", "/index", "/template", "/configuration", "/static/{filename}"):
            self.assertNotIn(p, spec["paths"])
        # config + inlined response components present
        self.assertIn("Config", spec["components"]["schemas"])
        self.assertIn("RuntimeParams", spec["components"]["schemas"])
        self.assertIn("LastRun", spec["components"]["schemas"])
        self.assertIn("Healthz", spec["components"]["schemas"])

    def test_config_includes_battery_mode_lock_site_enum(self):
        spec = gen.build_spec()
        schema = spec["components"]["schemas"]["Config"]["properties"]["battery_mode_lock"]

        self.assertEqual(schema["default"], "site")
        self.assertEqual(schema["enum"], ["site"])

    def test_action_operation_links_plan_output_doc(self):
        # externalDocs must sit on the Operation Object (valid in OpenAPI 3.1),
        # not on a Response Object (invalid — strict validators reject it).
        spec = gen.build_spec()
        action = spec["paths"]["/action/{action_name}"]["post"]
        self.assertIn("plan_output_schema.md", action["externalDocs"]["url"])
        self.assertNotIn("externalDocs", action["responses"]["200"])

    def test_action_request_is_open_object(self):
        spec = gen.build_spec()
        body = spec["paths"]["/action/{action_name}"]["post"]["requestBody"]
        schema = body["content"]["application/json"]["schema"]
        schema = _resolve_schema_ref(spec, schema)
        self.assertEqual(schema["type"], "object")
        self.assertTrue(schema["additionalProperties"])

    def test_action_request_uses_pattern_based_runtime_params_component(self):
        spec = gen.build_spec()
        body = spec["paths"]["/action/{action_name}"]["post"]["requestBody"]
        request_schema = body["content"]["application/json"]["schema"]
        runtime_schema = _resolve_schema_ref(spec, request_schema)

        self.assertIs(runtime_schema, spec["components"]["schemas"]["RuntimeParams"])
        self.assertNotIn("hybrid_inverter_config_<N>", runtime_schema.get("properties", {}))
        self.assertNotIn("hybrid_inverter_config_1", runtime_schema.get("properties", {}))
        self.assertIn(
            "^hybrid_inverter_config_[1-9][0-9]*$",
            runtime_schema.get("patternProperties", {}),
        )
        self.assertTrue(runtime_schema["additionalProperties"])

    def test_runtime_block_pattern_schema_documents_nested_pv_forecast(self):
        spec = gen.build_spec()
        runtime_schema = spec["components"]["schemas"]["RuntimeParams"]
        pattern_properties = runtime_schema.get("patternProperties", {})
        block_schema = pattern_properties["^hybrid_inverter_config_[1-9][0-9]*$"]
        description = block_schema["description"]

        self.assertNotIn("hybrid_inverter_config_<N>", runtime_schema.get("properties", {}))
        self.assertNotIn("hybrid_inverter_config_1", runtime_schema.get("properties", {}))
        for expected in (
            "already configured hybrid_inverter_config_N block where N >= 1",
            "split_pv",
            "pv_power_forecast",
            "numeric non-negative JSON list",
            "length at least the optimization horizon",
            "Flat top-level runtime keys continue to address block 0",
            "Runtime cannot create blocks",
        ):
            self.assertIn(expected, description)

    def test_runtime_params_component_has_no_config_scalar_duplicates(self):
        spec = gen.build_spec()
        runtime_schema = spec["components"]["schemas"]["RuntimeParams"]
        runtime_properties = set(runtime_schema.get("properties", {}))

        self.assertFalse(
            runtime_properties
            & {
                "battery_charge_power_max",
                "battery_discharge_power_max",
                "battery_minimum_state_of_charge",
                "battery_maximum_state_of_charge",
            }
        )


class TestOpenapiArtifact(unittest.TestCase):
    OUT = REPO_ROOT / "src" / "emhass" / "static" / "openapi.json"

    def test_load_json_strips_schema_and_id(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.schema.json"
            p.write_text(
                json.dumps({"$schema": "h", "$id": "i", "type": "object", "foo": 1}),
                encoding="utf-8",
            )
            loaded = gen._load_json(p)
        self.assertNotIn("$schema", loaded)
        self.assertNotIn("$id", loaded)
        self.assertEqual(loaded["foo"], 1)  # real content preserved

    def test_committed_file_is_valid(self):
        self.assertTrue(self.OUT.exists(), f"missing {self.OUT} — run scripts/generate_openapi.py")
        spec = json.loads(self.OUT.read_text(encoding="utf-8"))
        for key in ("openapi", "info", "paths", "components"):
            self.assertIn(key, spec)
        # every internal $ref resolves to a declared component
        names = set(spec["components"]["schemas"])
        text = json.dumps(spec)
        for ref in ("Config", "LastRun", "Healthz"):
            if f"#/components/schemas/{ref}" in text:
                self.assertIn(ref, names)

    def test_committed_matches_generated(self):
        committed = json.loads(self.OUT.read_text(encoding="utf-8"))
        fresh = gen.generate()
        self.assertEqual(
            committed,
            fresh,
            "openapi.json is stale — run `python scripts/generate_openapi.py` and commit",
        )


if __name__ == "__main__":
    unittest.main()
