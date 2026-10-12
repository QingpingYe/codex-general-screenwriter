import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from exporter_contract import ExporterContractError
from export_run import (
    ExportRunnerError,
    render_export,
    run_export,
    write_export,
)


CONTRACT = ROOT / "config" / "exporters.json"
CLI = ROOT / "scripts" / "export_cli.py"


def episode_payload():
    return {
        "artifact_id": "episode_script",
        "format": "episode_script",
        "series_id": "s1",
        "season_id": "season-1",
        "episode_id": "e2",
        "episode_function": "推进主线：揭露内鬼线索。",
        "arc_beat_ref": "arc-b2",
        "scenes": [
            {
                "scene_id": "S1", "heading": "场1 天台 夜",
                "location": "天台", "time_of_day": "夜",
                "lines": [
                    {"kind": "action", "text": "风把证物袋吹散。"},
                    {"kind": "dialogue", "speaker": "林一",
                     "text": "谁动了我的证据？"},
                ],
                "transition": "切至走廊",
            },
            {
                "scene_id": "S2", "heading": "场2 走廊 夜",
                "location": "走廊", "time_of_day": "夜",
                "lines": [
                    {"kind": "dialogue", "speaker": "陈默",
                     "text": "是人为删的。"},
                ],
                "transition": "",
            },
        ],
    }


def scene_table_payload():
    return {
        "artifact_id": "scene_table",
        "scenes": [
            {
                "scene_id": "S1", "location": "天台", "time_of_day": "夜",
                "cast": ["林一", "陈默"], "props": ["证物袋"],
                "transition": "切至走廊", "notes": "夜戏",
            }
        ],
    }


def season_payloads():
    return {
        "episode_script": episode_payload(),
        "season_arc": {
            "artifact_id": "season_arc",
            "beats": [{"beat_id": "arc-b2", "goal": "揭露内鬼线索"}],
        },
        "continuity_ledger": {
            "artifact_id": "continuity_ledger",
            "entries": [
                {"field": "character_states", "value": "林一: calm -> shaken"},
            ],
        },
    }


def artifact_refs():
    return {"episode_script": "runs/sd-run-1/episode_script.json"}


class RenderTests(unittest.TestCase):
    def test_script_render_is_deterministic_and_keeps_chinese_text(self):
        payloads = {"episode_script": episode_payload()}
        first = render_export("shortdrama_episode_script", payloads)
        second = render_export("shortdrama_episode_script", payloads)
        self.assertEqual(first, second)
        self.assertIn("场1 天台 夜", first)
        self.assertIn("林一：谁动了我的证据？", first)
        self.assertIn("【转场】切至走廊", first)
        self.assertIn("陈默：是人为删的。", first)

    def test_production_checklist_renders_markdown_table(self):
        text = render_export(
            "shortdrama_production_checklist",
            {"scene_table": scene_table_payload()},
        )
        self.assertIn("| 场次 | 地点 | 时段 | 出场 | 道具 | 转场 | 备注 |", text)
        self.assertIn("| S1 | 天台 | 夜 | 林一、陈默 | 证物袋 | 切至走廊 | 夜戏 |", text)

    def test_season_package_embeds_arc_and_continuity(self):
        text = render_export("tv_season_package", season_payloads())
        self.assertIn("《s1》season-1 / e2", text)
        self.assertIn("季弧线目标：揭露内鬼线索", text)
        self.assertIn("林一：谁动了我的证据？", text)
        self.assertIn("| character_states | 林一: calm -> shaken |", text)

    def test_structured_json_is_canonical_and_unescaped(self):
        text = render_export(
            "structured_json", {"episode_script": episode_payload()},
        )
        document = json.loads(text)
        self.assertEqual(document["artifact_id"], "episode_script")
        self.assertIn("揭露内鬼线索", text)
        self.assertLess(text.index('"arc_beat_ref"'), text.index('"format"'))

    def test_invalid_payload_raises_without_writing(self):
        with self.assertRaises(ExportRunnerError):
            render_export(
                "shortdrama_episode_script",
                {"episode_script": {"artifact_id": "episode_script"}},
            )

    def test_script_render_requires_heading(self):
        payloads = {"episode_script": episode_payload()}
        del payloads["episode_script"]["scenes"][0]["heading"]
        with self.assertRaises(ExportRunnerError):
            render_export("shortdrama_episode_script", payloads)

    def test_script_render_requires_canonical_scene_fields(self):
        for key in ("scene_id", "location", "time_of_day"):
            payloads = {"episode_script": episode_payload()}
            del payloads["episode_script"]["scenes"][0][key]
            with self.subTest(key=key), self.assertRaises(ExportRunnerError):
                render_export("shortdrama_episode_script", payloads)

    def test_script_render_rejects_empty_lines(self):
        payloads = {"episode_script": episode_payload()}
        payloads["episode_script"]["scenes"][0]["lines"] = []
        with self.assertRaises(ExportRunnerError):
            render_export("shortdrama_episode_script", payloads)

    def test_production_checklist_missing_scene_id_renders_dash(self):
        text = render_export(
            "shortdrama_production_checklist",
            {"scene_table": {"artifact_id": "scene_table", "scenes": [{}]}},
        )
        self.assertIn("| - | - | - | - | - | - | - |", text)
        self.assertNotIn("| S1 |", text)


class WriteExportTests(unittest.TestCase):
    def test_write_export_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "出稿.txt"
            written = write_export(target, "场1 天台 夜\n")
            self.assertEqual(written, target)
            self.assertEqual(target.read_text(encoding="utf-8"), "场1 天台 夜\n")

    def test_write_failure_removes_partial_temp_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "out.txt"
            with mock.patch(
                "export_run.os.replace", side_effect=OSError("boom")
            ):
                with self.assertRaises(ExportRunnerError):
                    write_export(target, "content")
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_output_directory_creation_failure_raises_runner_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            blocker = Path(tmp) / "blocker"
            blocker.write_text("keep", encoding="utf-8")
            with self.assertRaises(ExportRunnerError):
                write_export(blocker / "sub" / "out.txt", "content")
            self.assertEqual(blocker.read_text(encoding="utf-8"), "keep")
            self.assertEqual(list(Path(tmp).iterdir()), [blocker])

    def test_write_export_rejects_unencodable_content_without_temp(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "out.txt"
            with self.assertRaises(ExportRunnerError):
                write_export(target, "bad\ud800")
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_write_export_rejects_nul_path(self):
        with self.assertRaises(ExportRunnerError):
            write_export(Path("bad\x00dir") / "out.txt", "content")

    def test_existing_file_is_not_overwritten_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "out.txt"
            target.write_text("keep", encoding="utf-8")
            with self.assertRaises(ExporterContractError):
                write_export(target, "replace")
            self.assertEqual(target.read_text(encoding="utf-8"), "keep")


class RunExportTests(unittest.TestCase):
    def test_run_export_writes_validated_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_export(
                "shortdrama_episode_script",
                artifact_refs(),
                {"episode_script": episode_payload()},
                {"output_directory": tmp, "filename": "e2.txt"},
                contract_path=CONTRACT,
            )
            self.assertEqual(result.destination, Path(tmp) / "e2.txt")
            self.assertGreater(result.bytes_written, 0)
            self.assertEqual(result.manifest["model_calls"], "forbidden")
            self.assertIn(
                "林一：谁动了我的证据？",
                result.destination.read_text(encoding="utf-8"),
            )

    def test_existing_destination_is_not_overwritten_without_opt_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "e2.txt"
            target.write_text("keep", encoding="utf-8")
            with self.assertRaises(ExporterContractError):
                run_export(
                    "shortdrama_episode_script",
                    artifact_refs(),
                    {"episode_script": episode_payload()},
                    {"output_directory": tmp, "filename": "e2.txt"},
                    contract_path=CONTRACT,
                )
            self.assertEqual(target.read_text(encoding="utf-8"), "keep")

    def test_overwrite_opt_in_replaces_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "e2.txt"
            target.write_text("old", encoding="utf-8")
            run_export(
                "shortdrama_episode_script",
                artifact_refs(),
                {"episode_script": episode_payload()},
                {"output_directory": tmp, "filename": "e2.txt"},
                overwrite_allowed=True,
                contract_path=CONTRACT,
            )
            self.assertIn(
                "场1 天台 夜", target.read_text(encoding="utf-8"),
            )

    def test_failed_render_leaves_no_files_and_no_temp(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ExportRunnerError):
                run_export(
                    "shortdrama_episode_script",
                    artifact_refs(),
                    {"episode_script": {"artifact_id": "episode_script"}},
                    {"output_directory": tmp, "filename": "e2.txt"},
                    contract_path=CONTRACT,
                )
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_filename_with_path_separator_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ExportRunnerError):
                run_export(
                    "shortdrama_episode_script",
                    artifact_refs(),
                    {"episode_script": episode_payload()},
                    {"output_directory": tmp, "filename": "../escape.txt"},
                    contract_path=CONTRACT,
                )
            self.assertFalse((Path(tmp).parent / "escape.txt").exists())

    def test_missing_required_user_param_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ExporterContractError):
                run_export(
                    "shortdrama_episode_script",
                    artifact_refs(),
                    {"episode_script": episode_payload()},
                    {"output_directory": tmp},
                    contract_path=CONTRACT,
                )

    def test_nul_output_directory_is_rejected(self):
        with self.assertRaises(ExportRunnerError):
            run_export(
                "shortdrama_episode_script",
                artifact_refs(),
                {"episode_script": episode_payload()},
                {"output_directory": "bad\x00dir", "filename": "e2.txt"},
                contract_path=CONTRACT,
            )


class ExportCliTests(unittest.TestCase):
    def test_cli_roundtrip_writes_file_and_respects_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            refs_file = tmp_path / "refs.json"
            payloads_file = tmp_path / "payloads.json"
            params_file = tmp_path / "params.json"
            refs_file.write_text(
                json.dumps(artifact_refs(), ensure_ascii=False), encoding="utf-8",
            )
            payloads_file.write_text(
                json.dumps({"episode_script": episode_payload()},
                           ensure_ascii=False),
                encoding="utf-8",
            )
            params_file.write_text(
                json.dumps({"output_directory": tmp,
                            "filename": "episode.json"},
                           ensure_ascii=False),
                encoding="utf-8",
            )
            command = [
                sys.executable, str(CLI),
                "--exporter-id", "structured_json",
                "--artifact-refs", str(refs_file),
                "--payloads", str(payloads_file),
                "--params", str(params_file),
            ]
            first = subprocess.run(
                command, capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            written = tmp_path / "episode.json"
            document = json.loads(written.read_text(encoding="utf-8"))
            self.assertEqual(document["artifact_id"], "episode_script")
            second = subprocess.run(
                command, capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(second.returncode, 1)
            third = subprocess.run(
                command + ["--overwrite"],
                capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(third.returncode, 0, third.stderr)

    def test_cli_directory_failure_has_no_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            blocker = tmp_path / "blocker"
            blocker.write_text("keep", encoding="utf-8")
            refs_file = tmp_path / "refs.json"
            payloads_file = tmp_path / "payloads.json"
            params_file = tmp_path / "params.json"
            refs_file.write_text(
                json.dumps(artifact_refs(), ensure_ascii=False),
                encoding="utf-8",
            )
            payloads_file.write_text(
                json.dumps({"episode_script": episode_payload()},
                           ensure_ascii=False),
                encoding="utf-8",
            )
            params_file.write_text(
                json.dumps({"output_directory": str(blocker / "sub"),
                            "filename": "e2.txt"},
                           ensure_ascii=False),
                encoding="utf-8",
            )
            result = subprocess.run([
                sys.executable, str(CLI),
                "--exporter-id", "shortdrama_episode_script",
                "--artifact-refs", str(refs_file),
                "--payloads", str(payloads_file),
                "--params", str(params_file),
            ], capture_output=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn(b"[export_cli]", result.stderr)
            self.assertNotIn(b"Traceback", result.stderr)

    def test_cli_output_is_utf8_with_chinese_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            refs_file = tmp_path / "refs.json"
            payloads_file = tmp_path / "payloads.json"
            params_file = tmp_path / "params.json"
            refs_file.write_text(
                json.dumps(artifact_refs(), ensure_ascii=False),
                encoding="utf-8",
            )
            payloads_file.write_text(
                json.dumps({"episode_script": episode_payload()},
                           ensure_ascii=False),
                encoding="utf-8",
            )
            params_file.write_text(
                json.dumps({"output_directory": tmp,
                            "filename": "第一集.txt"},
                           ensure_ascii=False),
                encoding="utf-8",
            )
            result = subprocess.run([
                sys.executable, str(CLI),
                "--exporter-id", "shortdrama_episode_script",
                "--artifact-refs", str(refs_file),
                "--payloads", str(payloads_file),
                "--params", str(params_file),
            ], capture_output=True, text=True, encoding="utf-8",
                errors="replace")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("第一集.txt", result.stdout)
            written = tmp_path / "第一集.txt"
            self.assertIn(
                "林一：谁动了我的证据？",
                written.read_text(encoding="utf-8"),
            )

    def test_cli_unencodable_content_has_no_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            refs_file = tmp_path / "refs.json"
            payloads_file = tmp_path / "payloads.json"
            params_file = tmp_path / "params.json"
            payload = episode_payload()
            payload["scenes"][0]["lines"][0]["text"] = "bad\ud800"
            refs_file.write_text(
                json.dumps(artifact_refs(), ensure_ascii=False),
                encoding="utf-8",
            )
            payloads_file.write_text(
                json.dumps({"episode_script": payload}, ensure_ascii=True),
                encoding="utf-8",
            )
            params_file.write_text(
                json.dumps({"output_directory": tmp, "filename": "e2.txt"},
                           ensure_ascii=False),
                encoding="utf-8",
            )
            result = subprocess.run([
                sys.executable, str(CLI),
                "--exporter-id", "shortdrama_episode_script",
                "--artifact-refs", str(refs_file),
                "--payloads", str(payloads_file),
                "--params", str(params_file),
            ], capture_output=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn(b"[export_cli]", result.stderr)
            self.assertNotIn(b"Traceback", result.stderr)
            self.assertEqual(
                sorted(item.name for item in tmp_path.iterdir()),
                ["params.json", "payloads.json", "refs.json"],
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
