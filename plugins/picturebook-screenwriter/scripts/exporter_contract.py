"""Fail-closed exporter contract: request validation and destination policy."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


SUPPORTED_FORMATS = {
    "markdown", "json", "screenplay_text", "page_script",
    "html_preview", "asset_registry", "production_checklist",
}


class ExporterContractError(ValueError):
    pass


@dataclass(frozen=True)
class ExporterContract:
    exporter_id: str
    supported_types: tuple[str, ...]
    required_inputs: tuple[str, ...]
    output_format: str
    required_user_params: tuple[str, ...]
    confirmation_policy: str
    validation_policy: str
    model_calls: str = "forbidden"


@dataclass(frozen=True)
class ExportRequest:
    exporter_id: str
    output_format: str
    inputs: Mapping[str, str]
    user_params: Mapping[str, str]


@dataclass(frozen=True)
class ExportDestination:
    path: Path
    exists: bool
    overwrite_allowed: bool


def load_exporter_contract(exporter_id: str, path: str | Path) -> ExporterContract:
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise ExporterContractError(f"无法读取导出器配置：{source}") from error
    if (not isinstance(payload, Mapping)
            or payload.get("schema_version") != 1
            or not isinstance(payload.get("exporters"), list)):
        raise ExporterContractError("导出器配置必须是 schema_version=1 的 exporters 数组")
    for raw in payload["exporters"]:
        if isinstance(raw, Mapping) and raw.get("exporter_id") == exporter_id:
            return _parse_contract(raw)
    raise ExporterContractError(f"未知导出器：{exporter_id!r}")


def validate_export_request(
    contract: ExporterContract,
    inputs: Mapping[str, str],
    user_params: Mapping[str, str],
) -> ExportRequest:
    if not isinstance(inputs, Mapping) or not isinstance(user_params, Mapping):
        raise ExporterContractError("inputs 与 user_params 必须是对象")
    missing_inputs = [
        name for name in contract.required_inputs
        if not isinstance(inputs.get(name), str) or not inputs[name].strip()
    ]
    if missing_inputs:
        raise ExporterContractError(f"缺少必填输入产物：{', '.join(missing_inputs)}")
    unsupported = sorted(set(inputs) - set(contract.supported_types))
    if unsupported:
        raise ExporterContractError(f"输入产物不属于该导出器支持范围：{', '.join(unsupported)}")
    missing_params = [
        name for name in contract.required_user_params
        if not isinstance(user_params.get(name), str) or not user_params[name].strip()
    ]
    if missing_params:
        raise ExporterContractError(f"缺少必填用户参数：{', '.join(missing_params)}")
    return ExportRequest(
        exporter_id=contract.exporter_id,
        output_format=contract.output_format,
        inputs={name: inputs[name] for name in sorted(inputs)},
        user_params={name: user_params[name] for name in sorted(user_params)},
    )


def check_export_destination(
    destination: str | Path, overwrite_allowed: bool = False
) -> ExportDestination:
    path = Path(destination)
    if not path.name or path.is_dir():
        raise ExporterContractError(f"导出目标必须是具体文件路径：{path}")
    if path.exists() and not overwrite_allowed:
        raise ExporterContractError(f"导出目标已存在，未显式允许覆盖：{path}")
    return ExportDestination(
        path=path, exists=path.exists(), overwrite_allowed=bool(overwrite_allowed)
    )


def build_export_manifest(contract: ExporterContract, request: ExportRequest) -> dict[str, Any]:
    return {
        "exporter_id": contract.exporter_id,
        "output_format": contract.output_format,
        "inputs": dict(request.inputs),
        "user_params": dict(request.user_params),
        "confirmation_policy": contract.confirmation_policy,
        "validation_policy": contract.validation_policy,
        "model_calls": contract.model_calls,
    }


def _parse_contract(raw: Mapping[str, Any]) -> ExporterContract:
    required = {
        "exporter_id", "supported_types", "required_inputs", "output_format",
        "required_user_params", "confirmation_policy", "validation_policy",
    }
    if not required <= set(raw):
        raise ExporterContractError(f"导出器契约缺少字段：{raw.get('exporter_id')!r}")
    output_format = raw["output_format"]
    if output_format not in SUPPORTED_FORMATS:
        raise ExporterContractError(f"不支持的输出格式：{output_format!r}")
    return ExporterContract(
        exporter_id=raw["exporter_id"],
        supported_types=tuple(raw["supported_types"]),
        required_inputs=tuple(raw["required_inputs"]),
        output_format=output_format,
        required_user_params=tuple(raw["required_user_params"]),
        confirmation_policy=raw["confirmation_policy"],
        validation_policy=raw["validation_policy"],
        model_calls=raw.get("model_calls", "forbidden"),
    )
