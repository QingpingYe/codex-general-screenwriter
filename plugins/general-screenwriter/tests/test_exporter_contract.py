import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
REPO_ROOT = ROOT.parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
ILLUSTRATION_SCRIPTS = str(ROOT / "skills" / "illustration-export" / "scripts")
if ILLUSTRATION_SCRIPTS not in sys.path:
    sys.path.insert(0, ILLUSTRATION_SCRIPTS)

from exporter_contract import (
    ExporterContractError,
    check_export_destination,
    load_exporter_contract,
    build_export_manifest,
    validate_export_request,
)


EXPORTERS = ROOT / "config" / "exporters.json"


def html_contract():
    return load_exporter_contract("html_preview", EXPORTERS)


class ValidateRequestTests(unittest.TestCase):
    def test_missing_output_directory_param_is_rejected(self):
        contract = html_contract()
        with self.assertRaises(ExporterContractError):
            validate_export_request(
                contract,
                {"script": "picturebook/script_v1.md"},
                {"size": "A4", "quality": "high"},
            )

    def test_missing_required_user_params_is_rejected(self):
        contract = html_contract()
        with self.assertRaises(ExporterContractError):
            validate_export_request(
                contract,
                {"script": "picturebook/script_v1.md"},
                {"output_directory": "out/preview", "size": "A4"},
            )

    def test_missing_required_inputs_is_rejected(self):
        contract = html_contract()
        with self.assertRaises(ExporterContractError):
            validate_export_request(
                contract,
                {"worldview": "picturebook/worldview_v1.md"},
                {"output_directory": "out/preview", "size": "A4", "quality": "high"},
            )

    def test_unsupported_artifact_type_is_rejected(self):
        contract = html_contract()
        with self.assertRaises(ExporterContractError):
            validate_export_request(
                contract,
                {"script": "picturebook/script_v1.md", "characters": "x.md"},
                {"output_directory": "out/preview", "size": "A4", "quality": "high"},
            )

    def test_valid_request_returns_structured_request(self):
        contract = html_contract()
        request = validate_export_request(
            contract,
            {"script": "picturebook/script_v1.md"},
            {"output_directory": "out/preview", "size": "A4", "quality": "high"},
        )
        self.assertEqual(request.exporter_id, "html_preview")
        self.assertEqual(request.inputs["script"], "picturebook/script_v1.md")


class DestinationTests(unittest.TestCase):
    def test_existing_file_is_not_overwritten_by_default(self):
        target = ROOT / "tests" / "fixtures" / "picturebook-pass.json"
        with self.assertRaises(ExporterContractError):
            check_export_destination(target)

    def test_overwrite_requires_explicit_opt_in(self):
        target = ROOT / "tests" / "fixtures" / "picturebook-pass.json"
        destination = check_export_destination(target, overwrite_allowed=True)
        self.assertTrue(destination.overwrite_allowed)
        self.assertTrue(destination.path.exists())

    def test_fresh_destination_in_existing_directory_passes(self):
        destination = check_export_destination(
            ROOT / "tests" / "fixtures" / "_not_written_by_this_test.html")
        self.assertFalse(destination.path.exists())


class ManifestTests(unittest.TestCase):
    def test_manifest_is_pure_metadata_and_forbids_model_calls(self):
        contract = html_contract()
        request = validate_export_request(
            contract,
            {"script": "picturebook/script_v1.md"},
            {"output_directory": "out/preview", "size": "A4", "quality": "high"},
        )
        manifest = build_export_manifest(contract, request)
        self.assertEqual(manifest["exporter_id"], "html_preview")
        self.assertEqual(manifest["output_format"], "html_preview")
        self.assertEqual(manifest["model_calls"], "forbidden")
        self.assertEqual(manifest["inputs"], {"script": "picturebook/script_v1.md"})

    def test_config_declares_html_preview_contract(self):
        payload = json.loads(EXPORTERS.read_text(encoding="utf-8"))
        ids = {item["exporter_id"] for item in payload["exporters"]}
        self.assertIn("html_preview", ids)


class BuildHtmlIntegrationTests(unittest.TestCase):
    @staticmethod
    def _payload():
        return {
            "project_metadata": {
                "project_id": "proj-1", "series_id": "s1", "title": "小老鼠迈尔斯",
                "episode": 1, "target_age": "3-6", "total_pages": 1,
                "generated_at": "2026-10-10",
            },
            "pages": [
                {"page_number": 1, "english_text": "Little mouse.",
                 "chinese_translation": "小老鼠。", "illustration_description": "插画",
                 "image_path": "x.png"},
            ],
        }

    def test_build_html_rejects_existing_output_file(self):
        from build_html import build_html
        payload = self._payload()
        target = ROOT / "tests" / "fixtures" / "picturebook-pass.json"
        with self.assertRaises(ExporterContractError):
            build_html(payload, target.parent, output_name=target.name)

    def test_build_html_writes_fresh_output(self):
        import tempfile
        from build_html import build_html
        payload = self._payload()
        with tempfile.TemporaryDirectory() as tmp:
            result = build_html(payload, Path(tmp) / "fresh")
            self.assertTrue(Path(result.html_path).exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
