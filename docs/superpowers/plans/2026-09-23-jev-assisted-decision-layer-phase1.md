# Jev 辅助决策层 Phase 1（共享基础设施）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `picturebook-screenwriter` 建立用户显式的 Jev 执行选择门、一条可独立调用的共享 Jev 运行器（凭证门、契约、重试、租约、恢复点、原子终态、trace 与成本估算），使后续 Phase 2/3 的 operation 只需补策略与问题模板，不必再碰 HTTP、凭证或计费逻辑。

**Architecture:** 新增插件内 utility skill `skills/jev-decision-runtime/`，包含 4 个纯标准库模块：`decision_contract.py`（请求/结果/上下文/策略契约与校验）、`telemetry.py`（benchmark case id、计时、usage、Decimal 成本）、`jev_client.py`（凭证门 + endpoint allowlist + 可注入 transport + 重试与错误分类）、`jev_runner.py`（租约、pending call、恢复、原子终态、CLI）。入口技能新增 Execution Choice Gate 作为第一步，选择以 `pb-decision-context-v1` 附加到 run manifest 与子 Agent task envelope（`stage_dag.py` / `stage_dag_codex.py` 各改一处）。

**Tech Stack:** Python 3.10+（CI 用 3.12），**仅标准库**（CI 不执行任何 `pip install`，因此不得引入 `typesafe-sdk` / `requests` / `httpx`），`unittest`（无 pytest），Node 22 仅用于既有两个 JS 检查。

**Spec:** `docs/superpowers/specs/2026-09-23-jev-assisted-decision-layer-design.md`

**本计划只覆盖 Phase 1。** Phase 2（知识分块相关性筛选）、Phase 3（红线与逐页文本质量预筛）、Phase 4（对比验收）将在 Phase 1 落地后各自单独成计划。Phase 2/3 会向 `decision-policies.json` 追加 `operations.<operation>.question_templates` 与 `routing` 表，并实现路由；Phase 1 只定义路由词表并输出空 `routes`。

## Global Constraints

以下约束适用于每一个任务，逐条取自 spec 与仓库既有治理：

- **仅标准库。** `.github/workflows/ci.yml` 只做 `setup-python` / `setup-node` 后直接运行聚合校验，没有 `pip install`。任何第三方 import 都会让 CI 失败。
- **测试框架固定为 `unittest`**，测试文件命名为 `test_*.py`，与脚本同目录。`scripts/run_plugin_tests.py` 会自动发现 `plugins/picturebook-screenwriter/` 与 `scripts/` 下所有 `test_*.py`，因此新测试**不需要**注册。
- **凡是 Bash 步骤以 `python scripts/run_plugin_tests.py` 结尾的任务，都必须全绿**才能提交。该聚合校验包含 `governance_check.py`，它断言 `config/plugin-contract.json` 的 `skills` 数组与 `skills/` 下的实际目录**集合完全相等**。
- **新增 skill 目录必须登记到 `config/plugin-contract.json` 的 `skills` 数组**，否则 `governance_check.py` 与 `tests/test_plugin_contract.py::test_contract_matches_installed_skills` 同时失败。本计划的 Task 1 必须同时做这两件事。
- **`docs/` 被 `.gitignore` 忽略**（`.gitignore` 第 7 行 `/docs/`）。`docs/` 下已有文件是被跟踪的历史文件，但**新文件不会被 `git add docs/...` 收进去**。凡新增/修改 `docs/` 下的文件，提交时必须用 `git add -f`，并随后用 `git status` 确认已暂存。
- **凭证规则（spec §12）：** 只从环境变量 `TYPESAFE_API_KEY` 读取；不得进入 CLI 参数、manifest、`decision-context.json`、`pending.json`、trace、错误信息、测试 fixture 或日志。缺失或 trim 后为空即视为缺失。
- **固定模型版本 `jev-1.13.0`**，禁止使用会漂移的 `jev-latest` / `jev-preview`；请求契约校验会直接拒绝别名。
- **生产 endpoint 精确为 `https://api.typesafe.ai/v1/systemone`**；scheme 必须 `https`，host 必须精确等于 `api.typesafe.ai`，path 必须精确等于 `/v1/systemone`；不接受任何来自请求、配置或用户输入的 base URL 覆盖；完全禁用 HTTP redirect。
- **脚本 docstring / 注释用英文**，`SKILL.md` 正文与所有用户可见文案用中文——与仓库现有文件一致。
- **提交信息前缀沿用仓库风格**：`feat:` / `fix:` / `docs:` / `refactor:` / `chore:`。
- 每个提交都要带尾部署名行（仓库既有历史提交没有 trailer；这一行是本计划的署名约定，若不想保留，从提交命令里删掉最后那个 `-m` 即可，其余步骤不受影响）：

  ```
  Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
  ```

---

## Review Focus

以下五类是 spec 已经隐含、但任务清单里原本没有测试固定住、最容易在真实使用中咬人的输入与失败模式。每一条都在拥有对应代码的任务里补了一条测试；执行时如果那条测试在补实现之前就通过，说明它没有真正测到要保护的行为。

1. **只有 `request.json` 允许携带 `state` 正文。** 运行器为了可恢复必须把请求体落在本地 run 目录；用户会以为"不导出就不会把故事文本写进磁盘"。`pending.json`、`decision-context.json`、trace 或 result 任何一个携带正文，这个假设就不成立。（固定位置：Task 7 的 `test_only_the_persisted_request_carries_the_state_body` 与 `test_no_written_file_carries_a_credential`。）
2. **服务端可以悄悄换模型版本。** 请求写的是 `jev-1.13.0`，响应里的 `model` 却可能不是它。只记录不拦截，就会把未校准模型给出的概率当成已校准结果使用。（固定位置：Task 7 的 `test_a_different_resolved_model_is_refused`。）
3. **崩溃留下的半写文件必须读成"没有待办"。** 断电或 Ctrl-C 会留下空文件或半截 JSON；恢复路径若把它当成原请求重发，就会产生计划外的计费。（固定位置：Task 8 的 `test_a_corrupt_stored_request_is_not_replayed`。）
4. **同一个 run 里存在两个未完成 operation。** `decision_context.pending_call` 只有一个槽位，磁盘上却可能有两条。恢复时必须拒绝继续，而不是替用户挑一条。（固定位置：Task 8 的 `test_two_pending_operations_cannot_be_resumed_by_guess`。）
5. **凭证等待期间用户改选普通 LLM。** 用户以为"换回普通 LLM 就不会再发 Jev 请求"。切换后不能有任何请求发出，已有的 pending call 也不能被顺手清掉——它要留着，等用户回来显式处理。（固定位置：Task 8 的 `test_switching_to_llm_dispatches_nothing_and_keeps_the_pending_call`。）

---

## File Structure

**新增：**

| 文件 | 职责 |
|---|---|
| `plugins/picturebook-screenwriter/skills/jev-decision-runtime/SKILL.md` | utility skill 的用途、边界、CLI 调用方式 |
| `plugins/picturebook-screenwriter/skills/jev-decision-runtime/references/decision-policies.json` | 固定模型版本、价格快照、校准状态、每 operation 的 policy_version 与 fallback 路由 |
| `.../scripts/decision_contract.py` | `pb-jev-request-v1` / `pb-jev-result-v1` / `pb-decision-context-v1` / `pb-jev-policy-v1` 校验，`ContractError` |
| `.../scripts/telemetry.py` | `benchmark_case_id`、`request_fingerprint`、`Stopwatch`、`DecisionTrace`、Decimal 成本 |
| `.../scripts/jev_client.py` | 凭证门、endpoint allowlist、`UrllibTransport`、`FakeTransport`、重试与错误分类 |
| `.../scripts/jev_runner.py` | 目录布局、原子写、pending call、`decision_context` 同步、租约、恢复、CLI |
| `.../scripts/test_decision_contract.py` | 契约校验测试 |
| `.../scripts/test_telemetry.py` | 计量与成本测试 |
| `.../scripts/test_jev_client.py` | 凭证、allowlist、重试、隔离测试 |
| `.../scripts/test_jev_runner.py` | 租约、pending、恢复、原子终态测试 |
| `plugins/picturebook-screenwriter/tests/test_jev_phase1_integration.py` | 两条路径的端到端集成与脱敏测试 |

**修改：**

| 文件 | 改动 |
|---|---|
| `plugins/picturebook-screenwriter/config/plugin-contract.json` | `skills` 增 `jev-decision-runtime`；新增 `jev_runtime` 与 `execution_choice` 块 |
| `plugins/picturebook-screenwriter/skills/picturebook-screenwriter/SKILL.md` | 新增 `## Execution Choice Gate`，位置在 `## Workflow` 之前 |
| `plugins/picturebook-screenwriter/scripts/stage_dag.py` | `DECISION_CONTEXT_SCHEMA` 常量；`build_revision_manifest` 增加 `decision_context` 参数 |
| `plugins/picturebook-screenwriter/scripts/stage_dag_codex.py` | `format_task_envelope` 透传 `decision_context` |
| `plugins/picturebook-screenwriter/tests/test_plugin_contract.py` | 新增 `execution_choice` / `jev_runtime` 断言 |
| `plugins/picturebook-screenwriter/tests/test_skill_contract.py` | 新增“选择门在意图分类之前”断言 |
| `plugins/picturebook-screenwriter/tests/test_stage_dag.py` | 新增 `build_revision_manifest` 继承 `decision_context` 的断言 |
| `docs/ENFORCEMENT.md` | 新增 Phase 1 的强制力分级行 |
| `docs/CHANGELOG.md` | `[Unreleased]` 下新增 Added / Changed |
| `plugins/picturebook-screenwriter/README.md`, `README.md` | 能力清单与 Jev 配置说明 |
| `docs/RELEASE.md` | 凭证与 live smoke 边界一行 |

**运行时目录布局**（写在 **workspace** 下，绝不在插件目录内——`governance_check.py` 会拒绝插件内出现 `.picturebook-screenwriter`）：

```
<run_dir>/
  decision-context.json                      # pb-decision-context-v1
  jev/
    <operation_id>/                          # operation_id = f"{run_id}-{operation}"
      request.json                           # 不可变的 pb-jev-request-v1
      pending.json                           # pending_call 描述符；终态成功后删除
      lease.json                             # 执行租约；release 时删除
      result.json                            # 原子写入的终态 pb-jev-result-v1
      trace/
        0001.json                            # 每次 attempt 一条 pb-decision-trace-v1
```

---

### Task 1: 运行器骨架与请求/结果契约

建立 `jev-decision-runtime` skill 目录、登记契约、实现 `pb-jev-request-v1` 与 `pb-jev-result-v1` 的校验。这是后续所有任务的地基。

**Files:**
- Create: `plugins/picturebook-screenwriter/skills/jev-decision-runtime/SKILL.md`
- Create: `plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/decision_contract.py`
- Create: `plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/test_decision_contract.py`
- Modify: `plugins/picturebook-screenwriter/config/plugin-contract.json`

**Interfaces:**
- Consumes: 无
- Produces:
  - `decision_contract.ContractError(ValueError)`
  - `decision_contract.REQUEST_SCHEMA = "pb-jev-request-v1"`、`RESULT_SCHEMA = "pb-jev-result-v1"`、`TRACE_SCHEMA = "pb-decision-trace-v1"`、`CONTEXT_SCHEMA = "pb-decision-context-v1"`、`POLICY_SCHEMA = "pb-jev-policy-v1"`
  - `OPERATIONS: tuple[str, ...] = ("knowledge_relevance", "text_quality_prefilter")`
  - `PRIMITIVES: tuple[str, ...] = ("noul", "choice", "score")`
  - `ROUTE_VALUES: tuple[str, ...] = ("include", "exclude_soft", "screened_clear", "escalate_llm", "needs_user_choice")`
  - `RESULT_STATUSES`、`WAITING_STATUSES = ("waiting_for_jev_key", "waiting_for_jev_access")`、`CREDENTIAL_STATUSES`、`EXECUTION_MODES = ("llm", "jev_assisted")`
  - `assert_no_credential_fields(payload, label="payload") -> None`
  - `validate_request(payload) -> None`
  - `validate_answer_ids(request, result) -> None`
  - `validate_result(payload) -> None`

- [ ] **Step 1: 创建 skill 目录与 SKILL.md**

创建 `plugins/picturebook-screenwriter/skills/jev-decision-runtime/SKILL.md`：

```markdown
---
name: jev-decision-runtime
description: 共享 Jev 决策运行器。仅当用户已选择 Jev 辅助路径时使用；负责构造 TypeSafe SystemOne 请求、读取本机凭证、校验响应契约、处理重试与凭证等待、维护恢复点和执行租约、记录耗时与成本。它只做原子概率判断，不生成故事、不解释结论、不写文件、不调用图片生成。
---

# Jev Decision Runtime

本技能是插件内部的共享运行器，不直接面向用户。入口技能、`knowledge-loader`、`pre_output-baseline` 与 `quality-baseline` 都通过它调用 Jev，不各自实现 HTTP、重试或计费。

## 定位

- 只处理第 2 类工作：答案空间明确、需要自然语言常识的原子小判断。
- 不生成文本，不生成图片，不做计数、算术、日期比较或多层间接推理——这些留在确定型脚本。
- 普通 LLM 继续负责生成、解释性终审和修改建议。

## 能力边界（不得夸大）

1. 全局 `typesafe-ai` skill 只是给模型看的设计指南，它没有 transport，不能发起请求。真正的调用由本技能完成。
2. 本技能不能证明用户意图：它只能保证“没有 key 就不发请求”“endpoint 不是 allowlist 就拒绝”“响应不完整就不判定通过”。是否被调用仍取决于技能指令。
3. 本技能不拥有写工作区文件、同步飞书、调用图片生成或修改 DAG 状态的权限。

## 安全约束

- 凭证只从环境变量 `TYPESAFE_API_KEY` 读取，缺失或全空白即视为缺失。
- endpoint 固定为 `https://api.typesafe.ai/v1/systemone`，不接受 base URL 覆盖，禁用 redirect。
- 密钥绝不写入配置、manifest、trace、错误信息或命令行参数。
- 为了在缺 key 之后原地续跑，运行器把本次请求体写入本地 run 目录的 `request.json`；这是运行目录里**唯一**可以携带原文的文件，它不含密钥、不进插件包、也不进导出物，其余落盘物只保留 hash、计数、引用 ID 与概率。
```

- [ ] **Step 2: 写失败测试**

创建 `plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/test_decision_contract.py`：

```python
import unittest

from decision_contract import (
    ContractError,
    OPERATIONS,
    REQUEST_SCHEMA,
    RESULT_SCHEMA,
    assert_no_credential_fields,
    validate_answer_ids,
    validate_request,
    validate_result,
)


def make_request(**overrides):
    request = {
        "schema_version": REQUEST_SCHEMA,
        "run_id": "20260923-example-0001",
        "operation": "knowledge_relevance",
        "model": "jev-1.13.0",
        "policy_version": "knowledge-relevance-v1",
        "state": "目标产物：一本 32 页、面向 3-6 岁的分享主题绘本。",
        "questions": {
            "relevant": {
                "type": "noul",
                "instructions": "该知识块是否直接影响当前产物？",
                "criteria": {"true": "直接影响", "false": "不影响"},
            }
        },
        "context_refs": [
            {
                "ref_id": "海外绘本/小老鼠迈尔斯/worldview",
                "kind": "knowledge_page",
                "revisions": {"node-a": "17"},
            }
        ],
        "benchmark_case_id": "sha256:" + "0" * 64,
    }
    request.update(overrides)
    return request


def make_result(**overrides):
    result = {
        "schema_version": RESULT_SCHEMA,
        "run_id": "20260923-example-0001",
        "operation": "knowledge_relevance",
        "provider": "typesafe",
        "requested_model": "jev-1.13.0",
        "resolved_model": "jev-1.13.0",
        "policy_version": "knowledge-relevance-v1",
        "answers": {"relevant": {"type": "noul", "noul": 0.91}},
        "routes": [],
        "usage": {"input_tokens": 296, "output_tokens": 20},
        "trace": {},
        "status": "succeeded",
    }
    result.update(overrides)
    return result


class RequestContractTests(unittest.TestCase):
    def test_valid_request_is_accepted(self):
        validate_request(make_request())

    def test_unknown_operation_is_rejected(self):
        with self.assertRaises(ContractError):
            validate_request(make_request(operation="write_the_story"))

    def test_moving_model_alias_is_rejected(self):
        for alias in ("jev-latest", "jev-preview"):
            with self.subTest(alias=alias), self.assertRaises(ContractError):
                validate_request(make_request(model=alias))

    def test_empty_questions_are_rejected(self):
        with self.assertRaises(ContractError):
            validate_request(make_request(questions={}))

    def test_empty_context_refs_are_rejected(self):
        with self.assertRaises(ContractError):
            validate_request(make_request(context_refs=[]))

    def test_all_operations_are_accepted(self):
        for operation in OPERATIONS:
            with self.subTest(operation=operation):
                validate_request(make_request(operation=operation))

    def test_credential_shaped_fields_are_rejected(self):
        broken = make_request()
        broken["api_key"] = "sk-should-never-be-here"
        with self.assertRaises(ContractError):
            validate_request(broken)

    def test_token_count_fields_are_not_mistaken_for_credentials(self):
        assert_no_credential_fields({"input_tokens": 1, "output_tokens": 2})


class ResultContractTests(unittest.TestCase):
    def test_valid_result_is_accepted(self):
        validate_result(make_result())

    def test_noul_must_be_a_probability(self):
        broken = make_result(answers={"relevant": {"type": "noul", "noul": 1.4}})
        with self.assertRaises(ContractError):
            validate_result(broken)

    def test_non_finite_probability_is_rejected(self):
        broken = make_result(answers={"relevant": {"type": "noul", "noul": float("nan")}})
        with self.assertRaises(ContractError):
            validate_result(broken)

    def test_choice_needs_matching_probabilities(self):
        broken = make_result(answers={"pick": {
            "type": "choice",
            "choice": "b",
            "probabilities": {"a": 1.0, "b": 0.0},
            "confidence": 1.0,
        }})
        with self.assertRaises(ContractError):
            validate_result(broken)

    def test_choice_probabilities_must_sum_to_one(self):
        broken = make_result(answers={"pick": {
            "type": "choice",
            "choice": "a",
            "probabilities": {"a": 0.4, "b": 0.4},
            "confidence": 0.1,
        }})
        with self.assertRaises(ContractError):
            validate_result(broken)

    def test_score_may_land_between_levels(self):
        validate_result(make_result(answers={"friction": {
            "type": "score",
            "score": 1.05,
            "legend": {"0": "顺口", "1": "略拗口", "2": "很拗口"},
            "probabilities": {"0": 0.0, "1": 0.95, "2": 0.05},
            "confidence": 0.92,
        }}))

    def test_waiting_result_must_not_carry_answers_or_trace(self):
        broken = make_result(status="waiting_for_jev_key")
        with self.assertRaises(ContractError):
            validate_result(broken)

    def test_waiting_result_with_empty_payload_is_accepted(self):
        validate_result(make_result(
            status="waiting_for_jev_key",
            answers={},
            routes=[],
            usage={"input_tokens": None, "output_tokens": None},
            trace={},
            resolved_model=None,
        ))

    def test_outcome_unknown_may_carry_a_trace(self):
        validate_result(make_result(
            status="outcome_unknown",
            answers={},
            routes=[],
            usage={"input_tokens": None, "output_tokens": None},
            trace={"attempt": 1},
            resolved_model=None,
        ))

    def test_unknown_status_is_rejected(self):
        with self.assertRaises(ContractError):
            validate_result(make_result(status="probably_fine"))

    def test_routes_are_per_item_and_use_the_fixed_vocabulary(self):
        validate_result(make_result(routes=[
            {"item_id": "海外绘本/小老鼠迈尔斯/worldview#003",
             "route": "exclude_soft", "label": "clearly_irrelevant"},
            {"item_id": "海外绘本/小老鼠迈尔斯/worldview#004", "route": "include"},
        ]))

    def test_an_unknown_route_value_is_rejected(self):
        with self.assertRaises(ContractError):
            validate_result(make_result(routes=[
                {"item_id": "k#001", "route": "hope_for_the_best"},
            ]))

    def test_a_route_without_an_item_id_is_rejected(self):
        with self.assertRaises(ContractError):
            validate_result(make_result(routes=[{"route": "include"}]))

    def test_a_succeeded_result_can_carry_routes_with_answers(self):
        validate_result(make_result(routes=[
            {"item_id": "k#001", "route": "escalate_llm", "label": "conflict"},
        ]))

    def test_missing_answer_id_is_rejected(self):
        with self.assertRaises(ContractError):
            validate_answer_ids(make_request(questions={"relevant": {}, "usable": {}}),
                                make_result())

    def test_unknown_answer_id_is_rejected(self):
        with self.assertRaises(ContractError):
            validate_answer_ids(make_request(), make_result(
                answers={"relevant": {"type": "noul", "noul": 0.5}, "surprise": {"type": "noul", "noul": 0.5}},
            ))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: 运行测试确认失败**

Run: `python plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/test_decision_contract.py`
Expected: FAIL —— `ModuleNotFoundError: No module named 'decision_contract'`

- [ ] **Step 4: 实现 `decision_contract.py`**

创建 `plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/decision_contract.py`：

```python
"""Shared Jev decision-layer contracts: request, result, context, and policy."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

REQUEST_SCHEMA = "pb-jev-request-v1"
RESULT_SCHEMA = "pb-jev-result-v1"
TRACE_SCHEMA = "pb-decision-trace-v1"
CONTEXT_SCHEMA = "pb-decision-context-v1"
POLICY_SCHEMA = "pb-jev-policy-v1"

OPERATIONS = ("knowledge_relevance", "text_quality_prefilter")
PRIMITIVES = ("noul", "choice", "score")

# Phase 1 emits no routes (routing tables arrive with the Phase 2/3 operation
# policies), but the vocabulary is fixed here so the result contract is
# complete. A route describes one item — a knowledge chunk, a page, or a red
# line — not one question, because a single route can depend on several answers.
ROUTE_VALUES = ("include", "exclude_soft", "screened_clear", "escalate_llm", "needs_user_choice")

RESULT_STATUSES = (
    "succeeded",
    "failed",
    "waiting_for_jev_key",
    "waiting_for_jev_access",
    "outcome_unknown",
)
WAITING_STATUSES = ("waiting_for_jev_key", "waiting_for_jev_access")

CREDENTIAL_STATUSES = (
    "unchecked",
    "available",
    "waiting_for_jev_key",
    "waiting_for_jev_access",
)
EXECUTION_MODES = ("llm", "jev_assisted")

MOVING_MODEL_ALIASES = ("jev-latest", "jev-preview")

# A single operation may need more than one request (a batch of items). The
# optional operation_instance keeps each batch's operation directory, lease,
# pending call, and result distinct.
_INSTANCE_RE = re.compile(r"[A-Za-z0-9_-]+")

# Mirrors scripts/package_check.py so both credential sweeps agree on what a
# credential-shaped field name looks like. Suffix matching keeps the token
# counters (input_tokens / output_tokens) out of the net.
_CREDENTIAL_SUFFIXES = ("api_key", "apikey", "authorization", "password", "secret", "token")


class ContractError(ValueError):
    """A request, result, context, or policy payload violated the contract."""


def _require_object(payload: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise ContractError(f"{label} must be a JSON object")
    return payload


def _require_nonempty_str(payload: Mapping[str, Any], key: str, label: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{label}.{key} must be a non-empty string")
    return value


def _require_finite_number(payload: Mapping[str, Any], key: str, label: str) -> float:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{label}.{key} must be a number")
    if not math.isfinite(float(value)):
        raise ContractError(f"{label}.{key} must be a finite number")
    return float(value)


def _require_probability(payload: Mapping[str, Any], key: str, label: str) -> float:
    value = _require_finite_number(payload, key, label)
    if not 0.0 <= value <= 1.0:
        raise ContractError(f"{label}.{key} must be between 0 and 1")
    return value


def _validate_probability_map(value: Any, label: str) -> None:
    if not isinstance(value, Mapping) or not value:
        raise ContractError(f"{label}.probabilities must be a non-empty object")
    total = 0.0
    for key, probability in value.items():
        if not isinstance(key, str) or not key.strip():
            raise ContractError(f"{label}.probabilities keys must be non-empty strings")
        total += _require_probability(
            {key: probability}, key, f"{label}.probabilities"
        )
    if abs(total - 1.0) > 1e-6:
        raise ContractError(f"{label}.probabilities must sum to 1 (got {total})")


def assert_no_credential_fields(payload: Any, label: str = "payload") -> None:
    """Reject any field whose name looks like a credential carrier."""

    if isinstance(payload, Mapping):
        for key, child in payload.items():
            key_name = str(key).lower()
            if key_name.endswith(_CREDENTIAL_SUFFIXES):
                raise ContractError(f"{label}.{key} is a credential-shaped field")
            assert_no_credential_fields(child, f"{label}.{key}")
    elif isinstance(payload, (list, tuple)):
        for index, child in enumerate(payload):
            assert_no_credential_fields(child, f"{label}[{index}]")


def _validate_context_ref(ref: Any, label: str) -> None:
    ref = _require_object(ref, label)
    _require_nonempty_str(ref, "ref_id", label)
    _require_nonempty_str(ref, "kind", label)
    revisions = ref.get("revisions")
    if not isinstance(revisions, Mapping) or not revisions:
        raise ContractError(f"{label}.revisions must be a non-empty object")
    for key, value in revisions.items():
        if not isinstance(key, str) or not key.strip():
            raise ContractError(f"{label}.revisions keys must be non-empty strings")
        if not isinstance(value, str) or not value.strip():
            raise ContractError(f"{label}.revisions values must be non-empty strings")


def _validate_question(question_id: Any, question: Any) -> None:
    if not isinstance(question_id, str) or not question_id.strip():
        raise ContractError("request.questions keys must be non-empty strings")
    label = f"question {question_id!r}"
    question = _require_object(question, label)
    primitive = question.get("type")
    if primitive not in PRIMITIVES:
        raise ContractError(f"{label}.type must be one of {PRIMITIVES}")
    instructions = question.get("instructions")
    if isinstance(instructions, str):
        if not instructions.strip():
            raise ContractError(f"{label}.instructions must be non-empty")
    elif not isinstance(instructions, (Mapping, list)):
        raise ContractError(f"{label}.instructions must be a string, object, or array")
    criteria = question.get("criteria")
    if primitive == "choice":
        if not isinstance(criteria, Mapping) or not criteria:
            raise ContractError(f"{label} is a choice and needs non-empty object criteria")
    elif primitive == "score":
        if not isinstance(criteria, list) or len(criteria) < 2:
            raise ContractError(f"{label} is a score and needs at least two level descriptions")
        if len(criteria) > 10:
            raise ContractError(f"{label} is a score and accepts at most ten level descriptions")


def validate_request(payload: Any) -> None:
    payload = _require_object(payload, "request")
    if payload.get("schema_version") != REQUEST_SCHEMA:
        raise ContractError(f"request.schema_version must be {REQUEST_SCHEMA!r}")
    _require_nonempty_str(payload, "run_id", "request")
    operation = _require_nonempty_str(payload, "operation", "request")
    if operation not in OPERATIONS:
        raise ContractError(f"request.operation is not supported yet: {operation}")
    model = _require_nonempty_str(payload, "model", "request")
    if model in MOVING_MODEL_ALIASES:
        raise ContractError("request.model must be a pinned version id, not a moving alias")
    _require_nonempty_str(payload, "policy_version", "request")
    state = payload.get("state")
    if not isinstance(state, (str, Mapping, list)):
        raise ContractError("request.state must be a string, object, or array")
    questions = payload.get("questions")
    if not isinstance(questions, Mapping) or not questions:
        raise ContractError("request.questions must be a non-empty object")
    for question_id, question in questions.items():
        _validate_question(question_id, question)
    refs = payload.get("context_refs")
    if not isinstance(refs, list) or not refs:
        raise ContractError("request.context_refs must be a non-empty array")
    for index, ref in enumerate(refs):
        _validate_context_ref(ref, f"request.context_refs[{index}]")
    _require_nonempty_str(payload, "benchmark_case_id", "request")
    if "operation_instance" in payload:
        instance = payload["operation_instance"]
        if not isinstance(instance, str) or not _INSTANCE_RE.fullmatch(instance):
            raise ContractError(
                "request.operation_instance must match [A-Za-z0-9_-]+ when present"
            )
    assert_no_credential_fields(payload, "request")


def _validate_answer(question_id: str, answer: Any) -> None:
    label = f"result.answers[{question_id!r}]"
    answer = _require_object(answer, label)
    primitive = answer.get("type")
    if primitive not in PRIMITIVES:
        raise ContractError(f"{label}.type must be one of {PRIMITIVES}")
    if primitive == "noul":
        _require_probability(answer, "noul", label)
        return
    if primitive == "choice":
        choice = _require_nonempty_str(answer, "choice", label)
        probabilities = answer.get("probabilities")
        _validate_probability_map(probabilities, label)
        if choice not in probabilities:
            raise ContractError(f"{label}.choice must be one of its probabilities")
        _require_probability(answer, "confidence", label)
        return
    _require_finite_number(answer, "score", label)
    _validate_probability_map(answer.get("probabilities"), label)
    legend = answer.get("legend")
    if not isinstance(legend, Mapping) or not legend:
        raise ContractError(f"{label}.legend must be a non-empty object")
    _require_probability(answer, "confidence", label)


def _validate_usage(usage: Any) -> None:
    if not isinstance(usage, Mapping):
        raise ContractError("result.usage must be an object")
    for key in ("input_tokens", "output_tokens"):
        value = usage.get(key)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ContractError(f"result.usage.{key} must be null or a non-negative integer")


def _validate_routes(routes: Any) -> None:
    """Routes are per *item* (a knowledge chunk, a page, a red line), not per question.

    One item's route is computed by the operation's routing rules from that
    item's full answer set, so a single route can depend on several questions.
    """

    if not isinstance(routes, list):
        raise ContractError("result.routes must be an array")
    for index, route in enumerate(routes):
        label = f"result.routes[{index}]"
        route = _require_object(route, label)
        _require_nonempty_str(route, "item_id", label)
        value = _require_nonempty_str(route, "route", label)
        if value not in ROUTE_VALUES:
            raise ContractError(f"{label}.route must be one of {ROUTE_VALUES}")
        if "label" in route:
            _require_nonempty_str(route, "label", label)


def validate_result(payload: Any) -> None:
    payload = _require_object(payload, "result")
    if payload.get("schema_version") != RESULT_SCHEMA:
        raise ContractError(f"result.schema_version must be {RESULT_SCHEMA!r}")
    _require_nonempty_str(payload, "run_id", "result")
    operation = _require_nonempty_str(payload, "operation", "result")
    if operation not in OPERATIONS:
        raise ContractError(f"result.operation is not supported yet: {operation}")
    if payload.get("provider") != "typesafe":
        raise ContractError("result.provider must be 'typesafe'")
    _require_nonempty_str(payload, "requested_model", "result")
    _require_nonempty_str(payload, "policy_version", "result")
    status = payload.get("status")
    if status not in RESULT_STATUSES:
        raise ContractError(f"result.status must be one of {RESULT_STATUSES}")

    resolved_model = payload.get("resolved_model")
    if status == "succeeded":
        if not isinstance(resolved_model, str) or not resolved_model.strip():
            raise ContractError("a succeeded result must report a resolved_model")
        answers = payload.get("answers")
        if not isinstance(answers, Mapping) or not answers:
            raise ContractError("a succeeded result must carry answers")
        for question_id, answer in answers.items():
            _validate_answer(str(question_id), answer)
    else:
        if resolved_model is not None and (
            not isinstance(resolved_model, str) or not resolved_model.strip()
        ):
            raise ContractError("result.resolved_model must be null or a non-empty string")
        if payload.get("answers"):
            raise ContractError("a non-succeeded result must not carry answers")

    routes = payload.get("routes")
    _validate_routes(routes)
    if status != "succeeded" and routes:
        raise ContractError("a non-succeeded result must not carry routes")
    if status in WAITING_STATUSES and payload.get("trace"):
        raise ContractError("a waiting result must not carry a trace")
    if not isinstance(payload.get("trace"), Mapping):
        raise ContractError("result.trace must be an object")
    _validate_usage(payload.get("usage"))
    assert_no_credential_fields(payload, "result")


def validate_answer_ids(request: Any, result: Any) -> None:
    """Reject a response whose answer ids differ from the submitted questions."""

    expected = set(request["questions"])
    actual = set(result.get("answers") or {})
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing:
        raise ContractError(f"result is missing answers for: {missing}")
    if unknown:
        raise ContractError(f"result carries answers for unknown questions: {unknown}")
```

- [ ] **Step 5: 运行测试确认通过**

Run: `python plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/test_decision_contract.py`
Expected: PASS（全部测试通过）

- [ ] **Step 6: 登记新 skill 到插件契约**

编辑 `plugins/picturebook-screenwriter/config/plugin-contract.json`：在 `skills` 数组末尾（`"session-export"` 之后）加入 `"jev-decision-runtime"`，并在顶层新增 `jev_runtime` 块：

```json
  "jev_runtime": {
    "skill": "jev-decision-runtime",
    "endpoint": "https://api.typesafe.ai/v1/systemone",
    "credential_env": "TYPESAFE_API_KEY",
    "credential_sources": [
      "environment"
    ],
    "key_logging": "forbidden",
    "pinned_model": "jev-1.13.0",
    "moving_model_aliases": "forbidden",
    "base_url_override": "forbidden",
    "redirects": "disabled",
    "operations": [
      "knowledge_relevance",
      "text_quality_prefilter"
    ],
    "routing_source": "operation_policy"
  },
```

`routing_source: "operation_policy"` 记录 Phase 1 输出空 `routes`、路由表由 operation policy 提供这一事实（Phase 2/3 填充），不要把它写成已实现的路由。

- [ ] **Step 7: 运行聚合校验**

Run: `python scripts/run_plugin_tests.py`
Expected: PASS —— `OK: N offline commands passed`。新增的 `test_decision_contract.py` 会被自动发现；`governance_check.py` 因契约已同步而通过。

- [ ] **Step 8: 提交**

```bash
git add plugins/picturebook-screenwriter/skills/jev-decision-runtime plugins/picturebook-screenwriter/config/plugin-contract.json
git commit -m "feat(jev): add shared decision runtime scaffold and request/result contract" -m "Introduce the jev-decision-runtime utility skill and validate the pb-jev-request-v1 / pb-jev-result-v1 contract, including routing vocabulary and credential-shaped field rejection." -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: 策略文件与策略加载

固定模型版本、价格快照、校准状态与每 operation 的 `policy_version` / `fallback_route`。Phase 2/3 会向同一文件追加 `question_templates` 与 `routing` 表。

**Files:**
- Create: `plugins/picturebook-screenwriter/skills/jev-decision-runtime/references/decision-policies.json`
- Modify: `plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/decision_contract.py`
- Modify: `plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/test_decision_contract.py`

**Interfaces:**
- Consumes: Task 1 的 `ContractError`、`OPERATIONS`、`POLICY_SCHEMA`、`MOVING_MODEL_ALIASES`、`ROUTE_VALUES`
- Produces:
  - `decision_contract.POLICY_STATUSES = ("experimental", "calibrated")`
  - `decision_contract.validate_policy(payload) -> None`
  - `decision_contract.load_policy(path) -> dict`
  - `decision_contract.operation_policy(policy, operation) -> dict` —— 返回该 operation 的 policy 分支（含 `policy_version`、`calibration_status`、`fallback_route`、`routing`）
  - `decision_contract.default_policy_path() -> pathlib.Path`

- [ ] **Step 1: 写失败测试**

在 `test_decision_contract.py` 的 import 块中补充：

```python
from decision_contract import (
    POLICY_SCHEMA,
    default_policy_path,
    load_policy,
    operation_policy,
    validate_policy,
)
```

在文件末尾（`if __name__ == "__main__":` 之前）追加：

```python
def make_policy(**overrides):
    policy = {
        "schema_version": POLICY_SCHEMA,
        "pinned_model": "jev-1.13.0",
        "output_tokens_free": True,
        "price_snapshot": {
            "price_usd_per_million_input_tokens": "0.042",
            "snapshot_date": "2026-09-23",
        },
        "operations": {
            "knowledge_relevance": {
                "policy_version": "knowledge-relevance-v1",
                "calibration_status": "experimental",
                "fallback_route": "escalate_llm",
                "routing": {},
            },
            "text_quality_prefilter": {
                "policy_version": "text-quality-prefilter-v1",
                "calibration_status": "experimental",
                "fallback_route": "escalate_llm",
                "routing": {},
            },
        },
    }
    policy.update(overrides)
    return policy


class PolicyContractTests(unittest.TestCase):
    def test_valid_policy_is_accepted(self):
        validate_policy(make_policy())

    def test_moving_model_alias_is_rejected(self):
        with self.assertRaises(ContractError):
            validate_policy(make_policy(pinned_model="jev-latest"))

    def test_unknown_calibration_status_is_rejected(self):
        policy = make_policy()
        policy["operations"]["knowledge_relevance"]["calibration_status"] = "probably_fine"
        with self.assertRaises(ContractError):
            validate_policy(policy)

    def test_every_supported_operation_needs_a_policy_entry(self):
        policy = make_policy()
        del policy["operations"]["text_quality_prefilter"]
        with self.assertRaises(ContractError):
            validate_policy(policy)

    def test_price_snapshot_must_be_decimal_string_and_date(self):
        with self.assertRaises(ContractError):
            validate_policy(make_policy(price_snapshot={
                "price_usd_per_million_input_tokens": 0.042,
                "snapshot_date": "2026-09-23",
            }))
        with self.assertRaises(ContractError):
            validate_policy(make_policy(price_snapshot={
                "price_usd_per_million_input_tokens": "0.042",
                "snapshot_date": "",
            }))

    def test_unknown_route_value_is_rejected(self):
        policy = make_policy()
        policy["operations"]["knowledge_relevance"]["fallback_route"] = "hope_for_the_best"
        with self.assertRaises(ContractError):
            validate_policy(policy)

    def test_routing_rules_are_refused_until_the_operation_defines_them(self):
        # Phase 1 has no operation questions, so it cannot express a routing
        # rule yet. Shipping an empty table is required, not optional.
        policy = make_policy()
        policy["operations"]["knowledge_relevance"]["routing"] = {
            "relevant": {"clear_route": "exclude_soft"}
        }
        with self.assertRaises(ContractError):
            validate_policy(policy)

    def test_shipped_policy_file_is_valid_and_pins_a_version(self):
        policy = load_policy(default_policy_path())
        self.assertEqual(policy["pinned_model"], "jev-1.13.0")
        self.assertEqual(policy["operations"]["knowledge_relevance"]["calibration_status"],
                         "experimental")

    def test_operation_policy_reads_the_matching_branch(self):
        policy = load_policy(default_policy_path())
        entry = operation_policy(policy, "text_quality_prefilter")
        self.assertEqual(entry["policy_version"], "text-quality-prefilter-v1")

    def test_operation_policy_rejects_an_unknown_operation(self):
        with self.assertRaises(ContractError):
            operation_policy(make_policy(), "write_the_story")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/test_decision_contract.py`
Expected: FAIL —— `ImportError: cannot import name 'default_policy_path'`

- [ ] **Step 3: 实现策略校验与加载**

在 `decision_contract.py` 末尾追加：

```python
POLICY_STATUSES = ("experimental", "calibrated")
_DECIMAL_STRING = re.compile(r"^\d+(\.\d+)?$")


def _require_decimal_string(payload: Mapping[str, Any], key: str, label: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not _DECIMAL_STRING.fullmatch(value):
        raise ContractError(f"{label}.{key} must be a plain decimal string")
    return value


def _validate_routing_table(routing: Any, label: str) -> None:
    """Phase 1 ships no routing rules.

    The per-operation routing schema (question bands, match rules, labels) is
    designed together with each operation's questions in Phase 2 and Phase 3,
    because a routing rule cannot be expressed without knowing which questions
    exist and which direction of each probability means risk. Phase 1 therefore
    requires only that the table is a table.
    """

    if not isinstance(routing, Mapping):
        raise ContractError(f"{label}.routing must be an object")
    if routing:
        raise ContractError(
            f"{label}.routing must be empty until the operation's routing schema "
            "is defined"
        )


def validate_policy(payload: Any) -> None:
    payload = _require_object(payload, "policy")
    if payload.get("schema_version") != POLICY_SCHEMA:
        raise ContractError(f"policy.schema_version must be {POLICY_SCHEMA!r}")
    model = _require_nonempty_str(payload, "pinned_model", "policy")
    if model in MOVING_MODEL_ALIASES:
        raise ContractError("policy.pinned_model must be a pinned version id, not a moving alias")
    if payload.get("output_tokens_free") is not True:
        raise ContractError("policy.output_tokens_free must be true")
    snapshot = _require_object(payload.get("price_snapshot"), "policy.price_snapshot")
    _require_decimal_string(
        snapshot, "price_usd_per_million_input_tokens", "policy.price_snapshot"
    )
    _require_nonempty_str(snapshot, "snapshot_date", "policy.price_snapshot")

    operations = payload.get("operations")
    if not isinstance(operations, Mapping):
        raise ContractError("policy.operations must be an object")
    for operation in OPERATIONS:
        if operation not in operations:
            raise ContractError(f"policy.operations is missing the {operation!r} entry")
    for operation, entry in operations.items():
        label = f"policy.operations[{operation!r}]"
        if operation not in OPERATIONS:
            raise ContractError(f"{label} is not a supported operation")
        entry = _require_object(entry, label)
        _require_nonempty_str(entry, "policy_version", label)
        status = _require_nonempty_str(entry, "calibration_status", label)
        if status not in POLICY_STATUSES:
            raise ContractError(f"{label}.calibration_status must be one of {POLICY_STATUSES}")
        fallback = _require_nonempty_str(entry, "fallback_route", label)
        if fallback not in ROUTE_VALUES:
            raise ContractError(f"{label}.fallback_route must be one of {ROUTE_VALUES}")
        _validate_routing_table(entry.get("routing"), label)


def default_policy_path() -> Path:
    """Return the policy file that ships with this skill."""

    return Path(__file__).resolve().parents[1] / "references" / "decision-policies.json"


def load_policy(path: Any) -> dict:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ContractError(f"unable to read policy file: {error}") from error
    validate_policy(payload)
    return payload


def operation_policy(policy: Mapping[str, Any], operation: str) -> dict:
    if operation not in OPERATIONS:
        raise ContractError(f"operation is not supported yet: {operation}")
    entry = (policy.get("operations") or {}).get(operation)
    if not isinstance(entry, Mapping):
        raise ContractError(f"policy has no entry for operation {operation!r}")
    return dict(entry)
```

- [ ] **Step 4: 运行测试，确认只剩策略文件相关的两个失败**

Run: `python plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/test_decision_contract.py`
Expected: FAIL —— 只剩 `test_shipped_policy_file_is_valid_and_pins_a_version` 与 `test_operation_policy_reads_the_matching_branch`，因为 `references/decision-policies.json` 还不存在。策略校验的其余测试此时必须已经通过；出现别的失败就先修实现，再进入 Step 5。

- [ ] **Step 5: 写策略文件**

创建 `plugins/picturebook-screenwriter/skills/jev-decision-runtime/references/decision-policies.json`：

```json
{
  "schema_version": "pb-jev-policy-v1",
  "pinned_model": "jev-1.13.0",
  "output_tokens_free": true,
  "price_snapshot": {
    "price_usd_per_million_input_tokens": "0.042",
    "snapshot_date": "2026-09-23"
  },
  "operations": {
    "knowledge_relevance": {
      "policy_version": "knowledge-relevance-v1",
      "calibration_status": "experimental",
      "fallback_route": "escalate_llm",
      "routing": {}
    },
    "text_quality_prefilter": {
      "policy_version": "text-quality-prefilter-v1",
      "calibration_status": "experimental",
      "fallback_route": "escalate_llm",
      "routing": {}
    }
  },
  "notes": [
    "question_templates 与 routing 表由 Phase 2/3 的 operation 策略填充。",
    "experimental 期间 screened_clear 不得缩减普通 LLM 复核范围。",
    "阈值必须由本项目的中文绘本样本校准后逐 operation 转为 calibrated。"
  ]
}
```

`notes` 是给人看的说明；`validate_policy` 只读取它认识的键，不校验 `notes`。

- [ ] **Step 6: 运行测试确认通过**

Run: `python plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/test_decision_contract.py`
Expected: PASS

- [ ] **Step 7: 提交**

```bash
git add plugins/picturebook-screenwriter/skills/jev-decision-runtime
git commit -m "feat(jev): pin model version, price snapshot, and per-operation policy" -m "Add decision-policies.json with experimental calibration status and load it through a validated policy contract so the runner never invents a threshold." -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: `decision_context` 契约与 Stage DAG 透传

建立 `pb-decision-context-v1`（含 `pending_call` 描述符与 `resume_cursor` 词表），并把它透传到 run manifest 与子 Agent task envelope。`stage_dag.py` 的校验器**容忍未知顶层字段**，因此这里的改动是向后兼容的——不要给 `validate_manifest` 增加"必须包含 decision_context"的硬校验，那会改写全部既有 v2 历史 manifest 的语义。

**Files:**
- Modify: `plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/decision_contract.py`
- Modify: `plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/test_decision_contract.py`
- Modify: `plugins/picturebook-screenwriter/scripts/stage_dag.py`
- Modify: `plugins/picturebook-screenwriter/scripts/stage_dag_codex.py`
- Modify: `plugins/picturebook-screenwriter/tests/test_stage_dag.py`

**Interfaces:**
- Consumes: Task 1 的 `CONTEXT_SCHEMA`、`CREDENTIAL_STATUSES`、`EXECUTION_MODES`、`OPERATIONS`
- Produces:
  - `decision_contract.SELECTION_STATUSES = ("confirmed",)`
  - `decision_contract.ATTEMPT_STATUSES = ("pending", "in_flight", "failed", "outcome_unknown")`
  - `decision_contract.INITIAL_RESUME_CURSOR = "after_execution_choice"`
  - `decision_contract.OPERATION_CURSOR_PREFIX = "after_operation:"`
  - `decision_contract.operation_cursor(operation_id: str) -> str`
  - `decision_contract.validate_resume_cursor(value: str) -> None`
  - `decision_contract.validate_pending_call(payload) -> None`
  - `decision_contract.validate_decision_context(payload) -> None`
  - `decision_contract.build_decision_context(*, mode, external_text_processing_acknowledged, selected_at, resume_cursor=INITIAL_RESUME_CURSOR, credential_status="unchecked", pending_call=None) -> dict`
  - `stage_dag.DECISION_CONTEXT_SCHEMA = "pb-decision-context-v1"`
  - `stage_dag.build_revision_manifest(parent_run, feedback, artifact_ref, run_id, decision_context=None) -> dict`（新增第 5 个关键字参数）
  - `stage_dag_codex.format_task_envelope(manifest, stage) -> dict`（envelope 顶层新增可选 `decision_context`）

- [ ] **Step 1: 写失败测试**

在 `test_decision_contract.py` 的 import 块补充：

```python
from decision_contract import (
    ATTEMPT_STATUSES,
    CONTEXT_SCHEMA,
    build_decision_context,
    operation_cursor,
    validate_decision_context,
    validate_pending_call,
    validate_resume_cursor,
)
```

在文件末尾追加：

```python
def make_context(**overrides):
    context = build_decision_context(
        mode="jev_assisted",
        external_text_processing_acknowledged=True,
        selected_at="2026-09-23T10:30:00+08:00",
    )
    context.update(overrides)
    return context


def make_pending_call(**overrides):
    pending = {
        "operation_id": "20260923-example-0001-knowledge_relevance",
        "operation": "knowledge_relevance",
        "request_fingerprint": "sha256:" + "1" * 64,
        "policy_version": "knowledge-relevance-v1",
        "requested_model": "jev-1.13.0",
        "attempt_status": "pending",
        "input_refs": [
            {
                "ref_id": "海外绘本/小老鼠迈尔斯/worldview",
                "kind": "knowledge_page",
                "revisions": {"node-a": "17"},
            }
        ],
    }
    pending.update(overrides)
    return pending


class DecisionContextTests(unittest.TestCase):
    def test_context_defaults_to_the_initial_cursor(self):
        context = make_context()
        self.assertEqual(context["schema_version"], CONTEXT_SCHEMA)
        self.assertEqual(context["resume_cursor"], "after_execution_choice")
        self.assertEqual(context["credential_status"], "unchecked")
        self.assertIsNone(context["pending_call"])
        validate_decision_context(context)

    def test_unknown_mode_is_rejected(self):
        with self.assertRaises(ContractError):
            validate_decision_context(make_context(mode="jev_probably"))

    def test_unconfirmed_selection_is_rejected(self):
        with self.assertRaises(ContractError):
            validate_decision_context(make_context(selection_status="maybe"))

    def test_unknown_credential_status_is_rejected(self):
        with self.assertRaises(ContractError):
            validate_decision_context(make_context(credential_status="checking"))

    def test_context_accepts_a_pending_call(self):
        validate_decision_context(make_context(
            credential_status="waiting_for_jev_key",
            pending_call=make_pending_call(attempt_status="failed"),
        ))

    def test_context_carries_no_credential_shaped_field(self):
        with self.assertRaises(ContractError):
            validate_decision_context(make_context(api_key="sk-nope"))

    def test_resume_cursor_vocabulary(self):
        validate_resume_cursor("after_execution_choice")
        validate_resume_cursor(operation_cursor("20260923-example-0001-knowledge_relevance"))
        for bad in ("", "later", "after_operation:"):
            with self.subTest(bad=bad), self.assertRaises(ContractError):
                validate_resume_cursor(bad)

    def test_pending_call_attempt_status_vocabulary(self):
        for status in ATTEMPT_STATUSES:
            with self.subTest(status=status):
                validate_pending_call(make_pending_call(attempt_status=status))
        with self.assertRaises(ContractError):
            validate_pending_call(make_pending_call(attempt_status="probably"))

    def test_pending_call_needs_at_least_one_input_ref(self):
        with self.assertRaises(ContractError):
            validate_pending_call(make_pending_call(input_refs=[]))

    def test_pending_call_rejects_unknown_operation(self):
        with self.assertRaises(ContractError):
            validate_pending_call(make_pending_call(operation="write_the_story"))
```

在 `plugins/picturebook-screenwriter/tests/test_stage_dag.py` 末尾（`if __name__ == "__main__":` 之前）追加。**继承既有的 `StageDagRevisionTest`**，这样 `setUp` 会创建真实的 `project_root` 与可读的 `artifact_ref`——`build_revision_manifest` 要求父 run 已 `completed` 且 `outcome == "revision_requested"`，并要求 `artifact_ref` 是真实可读文件，这两项都由父类提供：

```python
class DecisionContextPropagationTest(StageDagRevisionTest):
    CONTEXT = {
        "schema_version": "pb-decision-context-v1",
        "mode": "jev_assisted",
        "selection_status": "confirmed",
        "credential_status": "available",
        "resume_cursor": "after_execution_choice",
        "pending_call": None,
        "selected_at": "2026-09-23T10:30:00+08:00",
        "external_text_processing_acknowledged": True,
    }
    FEEDBACK = [{"page": 5, "issue": "钩子偏弱", "instruction": "加强悬念"}]

    def test_schema_constant_is_published(self):
        self.assertEqual(stage_dag.DECISION_CONTEXT_SCHEMA, "pb-decision-context-v1")

    def test_revision_manifest_inherits_decision_context(self):
        revision = stage_dag.build_revision_manifest(
            self._revision_parent(),
            feedback=self.FEEDBACK,
            artifact_ref=self.artifact_ref,
            run_id="20260923-example-0002",
            decision_context=self.CONTEXT,
        )
        self.assertEqual(revision["decision_context"], self.CONTEXT)

    def test_revision_manifest_without_context_keeps_the_legacy_shape(self):
        revision = stage_dag.build_revision_manifest(
            self._revision_parent(),
            feedback=self.FEEDBACK,
            artifact_ref=self.artifact_ref,
            run_id="20260923-example-0002",
        )
        self.assertNotIn("decision_context", revision)

    def test_revision_manifest_copies_the_context_instead_of_aliasing_it(self):
        context = copy.deepcopy(self.CONTEXT)
        revision = stage_dag.build_revision_manifest(
            self._revision_parent(),
            feedback=self.FEEDBACK,
            artifact_ref=self.artifact_ref,
            run_id="20260923-example-0002",
            decision_context=context,
        )
        context["credential_status"] = "waiting_for_jev_key"
        self.assertEqual(revision["decision_context"]["credential_status"], "available")

    def test_manifest_validator_still_tolerates_the_new_field(self):
        manifest = stage_dag._creation_template_manifest()
        manifest["decision_context"] = dict(self.CONTEXT)
        self.assertEqual(
            stage_dag.validate_manifest(manifest)["decision_context"], self.CONTEXT
        )
```

`test_stage_dag.py` 已经 `import copy`、`os`、`tempfile`，不需要新增 import。

在 `plugins/picturebook-screenwriter/tests/test_stage_dag_codex.py` 末尾追加。`format_task_envelope` 要求 manifest 通过 `validate_manifest`，因此用既有的 `stage_dag._creation_template_manifest()` 模板（同一文件里 `test_format_task_envelope_validates` 就是这么做的），并取 `stages[1]`（`brief_gate`）作为被派发阶段：

```python
class TaskEnvelopeDecisionContextTests(unittest.TestCase):
    def _manifest_with_context(self):
        manifest = stage_dag._creation_template_manifest()
        manifest["decision_context"] = {
            "schema_version": "pb-decision-context-v1",
            "mode": "llm",
            "selection_status": "confirmed",
            "credential_status": "unchecked",
            "resume_cursor": "after_execution_choice",
            "pending_call": None,
            "selected_at": "2026-09-23T10:30:00+08:00",
            "external_text_processing_acknowledged": False,
        }
        return manifest

    def test_envelope_carries_the_manifest_decision_context(self):
        manifest = self._manifest_with_context()
        envelope = stage_dag_codex.format_task_envelope(
            manifest, manifest["stages"][1]
        )
        self.assertEqual(envelope["decision_context"], manifest["decision_context"])
        self.assertEqual(envelope["stage_id"], "brief_gate")
        self.assertEqual(stage_dag.validate_task(envelope, manifest), envelope)

    def test_envelope_omits_decision_context_when_absent(self):
        manifest = stage_dag._creation_template_manifest()
        envelope = stage_dag_codex.format_task_envelope(
            manifest, manifest["stages"][1]
        )
        self.assertNotIn("decision_context", envelope)

    def test_envelope_copies_the_context_instead_of_aliasing_it(self):
        manifest = self._manifest_with_context()
        envelope = stage_dag_codex.format_task_envelope(
            manifest, manifest["stages"][1]
        )
        manifest["decision_context"]["credential_status"] = "waiting_for_jev_key"
        self.assertEqual(envelope["decision_context"]["credential_status"], "unchecked")
```

`test_stage_dag_codex.py` 已 `import copy`、`json`、`tempfile`，并已导入 `stage_dag` 与 `stage_dag_codex`，不需要新增 import。

- [ ] **Step 2: 运行测试确认失败**

Run: `python plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/test_decision_contract.py`
Expected: FAIL —— `ImportError: cannot import name 'build_decision_context'`

Run: `python plugins/picturebook-screenwriter/tests/test_stage_dag.py`
Expected: FAIL —— `AttributeError: 'module' object has no attribute 'DECISION_CONTEXT_SCHEMA'` 或 `TypeError: build_revision_manifest() got an unexpected keyword argument 'decision_context'`

- [ ] **Step 3: 实现 `decision_context` 与 `pending_call` 契约**

在 `decision_contract.py` 末尾追加：

```python
SELECTION_STATUSES = ("confirmed",)
ATTEMPT_STATUSES = ("pending", "in_flight", "failed", "outcome_unknown")

INITIAL_RESUME_CURSOR = "after_execution_choice"
OPERATION_CURSOR_PREFIX = "after_operation:"


def operation_cursor(operation_id: str) -> str:
    return f"{OPERATION_CURSOR_PREFIX}{operation_id}"


def validate_resume_cursor(value: str) -> None:
    if value == INITIAL_RESUME_CURSOR:
        return
    if value.startswith(OPERATION_CURSOR_PREFIX) and len(value) > len(OPERATION_CURSOR_PREFIX):
        return
    raise ContractError(f"unknown decision_context.resume_cursor: {value!r}")


def validate_pending_call(payload: Any) -> None:
    payload = _require_object(payload, "pending_call")
    _require_nonempty_str(payload, "operation_id", "pending_call")
    operation = _require_nonempty_str(payload, "operation", "pending_call")
    if operation not in OPERATIONS:
        raise ContractError(f"pending_call.operation is not supported yet: {operation}")
    _require_nonempty_str(payload, "request_fingerprint", "pending_call")
    _require_nonempty_str(payload, "policy_version", "pending_call")
    _require_nonempty_str(payload, "requested_model", "pending_call")
    attempt_status = _require_nonempty_str(payload, "attempt_status", "pending_call")
    if attempt_status not in ATTEMPT_STATUSES:
        raise ContractError(f"pending_call.attempt_status must be one of {ATTEMPT_STATUSES}")
    refs = payload.get("input_refs")
    if not isinstance(refs, list) or not refs:
        raise ContractError("pending_call.input_refs must be a non-empty array")
    for index, ref in enumerate(refs):
        _validate_context_ref(ref, f"pending_call.input_refs[{index}]")
    assert_no_credential_fields(payload, "pending_call")


def validate_decision_context(payload: Any) -> None:
    payload = _require_object(payload, "decision_context")
    if payload.get("schema_version") != CONTEXT_SCHEMA:
        raise ContractError(f"decision_context.schema_version must be {CONTEXT_SCHEMA!r}")
    mode = payload.get("mode")
    if mode not in EXECUTION_MODES:
        raise ContractError(f"decision_context.mode must be one of {EXECUTION_MODES}")
    selection_status = payload.get("selection_status")
    if selection_status not in SELECTION_STATUSES:
        raise ContractError(
            f"decision_context.selection_status must be one of {SELECTION_STATUSES}"
        )
    credential_status = payload.get("credential_status")
    if credential_status not in CREDENTIAL_STATUSES:
        raise ContractError(
            f"decision_context.credential_status must be one of {CREDENTIAL_STATUSES}"
        )
    validate_resume_cursor(_require_nonempty_str(payload, "resume_cursor", "decision_context"))
    _require_nonempty_str(payload, "selected_at", "decision_context")
    if not isinstance(payload.get("external_text_processing_acknowledged"), bool):
        raise ContractError(
            "decision_context.external_text_processing_acknowledged must be a boolean"
        )
    pending_call = payload.get("pending_call")
    if pending_call is not None:
        validate_pending_call(pending_call)
    assert_no_credential_fields(payload, "decision_context")


def build_decision_context(
    *,
    mode: str,
    external_text_processing_acknowledged: bool,
    selected_at: str,
    resume_cursor: str = INITIAL_RESUME_CURSOR,
    credential_status: str = "unchecked",
    pending_call: Any = None,
) -> dict:
    context = {
        "schema_version": CONTEXT_SCHEMA,
        "mode": mode,
        "selection_status": "confirmed",
        "credential_status": credential_status,
        "resume_cursor": resume_cursor,
        "pending_call": pending_call,
        "selected_at": selected_at,
        "external_text_processing_acknowledged": bool(external_text_processing_acknowledged),
    }
    validate_decision_context(context)
    return context
```

- [ ] **Step 4: 在 `stage_dag.py` 中加常量与参数**

在 `stage_dag.py` 的 schema 常量区（`RESULT_SCHEMA = "pb-stage-result-v1"` 之后）加入：

```python
# Attached to a run manifest by the entry skill's execution choice gate. The
# validator tolerates it as an ordinary extra field, so v2 manifests written
# before the gate existed stay readable.
DECISION_CONTEXT_SCHEMA = "pb-decision-context-v1"
```

把 `build_revision_manifest` 的签名与实现改为（保留原有必填参数顺序，只在末尾追加关键字参数）：

```python
def build_revision_manifest(
    parent_run,
    feedback,
    artifact_ref,
    run_id,
    decision_context=None,
):
```

在函数体内，构造完 `manifest` 之后、`return` 之前加入：

```python
    if decision_context is not None:
        manifest["decision_context"] = copy.deepcopy(decision_context)
```

该函数已经 `import copy`（同一模块内已使用 `copy.deepcopy`）。不要改动它的任何既有校验。

- [ ] **Step 5: 在 `stage_dag_codex.py` 中透传**

在 `format_task_envelope` 内，`task = {...}` 字典构造完成之后、调用 `stage_dag.validate_task(task, manifest)` 之前加入：

```python
    decision_context = validated.get("decision_context")
    if decision_context is not None:
        task["decision_context"] = copy.deepcopy(decision_context)
```

`stage_dag_codex.py` 已 `import copy`（`format_task_envelope` 内已使用 `copy.deepcopy(validated["revision_feedback"])`）。`validate_task` 容忍未知键，因此不需要改校验器。

- [ ] **Step 6: 运行测试确认通过**

Run: `python plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/test_decision_contract.py`
Expected: PASS

Run: `python plugins/picturebook-screenwriter/tests/test_stage_dag.py`
Expected: PASS

Run: `python plugins/picturebook-screenwriter/tests/test_stage_dag_codex.py`
Expected: PASS

- [ ] **Step 7: 运行聚合校验**

Run: `python scripts/run_plugin_tests.py`
Expected: PASS

- [ ] **Step 8: 提交**

```bash
git add plugins/picturebook-screenwriter/skills/jev-decision-runtime plugins/picturebook-screenwriter/scripts/stage_dag.py plugins/picturebook-screenwriter/scripts/stage_dag_codex.py plugins/picturebook-screenwriter/tests/test_stage_dag.py plugins/picturebook-screenwriter/tests/test_stage_dag_codex.py
git commit -m "feat(jev): add decision context contract and propagate it through the stage DAG" -m "The execution choice travels as a backward-compatible decision_context object on the run manifest and on the subagent task envelope; revision runs inherit the root run's selection." -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 4: 计量——benchmark case id、计时、usage 与 Decimal 成本

spec §10 要求两支路径可用同一个 `benchmark_case_id` 并排比较，并且成本必须是十进制定点、缺失 usage 时不得伪造 token。

**Files:**
- Create: `plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/telemetry.py`
- Create: `plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/test_telemetry.py`

**Interfaces:**
- Consumes: Task 1 的 `TRACE_SCHEMA`
- Produces:
  - `telemetry.canonical_json(payload) -> str`
  - `telemetry.sha256_hex(text) -> str`
  - `telemetry.request_fingerprint(request) -> str`（忽略 `benchmark_case_id`，因为它是派生值）
  - `telemetry.benchmark_case_id(normalized_input, policy_version, rule_version) -> str`
  - `telemetry.estimate_cost_usd(input_tokens, price_usd_per_million_input_tokens) -> str`
  - `telemetry.estimate_usage(usage, price_usd_per_million_input_tokens) -> tuple[int | None, int | None, str | None]`
  - `telemetry.Stopwatch(clock=time.monotonic)`，含 `start()`、`stop()`、`elapsed_ms`
  - `telemetry.now_iso() -> str`
  - `telemetry.DecisionTrace`（frozen dataclass，字段见下）与 `DecisionTrace.to_dict()`

- [ ] **Step 1: 写失败测试**

创建 `plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/test_telemetry.py`：

```python
import unittest

from telemetry import (
    DecisionTrace,
    Stopwatch,
    benchmark_case_id,
    estimate_cost_usd,
    estimate_usage,
    request_fingerprint,
)


class FakeClock:
    def __init__(self, *ticks):
        self._ticks = list(ticks)

    def __call__(self):
        return self._ticks.pop(0)


class BenchmarkCaseIdTests(unittest.TestCase):
    def test_same_inputs_produce_the_same_id(self):
        first = benchmark_case_id({"pages": 32}, "knowledge-relevance-v1", "rules-v1")
        second = benchmark_case_id({"pages": 32}, "knowledge-relevance-v1", "rules-v1")
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("sha256:"))

    def test_key_order_does_not_change_the_id(self):
        first = benchmark_case_id({"a": 1, "b": 2}, "p", "r")
        second = benchmark_case_id({"b": 2, "a": 1}, "p", "r")
        self.assertEqual(first, second)

    def test_changing_the_input_changes_the_id(self):
        self.assertNotEqual(
            benchmark_case_id({"pages": 32}, "p", "r"),
            benchmark_case_id({"pages": 33}, "p", "r"),
        )

    def test_changing_the_policy_version_changes_the_id(self):
        self.assertNotEqual(
            benchmark_case_id({"pages": 32}, "p1", "r"),
            benchmark_case_id({"pages": 32}, "p2", "r"),
        )


class RequestFingerprintTests(unittest.TestCase):
    def test_bookkeeping_fields_are_excluded(self):
        base = {"run_id": "r1", "state": "x"}
        with_id = dict(base, benchmark_case_id="sha256:" + "0" * 64)
        self.assertEqual(request_fingerprint(base), request_fingerprint(with_id))

    def test_changing_the_state_changes_the_fingerprint(self):
        self.assertNotEqual(
            request_fingerprint({"run_id": "r1", "state": "x"}),
            request_fingerprint({"run_id": "r1", "state": "y"}),
        )


class CostTests(unittest.TestCase):
    def test_cost_matches_the_spec_example(self):
        self.assertEqual(estimate_cost_usd(8200, "0.042"), "0.000344400000")

    def test_cost_is_decimal_not_binary_float(self):
        # 0.042 cannot be represented exactly in binary floating point.
        self.assertEqual(estimate_cost_usd(1, "0.042"), "0.000000042000")

    def test_cost_of_zero_tokens_is_zero(self):
        self.assertEqual(estimate_cost_usd(0, "0.042"), "0.000000000000")

    def test_estimate_usage_returns_nulls_when_usage_is_missing(self):
        self.assertEqual(estimate_usage(None, "0.042"), (None, None, None))
        self.assertEqual(estimate_usage({}, "0.042"), (None, None, None))

    def test_estimate_usage_keeps_cost_when_output_tokens_are_missing(self):
        input_tokens, output_tokens, cost = estimate_usage({"input_tokens": 8200}, "0.042")
        self.assertEqual(input_tokens, 8200)
        self.assertIsNone(output_tokens)
        self.assertEqual(cost, "0.000344400000")

    def test_boolean_token_counts_are_not_accepted_as_integers(self):
        self.assertEqual(estimate_usage({"input_tokens": True}, "0.042"), (None, None, None))


class StopwatchTests(unittest.TestCase):
    def test_elapsed_milliseconds_use_the_injected_clock(self):
        stopwatch = Stopwatch(FakeClock(10.0, 10.412))
        stopwatch.start()
        stopwatch.stop()
        self.assertEqual(stopwatch.elapsed_ms, 412)


class TraceTests(unittest.TestCase):
    def make_trace(self, **overrides):
        payload = {
            "run_id": "20260923-example-0001",
            "benchmark_case_id": "sha256:" + "0" * 64,
            "execution_mode": "jev_assisted",
            "operation": "text_quality_prefilter",
            "started_at": "2026-09-23T10:30:00.000+08:00",
            "finished_at": "2026-09-23T10:30:00.412+08:00",
            "elapsed_ms": 412,
            "input_sha256": "a" * 64,
            "item_count": 32,
            "question_count": 160,
            "screened_clear_count": 0,
            "escalated_count": 0,
            "request_count": 4,
            "input_tokens": 8200,
            "output_tokens": 640,
            "estimated_cost_usd": "0.000344400000",
            "price_usd_per_million_input_tokens": "0.042",
            "price_snapshot_date": "2026-09-23",
            "resolved_model": "jev-1.13.0",
            "status": "succeeded",
            "fallback_used": False,
            "error_class": None,
        }
        payload.update(overrides)
        return DecisionTrace(**payload)

    def test_trace_serializes_to_the_spec_key_set(self):
        serialized = self.make_trace().to_dict()
        self.assertEqual(serialized["schema_version"], "pb-decision-trace-v1")
        self.assertEqual(
            set(serialized),
            {
                "schema_version", "run_id", "benchmark_case_id", "execution_mode",
                "operation", "started_at", "finished_at", "elapsed_ms", "input_sha256",
                "item_count", "question_count", "screened_clear_count", "escalated_count",
                "request_count", "input_tokens", "output_tokens", "estimated_cost_usd",
                "price_usd_per_million_input_tokens", "price_snapshot_date",
                "resolved_model", "status", "fallback_used", "error_class",
            },
        )

    def test_trace_never_carries_draft_text(self):
        marker = "小红帽把蛋糕递给了奶奶"
        serialized = self.make_trace(input_sha256="a" * 64).to_dict()
        self.assertNotIn(marker, repr(serialized))

    def test_fallback_is_false_unless_the_path_actually_switched(self):
        self.assertFalse(self.make_trace().to_dict()["fallback_used"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/test_telemetry.py`
Expected: FAIL —— `ModuleNotFoundError: No module named 'telemetry'`

- [ ] **Step 3: 实现 `telemetry.py`**

创建 `plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/telemetry.py`：

```python
"""Timing, usage, cost, and benchmark-case identity for Jev decisions."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from decision_contract import TRACE_SCHEMA

# Prices are billed per input token; output tokens are free. Keep the
# arithmetic in Decimal so a report never disagrees with the invoice.
_COST_QUANTUM = Decimal("1E-12")
_TOKENS_PER_MILLION = Decimal(1_000_000)
_CN_TZ = timezone(timedelta(hours=8))


def now_iso() -> str:
    return datetime.now(_CN_TZ).isoformat(timespec="milliseconds")


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def request_fingerprint(request: Mapping[str, Any]) -> str:
    """Stable identity of a request; benchmark_case_id is derived, not identity."""

    stable = {key: value for key, value in request.items() if key != "benchmark_case_id"}
    return "sha256:" + sha256_hex(canonical_json(stable))


def benchmark_case_id(normalized_input: Any, policy_version: str, rule_version: str) -> str:
    payload = {
        "input": normalized_input,
        "policy_version": policy_version,
        "rule_version": rule_version,
    }
    return "sha256:" + sha256_hex(canonical_json(payload))


def _is_token_count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def estimate_cost_usd(input_tokens: int, price_usd_per_million_input_tokens: str) -> str:
    price = Decimal(price_usd_per_million_input_tokens)
    cost = (Decimal(int(input_tokens)) * price / _TOKENS_PER_MILLION).quantize(
        _COST_QUANTUM, rounding=ROUND_HALF_UP
    )
    return str(cost)


def estimate_usage(
    usage: Any, price_usd_per_million_input_tokens: str
) -> tuple[int | None, int | None, str | None]:
    """Return (input_tokens, output_tokens, estimated_cost_usd); never invent tokens."""

    if not isinstance(usage, Mapping):
        return None, None, None
    input_tokens = usage.get("input_tokens")
    if not _is_token_count(input_tokens):
        return None, None, None
    output_tokens = usage.get("output_tokens")
    if not _is_token_count(output_tokens):
        output_tokens = None
    cost = estimate_cost_usd(input_tokens, price_usd_per_million_input_tokens)
    return input_tokens, output_tokens, cost


class Stopwatch:
    """Monotonic elapsed-time measurement with an injectable clock."""

    def __init__(self, clock=time.monotonic) -> None:
        self._clock = clock
        self._started: float | None = None
        self._elapsed_ms: int | None = None

    def start(self) -> None:
        self._started = self._clock()
        self._elapsed_ms = None

    def stop(self) -> None:
        if self._started is None:
            raise RuntimeError("stopwatch was never started")
        self._elapsed_ms = int(round((self._clock() - self._started) * 1000))

    @property
    def elapsed_ms(self) -> int:
        if self._elapsed_ms is None:
            raise RuntimeError("stopwatch has not been stopped")
        return self._elapsed_ms


@dataclass(frozen=True)
class DecisionTrace:
    run_id: str
    benchmark_case_id: str
    execution_mode: str
    operation: str
    started_at: str
    finished_at: str
    elapsed_ms: int
    input_sha256: str
    item_count: int
    question_count: int
    screened_clear_count: int
    escalated_count: int
    request_count: int
    input_tokens: int | None
    output_tokens: int | None
    estimated_cost_usd: str | None
    price_usd_per_million_input_tokens: str
    price_snapshot_date: str
    resolved_model: str | None
    status: str
    fallback_used: bool
    error_class: str | None

    def to_dict(self) -> dict:
        payload = {"schema_version": TRACE_SCHEMA}
        payload.update(self.__dict__)
        return payload
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/test_telemetry.py`
Expected: PASS

- [ ] **Step 5: 运行聚合校验并提交**

Run: `python scripts/run_plugin_tests.py`
Expected: PASS

```bash
git add plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/telemetry.py plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/test_telemetry.py
git commit -m "feat(jev): add decision telemetry with decimal cost and benchmark case ids" -m "Track timing, raw token usage, and a decimal estimated cost, and derive a benchmark case id so the llm and jev_assisted paths compare the same sample." -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 5: 凭证门、endpoint allowlist 与 transport 抽象

本任务只做**单次尝试**的 transport；重试与错误分类在 Task 6。凭证门必须是硬门：没有 key 就不进入 transport，一个字节都不发。

**Files:**
- Create: `plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/jev_client.py`
- Create: `plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/test_jev_client.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `jev_client.ENDPOINT = "https://api.typesafe.ai/v1/systemone"`、`ALLOWED_HOST = "api.typesafe.ai"`、`ENDPOINT_PATH = "/v1/systemone"`、`API_KEY_ENV = "TYPESAFE_API_KEY"`
  - `jev_client.JevClientError(RuntimeError)`、`JevEndpointError`、`JevTransportFailure`、`JevTransportOutcomeUnknown`
  - `jev_client.read_api_key(environ=None) -> str | None`
  - `jev_client.assert_production_endpoint(url) -> None`
  - `jev_client.TransportResponse`（frozen dataclass：`status_code: int`、`body: str`、`headers: Mapping[str, str]`）
  - `jev_client.Transport`（Protocol：`send(url, headers, body, timeout) -> TransportResponse`）
  - `jev_client.UrllibTransport(connect_timeout=5.0, total_timeout=30.0)`
  - `jev_client.FakeTransport(responses=None, error=None)`，含 `calls: list[dict]`
  - `jev_client.CallOutcome`（frozen dataclass：`status`、`status_code`、`payload`、`error_class`、`attempts`）
  - `jev_client.JevClient(transport, environ=None, sleep=time.sleep, total_timeout=30.0)` 与 `JevClient.call(request) -> CallOutcome`

- [ ] **Step 1: 写失败测试**

创建 `plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/test_jev_client.py`：

```python
import json
import os
import unittest
from unittest import mock

import jev_client
from jev_client import (
    API_KEY_ENV,
    ENDPOINT,
    FakeTransport,
    JevClient,
    JevEndpointError,
    JevTransportFailure,
    JevTransportOutcomeUnknown,
    TransportResponse,
    UrllibTransport,
    assert_production_endpoint,
    read_api_key,
)

MARKER_STATE = "小红帽把蛋糕递给了奶奶"


def make_request():
    return {
        "schema_version": "pb-jev-request-v1",
        "run_id": "20260923-example-0001",
        "operation": "knowledge_relevance",
        "model": "jev-1.13.0",
        "policy_version": "knowledge-relevance-v1",
        "state": MARKER_STATE,
        "questions": {"relevant": {"type": "noul", "instructions": "是否相关？"}},
        "context_refs": [{"ref_id": "k", "kind": "knowledge_page", "revisions": {"n": "1"}}],
        "benchmark_case_id": "sha256:" + "0" * 64,
    }


def success_body():
    return json.dumps({
        "model": "jev-1.13.0",
        "answers": {"relevant": {"type": "noul", "noul": 0.91}},
        "usage": {"input_tokens": 296, "output_tokens": 20},
    })


def make_client(transport, environ=None):
    return JevClient(transport, environ={} if environ is None else environ, sleep=lambda _: None)


class ApiKeyTests(unittest.TestCase):
    def test_missing_key_reads_as_missing(self):
        self.assertIsNone(read_api_key({}))

    def test_empty_and_whitespace_keys_read_as_missing(self):
        self.assertIsNone(read_api_key({API_KEY_ENV: ""}))
        self.assertIsNone(read_api_key({API_KEY_ENV: "   \t "}))

    def test_present_key_is_trimmed(self):
        self.assertEqual(read_api_key({API_KEY_ENV: "  sk-abc  "}), "sk-abc")


class EndpointAllowlistTests(unittest.TestCase):
    def test_shipped_endpoint_is_allowed(self):
        assert_production_endpoint(ENDPOINT)

    def test_other_hosts_are_refused(self):
        for url in (
            "https://evil.example/v1/systemone",
            "https://api.typesafe.ai.evil.example/v1/systemone",
            "https://typesafe.ai/v1/systemone",
        ):
            with self.subTest(url=url), self.assertRaises(JevEndpointError):
                assert_production_endpoint(url)

    def test_plain_http_is_refused(self):
        with self.assertRaises(JevEndpointError):
            assert_production_endpoint("http://api.typesafe.ai/v1/systemone")

    def test_other_paths_are_refused(self):
        with self.assertRaises(JevEndpointError):
            assert_production_endpoint("https://api.typesafe.ai/v1/other")


class CredentialGateTests(unittest.TestCase):
    def test_missing_key_returns_waiting_without_touching_the_transport(self):
        transport = FakeTransport(responses=[TransportResponse(200, success_body(), {})])
        outcome = make_client(transport, environ={}).call(make_request())
        self.assertEqual(outcome.status, "waiting_for_jev_key")
        self.assertEqual(outcome.attempts, 0)
        self.assertEqual(transport.calls, [])

    def test_whitespace_key_also_waits(self):
        transport = FakeTransport()
        outcome = make_client(transport, environ={API_KEY_ENV: "  "}).call(make_request())
        self.assertEqual(outcome.status, "waiting_for_jev_key")
        self.assertEqual(transport.calls, [])

    def test_an_ambient_key_is_not_used_when_an_explicit_environ_is_supplied(self):
        transport = FakeTransport()
        with mock.patch.dict(os.environ, {API_KEY_ENV: "ambient-secret"}, clear=False):
            outcome = make_client(transport, environ={}).call(make_request())
        self.assertEqual(outcome.status, "waiting_for_jev_key")
        self.assertEqual(transport.calls, [])

    def test_a_present_key_is_dispatched_once(self):
        transport = FakeTransport(responses=[TransportResponse(200, success_body(), {})])
        outcome = make_client(transport, environ={API_KEY_ENV: "sk-abc"}).call(make_request())
        self.assertEqual(outcome.status, "succeeded")
        self.assertEqual(outcome.attempts, 1)
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(transport.calls[0]["url"], ENDPOINT)

    def test_authorization_header_is_sent_as_bearer(self):
        transport = FakeTransport(responses=[TransportResponse(200, success_body(), {})])
        make_client(transport, environ={API_KEY_ENV: "sk-abc"}).call(make_request())
        self.assertEqual(transport.calls[0]["headers"]["Authorization"], "Bearer sk-abc")

    def test_the_key_never_appears_in_the_outcome(self):
        transport = FakeTransport(responses=[TransportResponse(200, success_body(), {})])
        outcome = make_client(transport, environ={API_KEY_ENV: "sk-secret-value"}).call(make_request())
        self.assertNotIn("sk-secret-value", repr(outcome))


class RedirectionTests(unittest.TestCase):
    def test_redirect_handler_declines_every_redirect(self):
        handler = jev_client._NoRedirectHandler()
        self.assertIsNone(handler.redirect_request(None, None, 302, "Found", {}, "https://evil.example/"))

    def test_a_mocked_302_is_reported_as_an_endpoint_error(self):
        # UrllibTransport must not follow the redirect; urllib surfaces the 3xx
        # as an HTTPError, which the transport returns verbatim.
        transport = UrllibTransport()
        with mock.patch.object(transport, "_open") as opener:
            opener.side_effect = jev_client.urllib.error.HTTPError(
                ENDPOINT, 302, "Found", {"Location": "https://evil.example/"}, None
            )
            response = transport.send(ENDPOINT, {}, b"{}", 1.0)
        self.assertEqual(response.status_code, 302)


class TransportFailureTests(unittest.TestCase):
    def test_a_provably_unsent_request_is_a_transport_failure(self):
        transport = FakeTransport(error=JevTransportFailure("connection refused"))
        outcome = make_client(transport, environ={API_KEY_ENV: "sk-abc"}).call(make_request())
        self.assertEqual(outcome.status, "failed")
        self.assertEqual(outcome.error_class, "JevTransportFailure")

    def test_an_ambiguous_outcome_is_never_reported_as_failure(self):
        transport = FakeTransport(error=JevTransportOutcomeUnknown("read timed out"))
        outcome = make_client(transport, environ={API_KEY_ENV: "sk-abc"}).call(make_request())
        self.assertEqual(outcome.status, "outcome_unknown")

    def test_a_malformed_success_body_is_a_failure(self):
        transport = FakeTransport(responses=[TransportResponse(200, "{not json", {})])
        outcome = make_client(transport, environ={API_KEY_ENV: "sk-abc"}).call(make_request())
        self.assertEqual(outcome.status, "failed")
        self.assertEqual(outcome.error_class, "invalid_json")


class UrllibTransportTests(unittest.TestCase):
    def test_the_real_transport_refuses_a_non_allowlisted_url_before_opening(self):
        transport = UrllibTransport()
        with mock.patch.object(transport, "_open") as opener:
            with self.assertRaises(JevEndpointError):
                transport.send("https://evil.example/v1/systemone", {}, b"{}", 1.0)
        opener.assert_not_called()

    def test_the_real_transport_refuses_to_swallow_ambient_credentials_in_tests(self):
        # The production transport must be constructed with an explicit environ
        # by the runner; it must not read the environment by itself.
        self.assertFalse(hasattr(UrllibTransport(), "environ"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/test_jev_client.py`
Expected: FAIL —— `ModuleNotFoundError: No module named 'jev_client'`

- [ ] **Step 3: 实现 `jev_client.py`（单次尝试）**

创建 `plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/jev_client.py`：

```python
"""Minimal standard-library client for the TypeSafe Jev SystemOne API."""

from __future__ import annotations

import json
import os
import socket
import ssl
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
ALLOWED_HOST = "api.typesafe.ai"
ENDPOINT_PATH = "/v1/systemone"
API_KEY_ENV = "TYPESAFE_API_KEY"

DEFAULT_CONNECT_TIMEOUT = 5.0
DEFAULT_TOTAL_TIMEOUT = 30.0


class JevClientError(RuntimeError):
    """Base class for client-side failures."""


class JevEndpointError(JevClientError):
    """The endpoint is not the allow-listed production endpoint."""


class JevTransportFailure(JevClientError):
    """The request provably never completed; reporting a failure is safe."""


class JevTransportOutcomeUnknown(JevClientError):
    """The request may have reached the service; the outcome cannot be known."""


@dataclass(frozen=True)
class TransportResponse:
    status_code: int
    body: str
    headers: Mapping[str, str]


class Transport(Protocol):
    def send(
        self, url: str, headers: Mapping[str, str], body: bytes, timeout: float
    ) -> TransportResponse: ...


@dataclass(frozen=True)
class CallOutcome:
    status: str
    status_code: int | None
    payload: Mapping[str, Any] | None
    error_class: str | None
    attempts: int


def read_api_key(environ: Mapping[str, str] | None = None) -> str | None:
    """Read the Jev key from the environment; empty or blank counts as missing."""

    source = os.environ if environ is None else environ
    raw = source.get(API_KEY_ENV)
    if not isinstance(raw, str):
        return None
    return raw.strip() or None


def assert_production_endpoint(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise JevEndpointError(f"endpoint must use https, got {parts.scheme!r}")
    if parts.hostname != ALLOWED_HOST:
        raise JevEndpointError(f"endpoint host is not allow-listed: {parts.hostname!r}")
    if parts.path != ENDPOINT_PATH:
        raise JevEndpointError(f"endpoint path is not allow-listed: {parts.path!r}")


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse every redirect so credentials never travel to another host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class UrllibTransport:
    """Production transport, pinned to the allow-listed endpoint."""

    def __init__(
        self,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        total_timeout: float = DEFAULT_TOTAL_TIMEOUT,
    ) -> None:
        self.connect_timeout = connect_timeout
        self.total_timeout = total_timeout

    def _open(self, request: urllib.request.Request, timeout: float):
        opener = urllib.request.build_opener(_NoRedirectHandler())
        return opener.open(request, timeout=timeout)

    def send(
        self, url: str, headers: Mapping[str, str], body: bytes, timeout: float
    ) -> TransportResponse:
        assert_production_endpoint(url)
        request = urllib.request.Request(
            url, data=body, headers=dict(headers), method="POST"
        )
        try:
            with self._open(request, timeout) as response:
                return TransportResponse(
                    response.status, response.read().decode("utf-8"), dict(response.headers)
                )
        except urllib.error.HTTPError as error:
            return TransportResponse(
                error.code, error.read().decode("utf-8", "replace"), dict(error.headers)
            )
        except (socket.timeout, TimeoutError) as error:
            # A timeout can fire during connect or while reading the response.
            # We cannot tell which, and a duplicate billed call is worse than a
            # spurious "unknown", so timeouts always report the ambiguous case.
            raise JevTransportOutcomeUnknown(str(error)) from error
        except urllib.error.URLError as error:
            if isinstance(error.reason, (socket.timeout, TimeoutError)):
                raise JevTransportOutcomeUnknown(str(error.reason)) from error
            raise JevTransportFailure(str(error)) from error
        except (ssl.SSLError, ConnectionError, OSError) as error:
            raise JevTransportFailure(str(error)) from error


class FakeTransport:
    """Scripted transport for tests. Never reads the environment or opens a socket."""

    def __init__(self, responses=None, error: Exception | None = None) -> None:
        self.calls: list[dict] = []
        self._responses = list(responses or [])
        self._error = error

    def send(
        self, url: str, headers: Mapping[str, str], body: bytes, timeout: float
    ) -> TransportResponse:
        self.calls.append(
            {"url": url, "headers": dict(headers), "body": body, "timeout": timeout}
        )
        if self._error is not None:
            raise self._error
        if not self._responses:
            raise AssertionError("FakeTransport has no scripted response left")
        return self._responses.pop(0)


class JevClient:
    """Dispatch a decision request; holds the credential gate."""

    def __init__(
        self,
        transport: Transport,
        environ: Mapping[str, str] | None = None,
        sleep=time.sleep,
        total_timeout: float = DEFAULT_TOTAL_TIMEOUT,
    ) -> None:
        self._transport = transport
        self._environ = environ
        self._sleep = sleep
        self._total_timeout = total_timeout

    def call(self, request: Mapping[str, Any]) -> CallOutcome:
        key = read_api_key(self._environ)
        if key is None:
            return CallOutcome("waiting_for_jev_key", None, None, None, 0)
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        body = json.dumps(request, ensure_ascii=False).encode("utf-8")
        return self._attempt(request, headers, body)

    def _attempt(self, request, headers, body) -> CallOutcome:
        try:
            response = self._transport.send(
                ENDPOINT, headers, body, self._total_timeout
            )
        except JevTransportOutcomeUnknown as error:
            return CallOutcome("outcome_unknown", None, None, type(error).__name__, 1)
        except JevTransportFailure as error:
            return CallOutcome("failed", None, None, type(error).__name__, 1)
        if 300 <= response.status_code < 400:
            raise JevEndpointError(
                f"redirect responses are not accepted: {response.status_code}"
            )
        return self._classify(response, request)

    def _classify(self, response: TransportResponse, request) -> CallOutcome:
        status = response.status_code
        if status == 200:
            try:
                payload = json.loads(response.body)
            except ValueError:
                return CallOutcome("failed", status, None, "invalid_json", 1)
            return CallOutcome("succeeded", status, payload, None, 1)
        if status == 401:
            return CallOutcome("waiting_for_jev_key", status, None, "unauthorized", 1)
        if status == 403:
            return CallOutcome("waiting_for_jev_access", status, None, "forbidden", 1)
        if status == 422:
            return CallOutcome("failed", status, None, "unprocessable_entity", 1)
        return CallOutcome("failed", status, None, f"http_{status}", 1)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/test_jev_client.py`
Expected: PASS

- [ ] **Step 5: 运行聚合校验并提交**

Run: `python scripts/run_plugin_tests.py`
Expected: PASS

```bash
git add plugins/picturebook-screenwriter/skills/jev-decision-runtime
git commit -m "feat(jev): add credential gate, endpoint allowlist, and transport abstraction" -m "No key means no request is constructed; the production transport refuses any host or path outside the allowlist and declines every redirect." -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 6: 重试、退避与错误分类

429/529 与网络失败按上限重试；422 不盲重试；401/403 不盲重试而是转入等待状态。

**Files:**
- Modify: `plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/jev_client.py`
- Modify: `plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/test_jev_client.py`

**Interfaces:**
- Consumes: Task 5 的 `JevClient`、`FakeTransport`、`CallOutcome`、`TransportResponse`
- Produces:
  - `jev_client.MAX_ATTEMPTS = 3`、`BACKOFF_INITIAL_SECONDS = 0.5`、`BACKOFF_MAX_SECONDS = 5.0`
  - `jev_client.parse_retry_after(headers) -> float | None`
  - `jev_client.backoff_seconds(attempt, retry_after) -> float`
  - `JevClient.call` 的 `attempts` 字段反映真实尝试次数

- [ ] **Step 1: 写失败测试**

在 `test_jev_client.py` 的 import 块补充：

```python
from jev_client import backoff_seconds, parse_retry_after
```

在文件末尾追加：

```python
class RetryPolicyTests(unittest.TestCase):
    def test_retry_after_is_read_in_seconds_and_milliseconds(self):
        self.assertEqual(parse_retry_after({"Retry-After": "2"}), 2.0)
        self.assertEqual(parse_retry_after({"retry-after-ms": "1500"}), 1.5)

    def test_a_missing_or_unparsable_retry_after_is_none(self):
        self.assertIsNone(parse_retry_after({}))
        self.assertIsNone(parse_retry_after({"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}))

    def test_backoff_grows_and_is_capped(self):
        self.assertEqual(backoff_seconds(1, None), 0.5)
        self.assertEqual(backoff_seconds(2, None), 1.0)
        self.assertEqual(backoff_seconds(9, None), 5.0)

    def test_retry_after_wins_over_exponential_backoff(self):
        self.assertEqual(backoff_seconds(1, 2.0), 2.0)
        self.assertEqual(backoff_seconds(1, 600.0), 5.0)


class RetryLoopTests(unittest.TestCase):
    def test_overload_is_retried_then_succeeds(self):
        transport = FakeTransport(responses=[
            TransportResponse(529, "", {}),
            TransportResponse(200, success_body(), {}),
        ])
        outcome = make_client(transport, environ={API_KEY_ENV: "sk-abc"}).call(make_request())
        self.assertEqual(outcome.status, "succeeded")
        self.assertEqual(outcome.attempts, 2)
        self.assertEqual(len(transport.calls), 2)

    def test_rate_limiting_honours_retry_after(self):
        sleeps = []
        transport = FakeTransport(responses=[
            TransportResponse(429, "", {"retry-after-ms": "2500"}),
            TransportResponse(200, success_body(), {}),
        ])
        client = JevClient(transport, environ={API_KEY_ENV: "sk-abc"}, sleep=sleeps.append)
        outcome = client.call(make_request())
        self.assertEqual(outcome.status, "succeeded")
        self.assertEqual(sleeps, [2.5])

    def test_repeated_overload_gives_up_after_the_attempt_cap(self):
        transport = FakeTransport(responses=[
            TransportResponse(529, "", {}),
            TransportResponse(529, "", {}),
            TransportResponse(529, "", {}),
        ])
        outcome = make_client(transport, environ={API_KEY_ENV: "sk-abc"}).call(make_request())
        self.assertEqual(outcome.status, "failed")
        self.assertEqual(outcome.error_class, "http_529")
        self.assertEqual(outcome.attempts, 3)

    def test_a_contract_error_is_never_retried(self):
        transport = FakeTransport(responses=[TransportResponse(422, "bad field", {})])
        outcome = make_client(transport, environ={API_KEY_ENV: "sk-abc"}).call(make_request())
        self.assertEqual(outcome.status, "failed")
        self.assertEqual(outcome.error_class, "unprocessable_entity")
        self.assertEqual(len(transport.calls), 1)

    def test_unauthorized_is_not_blindly_retried(self):
        transport = FakeTransport(responses=[TransportResponse(401, "", {})])
        outcome = make_client(transport, environ={API_KEY_ENV: "sk-abc"}).call(make_request())
        self.assertEqual(outcome.status, "waiting_for_jev_key")
        self.assertEqual(len(transport.calls), 1)

    def test_forbidden_has_its_own_waiting_state(self):
        transport = FakeTransport(responses=[TransportResponse(403, "", {})])
        outcome = make_client(transport, environ={API_KEY_ENV: "sk-abc"}).call(make_request())
        self.assertEqual(outcome.status, "waiting_for_jev_access")
        self.assertEqual(len(transport.calls), 1)

    def test_a_transport_failure_is_retried_up_to_the_cap(self):
        transport = FakeTransport(error=JevTransportFailure("connection refused"))
        outcome = make_client(transport, environ={API_KEY_ENV: "sk-abc"}).call(make_request())
        self.assertEqual(outcome.status, "failed")
        self.assertEqual(outcome.attempts, 3)
        self.assertEqual(len(transport.calls), 3)

    def test_an_ambiguous_outcome_is_not_retried(self):
        transport = FakeTransport(error=JevTransportOutcomeUnknown("read timed out"))
        outcome = make_client(transport, environ={API_KEY_ENV: "sk-abc"}).call(make_request())
        self.assertEqual(outcome.status, "outcome_unknown")
        self.assertEqual(len(transport.calls), 1)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/test_jev_client.py`
Expected: FAIL —— `ImportError: cannot import name 'backoff_seconds'`

- [ ] **Step 3: 实现重试与分类**

在 `jev_client.py` 的常量区加入：

```python
MAX_ATTEMPTS = 3
BACKOFF_INITIAL_SECONDS = 0.5
BACKOFF_MAX_SECONDS = 5.0
_RETRYABLE_STATUSES = (429, 529)
```

把 `JevClient._attempt` 替换为带重试的实现，并新增 `_dispatch` 与两个模块级函数：

```python
def parse_retry_after(headers: Mapping[str, str]) -> float | None:
    """Read retry-after-ms or retry-after as seconds; HTTP-date form is ignored."""

    lowered = {str(key).lower(): value for key, value in (headers or {}).items()}
    milliseconds = lowered.get("retry-after-ms")
    if milliseconds is not None:
        try:
            return float(milliseconds) / 1000.0
        except (TypeError, ValueError):
            return None
    seconds = lowered.get("retry-after")
    if seconds is None:
        return None
    try:
        return float(seconds)
    except (TypeError, ValueError):
        return None


def backoff_seconds(attempt: int, retry_after: float | None) -> float:
    if retry_after is not None and retry_after >= 0:
        return min(retry_after, BACKOFF_MAX_SECONDS)
    return min(BACKOFF_INITIAL_SECONDS * (2 ** (attempt - 1)), BACKOFF_MAX_SECONDS)
```

在 `JevClient` 中：

```python
    def _attempt(self, request, headers, body) -> CallOutcome:
        attempts = 0
        while attempts < MAX_ATTEMPTS:
            attempts += 1
            try:
                response = self._transport.send(
                    ENDPOINT, headers, body, self._total_timeout
                )
            except JevTransportOutcomeUnknown as error:
                # Ambiguous: retrying could duplicate a billed call.
                return CallOutcome("outcome_unknown", None, None, type(error).__name__, attempts)
            except JevTransportFailure as error:
                if attempts >= MAX_ATTEMPTS:
                    return CallOutcome("failed", None, None, type(error).__name__, attempts)
                self._sleep(backoff_seconds(attempts, None))
                continue
            if 300 <= response.status_code < 400:
                raise JevEndpointError(
                    f"redirect responses are not accepted: {response.status_code}"
                )
            outcome = self._classify(response, attempts)
            if outcome.status == "retry":
                if attempts >= MAX_ATTEMPTS:
                    return CallOutcome(
                        "failed", response.status_code, None,
                        f"http_{response.status_code}", attempts,
                    )
                self._sleep(backoff_seconds(attempts, outcome.payload))
                continue
            return outcome
        return CallOutcome("failed", None, None, "attempts_exhausted", attempts)
```

把 `_classify` 改为接收 `attempts`，并在 `_RETRYABLE_STATUSES` 分支返回一个内部重试信号（`payload` 承载 retry-after 秒数）：

```python
    def _classify(self, response: TransportResponse, attempts: int) -> CallOutcome:
        status = response.status_code
        if status == 200:
            try:
                payload = json.loads(response.body)
            except ValueError:
                return CallOutcome("failed", status, None, "invalid_json", attempts)
            return CallOutcome("succeeded", status, payload, None, attempts)
        if status == 401:
            return CallOutcome("waiting_for_jev_key", status, None, "unauthorized", attempts)
        if status == 403:
            return CallOutcome("waiting_for_jev_access", status, None, "forbidden", attempts)
        if status == 422:
            return CallOutcome("failed", status, None, "unprocessable_entity", attempts)
        if status in _RETRYABLE_STATUSES:
            return CallOutcome(
                "retry", status, parse_retry_after(response.headers), None, attempts
            )
        return CallOutcome("failed", status, None, f"http_{status}", attempts)
```

`"retry"` 是 `JevClient` 私有的内部信号，**不**出现在 `pb-jev-result-v1` 的 `status` 取值里；runner 只会看到 `succeeded` / `failed` / `waiting_for_*` / `outcome_unknown`。

- [ ] **Step 4: 运行测试确认通过**

Run: `python plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/test_jev_client.py`
Expected: PASS

- [ ] **Step 5: 运行聚合校验并提交**

Run: `python scripts/run_plugin_tests.py`
Expected: PASS

```bash
git add plugins/picturebook-screenwriter/skills/jev-decision-runtime
git commit -m "feat(jev): bound retries and classify transport and HTTP failures" -m "Rate limiting and overload retry with capped exponential backoff honouring retry-after; 401 and 403 wait instead of retrying, 422 never retries, and an ambiguous outcome is never resent." -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 7: 运行器——请求落盘、单次执行与原子终态

把 request/result/trace 与目录布局接起来，并落实 spec 的关键顺序约束：**只有在终态结果原子落盘之后，才能清除 pending call**。

**Files:**
- Create: `plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/jev_runner.py`
- Create: `plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/test_jev_runner.py`

**Interfaces:**
- Consumes: Task 1–6 的 `decision_contract`、`telemetry`、`jev_client`
- Produces:
  - `jev_runner.RunnerConfig(run_dir: Path, policy: dict, execution_mode: str = "jev_assisted", holder: str = "primary", lease_ttl_minutes: int = 15)`
  - `jev_runner.operation_id_for(run_id: str, operation: str, instance: str = "") -> str`
  - `jev_runner.operation_id_from_request(request) -> str`
  - `jev_runner.operation_dir(run_dir, operation_id) -> Path`、`pending_path`、`lease_path`、`result_path`、`trace_path`、`context_path`、`request_path`
  - `jev_runner.write_atomic(path: Path, payload) -> None`、`jev_runner.read_json(path) -> dict | None`
  - `jev_runner.build_pending_call(request) -> dict`
  - `jev_runner.build_result(*, request, status, payload=None, error_class=None, attempts=0, elapsed_ms=0, trace=None) -> dict`
  - `jev_runner.read_decision_context(run_dir) -> dict | None`
  - `jev_runner.build_decision_context_for_run(*, mode, external_text_processing_acknowledged, selected_at=None) -> dict`
  - `jev_runner.sync_decision_context(config, *, credential_status, pending_call, resume_cursor=None) -> dict`
  - `jev_runner.execute(request, config, client, clock=None) -> dict`
  - `jev_runner.run_operation(request, config, client, clock=None, now=None) -> dict`
  - `jev_runner.trace_for(request, config, *, status, attempts, error_class, resolved_model, usage, elapsed_ms, started_at, finished_at) -> dict | None`

- [ ] **Step 1: 写失败测试**

创建 `plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/test_jev_runner.py`：

```python
import json
import tempfile
import unittest
from pathlib import Path

from decision_contract import (
    ContractError,
    load_policy,
    default_policy_path,
)
from jev_client import API_KEY_ENV, ENDPOINT, FakeTransport, JevClient, TransportResponse
from jev_runner import (
    RunnerConfig,
    context_path,
    operation_dir,
    operation_id_for,
    pending_path,
    read_decision_context,
    read_json,
    request_path,
    result_path,
    run_operation,
    trace_path,
    write_atomic,
)

RUN_ID = "20260923-example-0001"
MARKER_STATE = "小红帽把蛋糕递给了奶奶"


def make_request(**overrides):
    request = {
        "schema_version": "pb-jev-request-v1",
        "run_id": RUN_ID,
        "operation": "knowledge_relevance",
        "model": "jev-1.13.0",
        "policy_version": "knowledge-relevance-v1",
        "state": MARKER_STATE,
        "questions": {"relevant": {"type": "noul", "instructions": "是否相关？"}},
        "context_refs": [
            {"ref_id": "海外绘本/小老鼠迈尔斯/worldview", "kind": "knowledge_page",
             "revisions": {"node-a": "17"}}
        ],
        "benchmark_case_id": "sha256:" + "0" * 64,
    }
    request.update(overrides)
    return request


def success_body():
    return json.dumps({
        "model": "jev-1.13.0",
        "answers": {"relevant": {"type": "noul", "noul": 0.91}},
        "usage": {"input_tokens": 296, "output_tokens": 20},
    })


class RunnerCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self._tmp.name)
        self.config = RunnerConfig(
            run_dir=self.run_dir, policy=load_policy(default_policy_path())
        )
        self.operation_id = operation_id_for(RUN_ID, "knowledge_relevance")

    def tearDown(self):
        self._tmp.cleanup()

    def client(self, responses=None, error=None, environ=None):
        transport = FakeTransport(responses=responses, error=error)
        return JevClient(
            transport,
            environ={API_KEY_ENV: "sk-abc"} if environ is None else environ,
            sleep=lambda _: None,
        ), transport


class AtomicWriteTests(RunnerCase):
    def test_write_atomic_replaces_and_leaves_no_temporary(self):
        target = self.run_dir / "sample.json"
        write_atomic(target, {"a": 1})
        write_atomic(target, {"a": 2})
        self.assertEqual(read_json(target), {"a": 2})
        self.assertEqual(sorted(p.name for p in self.run_dir.iterdir()), ["sample.json"])

    def test_read_json_returns_none_for_missing_or_broken_files(self):
        self.assertIsNone(read_json(self.run_dir / "missing.json"))
        broken = self.run_dir / "broken.json"
        broken.write_text("{not json", encoding="utf-8")
        self.assertIsNone(read_json(broken))


class PathLayoutTests(RunnerCase):
    def test_paths_match_the_documented_layout(self):
        self.assertEqual(
            operation_dir(self.run_dir, self.operation_id),
            self.run_dir / "jev" / self.operation_id,
        )
        self.assertEqual(request_path(self.run_dir, self.operation_id).name, "request.json")
        self.assertEqual(pending_path(self.run_dir, self.operation_id).name, "pending.json")
        self.assertEqual(result_path(self.run_dir, self.operation_id).name, "result.json")
        self.assertEqual(
            trace_path(self.run_dir, self.operation_id, 1),
            operation_dir(self.run_dir, self.operation_id) / "trace" / "0001.json",
        )
        self.assertEqual(context_path(self.run_dir).name, "decision-context.json")

    def test_an_operation_instance_gets_its_own_directory(self):
        plain = operation_id_for(RUN_ID, "knowledge_relevance")
        batched = operation_id_for(RUN_ID, "knowledge_relevance", "batch-002")
        self.assertEqual(plain, "20260923-example-0001-knowledge_relevance")
        self.assertEqual(batched, "20260923-example-0001-knowledge_relevance-batch-002")
        self.assertNotEqual(
            request_path(self.run_dir, plain), request_path(self.run_dir, batched)
        )

    def test_operation_id_is_derived_from_the_request_instance(self):
        from jev_runner import operation_id_from_request

        self.assertEqual(operation_id_from_request(make_request()), self.operation_id)
        self.assertEqual(
            operation_id_from_request(make_request(operation_instance="batch-003")),
            f"{self.operation_id}-batch-003",
        )


class SuccessfulRunTests(RunnerCase):
    def test_success_persists_the_result_and_persists_the_request(self):
        client, transport = self.client([TransportResponse(200, success_body(), {})])
        result = run_operation(make_request(), self.config, client)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["resolved_model"], "jev-1.13.0")
        self.assertEqual(result["answers"]["relevant"]["noul"], 0.91)
        self.assertEqual(result["routes"], [])
        self.assertEqual(result["usage"], {"input_tokens": 296, "output_tokens": 20})
        self.assertTrue(request_path(self.run_dir, self.operation_id).is_file())
        self.assertEqual(
            read_json(result_path(self.run_dir, self.operation_id))["status"], "succeeded"
        )
        self.assertEqual(len(transport.calls), 1)

    def test_success_clears_the_pending_call_only_after_the_result_lands(self):
        client, _ = self.client([TransportResponse(200, success_body(), {})])
        run_operation(make_request(), self.config, client)
        self.assertFalse(pending_path(self.run_dir, self.operation_id).exists())
        context = read_decision_context(self.run_dir)
        self.assertIsNone(context["pending_call"])
        self.assertEqual(context["credential_status"], "available")
        self.assertEqual(context["resume_cursor"],
                         f"after_operation:{self.operation_id}")

    def test_a_successful_run_writes_a_trace_without_draft_text(self):
        client, _ = self.client([TransportResponse(200, success_body(), {})])
        run_operation(make_request(), self.config, client)
        trace = read_json(trace_path(self.run_dir, self.operation_id, 1))
        self.assertEqual(trace["schema_version"], "pb-decision-trace-v1")
        self.assertEqual(trace["input_tokens"], 296)
        self.assertEqual(trace["estimated_cost_usd"], "0.000012432000")
        self.assertNotIn(MARKER_STATE, json.dumps(trace, ensure_ascii=False))

    def test_no_written_file_carries_a_credential(self):
        client, _ = self.client([TransportResponse(200, success_body(), {})])
        run_operation(make_request(), self.config, client)
        for path in self.run_dir.rglob("*"):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                self.assertNotIn("sk-abc", text)
                self.assertNotIn("Authorization", text)

    def test_only_the_persisted_request_carries_the_state_body(self):
        # Resuming a suspended call needs the request body locally, so the run
        # directory keeps exactly one file holding the input text: request.json.
        # Nothing written for humans or for telemetry may carry it.
        client, _ = self.client([TransportResponse(200, success_body(), {})])
        run_operation(make_request(), self.config, client)
        operation_dir = self.run_dir / "jev" / self.operation_id
        carriers = sorted(
            path.name
            for path in self.run_dir.rglob("*")
            if path.is_file() and MARKER_STATE in path.read_text(encoding="utf-8")
        )
        self.assertEqual(carriers, ["request.json"])
        self.assertEqual(
            read_json(operation_dir / "request.json")["state"], MARKER_STATE
        )

    def test_a_different_resolved_model_is_refused(self):
        # The policy pins the version the thresholds were calibrated against. A
        # response from any other version must not be reported as succeeded, or
        # uncalibrated probabilities would be consumed as if they came from the
        # pinned model.
        body = json.dumps({
            "model": "jev-1.14.0",
            "answers": {"relevant": {"type": "noul", "noul": 0.91}},
            "usage": {"input_tokens": 296, "output_tokens": 20},
        })
        client, _ = self.client([TransportResponse(200, body, {})])
        result = run_operation(make_request(), self.config, client)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_class"], "model_version_mismatch")
        self.assertFalse(result_path(self.run_dir, self.operation_id).exists())
        self.assertTrue(pending_path(self.run_dir, self.operation_id).is_file())


class IncompleteResponseTests(RunnerCase):
    def test_a_missing_answer_id_fails_without_writing_a_result(self):
        body = json.dumps({"model": "jev-1.13.0", "answers": {}, "usage": {}})
        client, _ = self.client([TransportResponse(200, body, {})])
        result = run_operation(make_request(), self.config, client)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_class"], "incomplete_response")
        self.assertFalse(result_path(self.run_dir, self.operation_id).exists())
        self.assertTrue(pending_path(self.run_dir, self.operation_id).is_file())

    def test_a_failed_attempt_is_recorded_as_failed_not_cleared(self):
        client, _ = self.client([TransportResponse(422, "bad field", {})])
        result = run_operation(make_request(), self.config, client)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(
            read_json(pending_path(self.run_dir, self.operation_id))["attempt_status"],
            "failed",
        )


class WaitingRunTests(RunnerCase):
    def test_a_missing_key_waits_and_writes_no_result(self):
        client, transport = self.client(environ={})
        result = run_operation(make_request(), self.config, client)
        self.assertEqual(result["status"], "waiting_for_jev_key")
        self.assertEqual(result["answers"], {})
        self.assertEqual(result["routes"], [])
        self.assertEqual(result["trace"], {})
        self.assertIsNone(result["resolved_model"])
        self.assertEqual(transport.calls, [])
        self.assertFalse(result_path(self.run_dir, self.operation_id).exists())
        context = read_decision_context(self.run_dir)
        self.assertEqual(context["credential_status"], "waiting_for_jev_key")
        self.assertIsNotNone(context["pending_call"])

    def test_waiting_keeps_the_pending_call_at_pending(self):
        client, _ = self.client(environ={})
        run_operation(make_request(), self.config, client)
        pending = read_json(pending_path(self.run_dir, self.operation_id))
        self.assertEqual(pending["attempt_status"], "pending")

    def test_a_waiting_run_writes_no_trace(self):
        client, _ = self.client(environ={})
        run_operation(make_request(), self.config, client)
        self.assertFalse(trace_path(self.run_dir, self.operation_id, 1).exists())

    def test_forbidden_has_its_own_waiting_state(self):
        client, _ = self.client([TransportResponse(403, "", {})])
        result = run_operation(make_request(), self.config, client)
        self.assertEqual(result["status"], "waiting_for_jev_access")
        self.assertEqual(
            read_decision_context(self.run_dir)["credential_status"],
            "waiting_for_jev_access",
        )


class RequestGateTests(RunnerCase):
    def test_a_policy_version_mismatch_is_refused_before_dispatch(self):
        client, transport = self.client([TransportResponse(200, success_body(), {})])
        with self.assertRaises(ContractError):
            run_operation(
                make_request(policy_version="knowledge-relevance-v99"),
                self.config, client,
            )
        self.assertEqual(transport.calls, [])

    def test_an_invalid_request_is_refused_before_dispatch(self):
        client, transport = self.client([TransportResponse(200, success_body(), {})])
        with self.assertRaises(ContractError):
            run_operation(make_request(questions={}), self.config, client)
        self.assertEqual(transport.calls, [])

    def test_an_llm_mode_run_is_refused_here(self):
        client, transport = self.client([TransportResponse(200, success_body(), {})])
        config = RunnerConfig(run_dir=self.run_dir,
                              policy=self.config.policy, execution_mode="llm")
        with self.assertRaises(ContractError):
            run_operation(make_request(), config, client)
        self.assertEqual(transport.calls, [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/test_jev_runner.py`
Expected: FAIL —— `ModuleNotFoundError: No module named 'jev_runner'`

- [ ] **Step 3: 实现 `jev_runner.py`（无租约、无恢复）**

创建 `plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/jev_runner.py`：

```python
"""Shared Jev decision runner: layout, atomic persistence, and execution."""

from __future__ import annotations

import copy
import json
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from decision_contract import (
    ContractError,
    build_decision_context,
    operation_cursor,
    operation_policy,
    validate_answer_ids,
    validate_decision_context,
    validate_request,
    validate_result,
)
from telemetry import (
    DecisionTrace,
    Stopwatch,
    estimate_usage,
    now_iso,
    request_fingerprint,
    sha256_hex,
    canonical_json,
)

RESULT_STATUSES_WITH_TRACE = ("succeeded", "failed", "outcome_unknown")
_CREDENTIAL_STATUS_FOR_OUTCOME = {
    "succeeded": "available",
    "failed": "available",
    "outcome_unknown": "available",
    "waiting_for_jev_key": "waiting_for_jev_key",
    "waiting_for_jev_access": "waiting_for_jev_access",
}
_ATTEMPT_STATUS_FOR_OUTCOME = {
    "succeeded": None,
    "failed": "failed",
    "outcome_unknown": "outcome_unknown",
    "waiting_for_jev_key": "pending",
    "waiting_for_jev_access": "pending",
}


@dataclass(frozen=True)
class RunnerConfig:
    run_dir: Path
    policy: Mapping[str, Any]
    execution_mode: str = "jev_assisted"
    holder: str = "primary"
    lease_ttl_minutes: int = 15


def operation_id_for(run_id: str, operation: str, instance: str = "") -> str:
    base = f"{run_id}-{operation}"
    return f"{base}-{instance}" if instance else base


def operation_id_from_request(request: Mapping[str, Any]) -> str:
    return operation_id_for(
        request["run_id"], request["operation"], request.get("operation_instance", "")
    )


def operation_dir(run_dir: Any, operation_id: str) -> Path:
    return Path(run_dir) / "jev" / operation_id


def request_path(run_dir: Any, operation_id: str) -> Path:
    return operation_dir(run_dir, operation_id) / "request.json"


def pending_path(run_dir: Any, operation_id: str) -> Path:
    return operation_dir(run_dir, operation_id) / "pending.json"


def lease_path(run_dir: Any, operation_id: str) -> Path:
    return operation_dir(run_dir, operation_id) / "lease.json"


def result_path(run_dir: Any, operation_id: str) -> Path:
    return operation_dir(run_dir, operation_id) / "result.json"


def trace_path(run_dir: Any, operation_id: str, attempt: int) -> Path:
    return operation_dir(run_dir, operation_id) / "trace" / f"{attempt:04d}.json"


def context_path(run_dir: Any) -> Path:
    return Path(run_dir) / "decision-context.json"


def read_json(path: Any) -> dict | None:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def write_atomic(path: Any, payload: Mapping[str, Any]) -> None:
    """temp + os.replace, so a reader never observes a half-written terminal file."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with open(temporary, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def build_pending_call(request: Mapping[str, Any]) -> dict:
    return {
        "operation_id": operation_id_from_request(request),
        "operation": request["operation"],
        "request_fingerprint": request_fingerprint(request),
        "policy_version": request["policy_version"],
        "requested_model": request["model"],
        "attempt_status": "pending",
        "input_refs": [copy.deepcopy(ref) for ref in request["context_refs"]],
    }


def build_result(
    *,
    request: Mapping[str, Any],
    status: str,
    payload: Mapping[str, Any] | None = None,
    error_class: str | None = None,
    attempts: int = 0,
    elapsed_ms: int = 0,
    trace: Mapping[str, Any] | None = None,
    price_usd_per_million_input_tokens: str = "0.042",
) -> dict:
    answers = {}
    usage = {"input_tokens": None, "output_tokens": None}
    resolved_model = None
    if status == "succeeded" and payload is not None:
        answers = dict(payload.get("answers") or {})
        input_tokens, output_tokens, _ = estimate_usage(
            payload.get("usage"), price_usd_per_million_input_tokens
        )
        usage = {"input_tokens": input_tokens, "output_tokens": output_tokens}
        resolved_model = payload.get("model")
    result = {
        "schema_version": "pb-jev-result-v1",
        "run_id": request["run_id"],
        "operation": request["operation"],
        "provider": "typesafe",
        "requested_model": request["model"],
        "resolved_model": resolved_model,
        "policy_version": request["policy_version"],
        "answers": answers,
        "routes": [],
        "usage": usage,
        "trace": dict(trace or {}) if status in RESULT_STATUSES_WITH_TRACE else {},
        "status": status,
    }
    if error_class is not None:
        result["error_class"] = error_class
    validate_result(result)
    return result


def read_decision_context(run_dir: Any) -> dict | None:
    return read_json(context_path(run_dir))


def build_decision_context_for_run(
    *,
    mode: str,
    external_text_processing_acknowledged: bool,
    selected_at: str | None = None,
) -> dict:
    return build_decision_context(
        mode=mode,
        external_text_processing_acknowledged=external_text_processing_acknowledged,
        selected_at=selected_at or now_iso(),
    )


def sync_decision_context(
    config: RunnerConfig,
    *,
    credential_status: str,
    pending_call: Mapping[str, Any] | None,
    resume_cursor: str | None = None,
) -> dict:
    context = read_decision_context(config.run_dir)
    if context is None:
        context = build_decision_context_for_run(
            mode=config.execution_mode,
            external_text_processing_acknowledged=True,
        )
    updated = copy.deepcopy(context)
    updated["credential_status"] = credential_status
    updated["pending_call"] = copy.deepcopy(pending_call) if pending_call else None
    if resume_cursor is not None:
        updated["resume_cursor"] = resume_cursor
    validate_decision_context(updated)
    write_atomic(context_path(config.run_dir), updated)
    return updated


def trace_for(
    request,
    config,
    *,
    status,
    attempts,
    error_class,
    resolved_model,
    usage,
    elapsed_ms,
    started_at,
    finished_at,
) -> dict | None:
    if status not in RESULT_STATUSES_WITH_TRACE:
        return None
    snapshot = config.policy["price_snapshot"]
    input_tokens, output_tokens, cost = estimate_usage(
        usage, snapshot["price_usd_per_million_input_tokens"]
    )
    trace = DecisionTrace(
        run_id=request["run_id"],
        benchmark_case_id=request["benchmark_case_id"],
        execution_mode=config.execution_mode,
        operation=request["operation"],
        started_at=started_at,
        finished_at=finished_at,
        elapsed_ms=elapsed_ms,
        input_sha256=sha256_hex(canonical_json(request)),
        item_count=len(request["context_refs"]),
        question_count=len(request["questions"]),
        screened_clear_count=0,
        escalated_count=0,
        request_count=attempts,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        estimated_cost_usd=cost,
        price_usd_per_million_input_tokens=snapshot["price_usd_per_million_input_tokens"],
        price_snapshot_date=snapshot["snapshot_date"],
        resolved_model=resolved_model,
        status=status,
        fallback_used=False,
        error_class=error_class,
    )
    return trace.to_dict()


def execute(request, config, client, clock=None) -> dict:
    validate_request(request)
    if config.execution_mode != "jev_assisted":
        raise ContractError(
            "the Jev runner is only valid on the jev_assisted execution path"
        )
    entry = operation_policy(config.policy, request["operation"])
    if entry["policy_version"] != request["policy_version"]:
        raise ContractError(
            f"request.policy_version {request['policy_version']!r} does not match "
            f"the policy in use ({entry['policy_version']!r})"
        )
    operation_id = operation_id_from_request(request)
    write_atomic(request_path(config.run_dir, operation_id), request)
    write_atomic(pending_path(config.run_dir, operation_id), build_pending_call(request))
    sync_decision_context(
        config, credential_status="unchecked", pending_call=build_pending_call(request)
    )

    stopwatch = Stopwatch(clock if clock is not None else time.monotonic)
    started_at = now_iso()
    stopwatch.start()
    outcome = client.call(request)
    stopwatch.stop()
    finished_at = now_iso()
    elapsed_ms = stopwatch.elapsed_ms

    if outcome.status == "succeeded":
        try:
            validate_answer_ids(request, outcome.payload)
        except ContractError as error:
            return _settle(
                request, config, operation_id, "failed",
                error_class="incomplete_response", attempts=outcome.attempts,
                elapsed_ms=elapsed_ms, started_at=started_at, finished_at=finished_at,
            )
        resolved_model = (outcome.payload or {}).get("model")
        if resolved_model != config.policy["pinned_model"]:
            # A different resolved version means the policy's thresholds were
            # never calibrated for the answers that just came back, so this
            # cannot be reported as a succeeded operation.
            return _settle(
                request, config, operation_id, "failed",
                error_class="model_version_mismatch", attempts=outcome.attempts,
                elapsed_ms=elapsed_ms, started_at=started_at, finished_at=finished_at,
            )
        trace = trace_for(
            request, config,
            status="succeeded",
            attempts=outcome.attempts,
            error_class=None,
            resolved_model=resolved_model,
            usage=(outcome.payload or {}).get("usage"),
            elapsed_ms=elapsed_ms,
            started_at=started_at,
            finished_at=finished_at,
        )
        result = build_result(
            request=request, status="succeeded", payload=outcome.payload,
            attempts=outcome.attempts, elapsed_ms=elapsed_ms, trace=trace,
            price_usd_per_million_input_tokens=(
                config.policy["price_snapshot"]["price_usd_per_million_input_tokens"]
            ),
        )
        # Terminal state must land before the pending call disappears, so a
        # crash in between leaves a resumable pending call rather than a
        # missing result.
        write_atomic(result_path(config.run_dir, operation_id), result)
        write_atomic(trace_path(config.run_dir, operation_id, outcome.attempts), trace)
        pending_path(config.run_dir, operation_id).unlink(missing_ok=True)
        sync_decision_context(
            config, credential_status="available", pending_call=None,
            resume_cursor=operation_cursor(operation_id),
        )
        return result

    return _settle(
        request, config, operation_id, outcome.status,
        error_class=outcome.error_class, attempts=outcome.attempts,
        elapsed_ms=elapsed_ms, started_at=started_at, finished_at=finished_at,
    )


def _settle(
    request,
    config,
    operation_id,
    status,
    *,
    error_class,
    attempts,
    elapsed_ms,
    started_at,
    finished_at,
):
    pending = build_pending_call(request)
    pending["attempt_status"] = _ATTEMPT_STATUS_FOR_OUTCOME[status]
    trace = trace_for(
        request, config,
        status=status,
        attempts=attempts,
        error_class=error_class,
        resolved_model=None,
        usage=None,
        elapsed_ms=elapsed_ms,
        started_at=started_at,
        finished_at=finished_at,
    )
    result = build_result(
        request=request, status=status, error_class=error_class,
        attempts=attempts, elapsed_ms=elapsed_ms, trace=trace,
        price_usd_per_million_input_tokens=(
            config.policy["price_snapshot"]["price_usd_per_million_input_tokens"]
        ),
    )
    write_atomic(pending_path(config.run_dir, operation_id), pending)
    if trace is not None:
        write_atomic(trace_path(config.run_dir, operation_id, attempts), trace)
    sync_decision_context(
        config,
        credential_status=_CREDENTIAL_STATUS_FOR_OUTCOME[status],
        pending_call=pending,
    )
    return result


def run_operation(request, config, client, clock=None, now=None) -> dict:
    return execute(request, config, client, clock=clock)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/test_jev_runner.py`
Expected: PASS

- [ ] **Step 5: 运行聚合校验并提交**

Run: `python scripts/run_plugin_tests.py`
Expected: PASS

```bash
git add plugins/picturebook-screenwriter/skills/jev-decision-runtime
git commit -m "feat(jev): execute one decision operation and land an atomic terminal result" -m "Persist the request, keep a pending-call descriptor, and only clear it after the terminal result has been written and validated." -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 8: 凭证恢复——pending call、resume 与 freshness

spec §5.3 与 §14.1：缺 key 时保存恢复点；用户本机配置后从同一操作续跑；来源 revision 变化时旧 call 标记 `superseded`，不得把变化后的输入冒充原请求。

**Files:**
- Modify: `plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/jev_runner.py`
- Modify: `plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/test_jev_runner.py`

**Interfaces:**
- Consumes: Task 7 的 `execute`、`build_pending_call`、paths、`sync_decision_context`
- Produces:
  - `jev_runner.NoPendingCall(RuntimeError)`
  - `jev_runner.AmbiguousAttempt(RuntimeError)`
  - `jev_runner.resume_operation(config, client, current_input_refs, *, allow_new_attempt=False, clock=None) -> dict`
  - `jev_runner.pending_operation_ids(run_dir) -> list[str]`

- [ ] **Step 1: 写失败测试**

在 `test_jev_runner.py` 的 import 块补充：

```python
from jev_runner import (
    AmbiguousAttempt,
    NoPendingCall,
    execute,
    pending_operation_ids,
    resume_operation,
)
```

在文件末尾追加：

```python
class ResumeTests(RunnerCase):
    def _wait_for_key(self):
        client, transport = self.client(environ={})
        result = run_operation(make_request(), self.config, client)
        self.assertEqual(result["status"], "waiting_for_jev_key")
        return transport

    def test_pending_operation_ids_lists_the_waiting_operation(self):
        self._wait_for_key()
        self.assertEqual(pending_operation_ids(self.run_dir), [self.operation_id])

    def test_resume_continues_the_same_operation_after_the_key_appears(self):
        self._wait_for_key()
        client, transport = self.client([TransportResponse(200, success_body(), {})])
        result = resume_operation(
            self.config, client, make_request()["context_refs"]
        )
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(len(transport.calls), 1)
        self.assertFalse(pending_path(self.run_dir, self.operation_id).exists())

    def test_resume_does_not_re_load_knowledge_or_ask_again(self):
        self._wait_for_key()
        client, _ = self.client([TransportResponse(200, success_body(), {})])
        resume_operation(self.config, client, make_request()["context_refs"])
        context = read_decision_context(self.run_dir)
        self.assertEqual(context["mode"], "jev_assisted")
        self.assertEqual(context["selection_status"], "confirmed")

    def test_changed_input_revisions_supersede_the_old_pending_call(self):
        self._wait_for_key()
        client, transport = self.client([TransportResponse(200, success_body(), {})])
        moved = [{"ref_id": "海外绘本/小老鼠迈尔斯/worldview", "kind": "knowledge_page",
                  "revisions": {"node-a": "18"}}]
        result = resume_operation(self.config, client, moved)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_class"], "superseded")
        self.assertEqual(transport.calls, [])
        self.assertFalse(result_path(self.run_dir, self.operation_id).exists())

    def test_resume_without_a_pending_call_is_refused(self):
        client, _ = self.client([TransportResponse(200, success_body(), {})])
        with self.assertRaises(NoPendingCall):
            resume_operation(self.config, client, make_request()["context_refs"])

    def test_a_corrupt_stored_request_is_not_replayed(self):
        # A crash can leave a truncated request.json behind. Replaying it would
        # re-send a request nobody can read, so an unreadable file counts as
        # "nothing to resume" and the caller has to rebuild the operation.
        self._wait_for_key()
        request_path(self.run_dir, self.operation_id).write_text(
            "{not json", encoding="utf-8"
        )
        client, transport = self.client([TransportResponse(200, success_body(), {})])
        with self.assertRaises(NoPendingCall):
            resume_operation(self.config, client, make_request()["context_refs"])
        self.assertEqual(transport.calls, [])

    def test_two_pending_operations_cannot_be_resumed_by_guess(self):
        # decision_context.pending_call has a single slot while the run
        # directory can hold several waiting operations, so the context always
        # describes the most recent one. Resume must enumerate the disk and
        # refuse, never guess which operation the user meant.
        client, _ = self.client(environ={})
        run_operation(make_request(), self.config, client)
        run_operation(
            make_request(operation_instance="batch-002"), self.config, client
        )
        self.assertEqual(
            pending_operation_ids(self.run_dir),
            [self.operation_id, f"{self.operation_id}-batch-002"],
        )
        context = read_decision_context(self.run_dir)
        self.assertEqual(
            context["pending_call"]["operation_id"],
            f"{self.operation_id}-batch-002",
        )
        resume_client, transport = self.client(
            [TransportResponse(200, success_body(), {})]
        )
        with self.assertRaises(NoPendingCall):
            resume_operation(
                self.config, resume_client, make_request()["context_refs"]
            )
        self.assertEqual(transport.calls, [])

    def test_switching_to_llm_dispatches_nothing_and_keeps_the_pending_call(self):
        # "Switch back to the plain LLM" must not be read as "this waiting call
        # is resolved": no request goes out, and the pending call stays visible
        # until the user deals with it.
        self._wait_for_key()
        llm_config = RunnerConfig(
            run_dir=self.config.run_dir,
            policy=self.config.policy,
            execution_mode="llm",
        )
        client, transport = self.client([TransportResponse(200, success_body(), {})])
        with self.assertRaises(ContractError):
            execute(make_request(), llm_config, client)
        self.assertEqual(transport.calls, [])
        self.assertTrue(pending_path(self.run_dir, self.operation_id).is_file())

    def test_a_tampered_request_fingerprint_is_refused(self):
        self._wait_for_key()
        stored = read_json(request_path(self.run_dir, self.operation_id))
        stored["state"] = "被改写过的 state"
        write_atomic(request_path(self.run_dir, self.operation_id), stored)
        client, transport = self.client([TransportResponse(200, success_body(), {})])
        result = resume_operation(self.config, client, make_request()["context_refs"])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_class"], "superseded")
        self.assertEqual(transport.calls, [])

    def test_an_ambiguous_attempt_needs_explicit_consent_to_resend(self):
        client, transport = self.client(error=JevTransportOutcomeUnknown("read timed out"))
        first = run_operation(make_request(), self.config, client)
        self.assertEqual(first["status"], "outcome_unknown")

        retry_client, retry_transport = self.client(
            [TransportResponse(200, success_body(), {})]
        )
        refused = resume_operation(
            self.config, retry_client, make_request()["context_refs"]
        )
        self.assertEqual(refused["status"], "outcome_unknown")
        self.assertEqual(retry_transport.calls, [])
        with self.assertRaises(AmbiguousAttempt):
            resume_operation(
                self.config, retry_client, make_request()["context_refs"],
                allow_new_attempt=True,
            )
        self.assertEqual(retry_transport.calls, [])
```

注意：最后一个断言之后，本任务只要求"未经显式同意绝不重发"；`allow_new_attempt=True` 在 Phase 1 通过抛 `AmbiguousAttempt` 明确拒绝，把"如何建立新 attempt"留给 Phase 4 的对比验收决定，不要在这里发明 attempt id 规则。

- [ ] **Step 2: 运行测试确认失败**

Run: `python plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/test_jev_runner.py`
Expected: FAIL —— `ImportError: cannot import name 'pending_operation_ids'`

- [ ] **Step 3: 实现恢复路径**

在 `jev_runner.py` 末尾追加：

```python
class NoPendingCall(RuntimeError):
    """There is no recoverable pending call for this run."""


class AmbiguousAttempt(RuntimeError):
    """A previous attempt may have reached the service; consent is required."""


def pending_operation_ids(run_dir: Any) -> list[str]:
    root = Path(run_dir) / "jev"
    if not root.is_dir():
        return []
    return sorted(
        path.name
        for path in root.iterdir()
        if path.is_dir() and (path / "pending.json").is_file()
    )


def _refs_equal(left: Any, right: Any) -> bool:
    return canonical_json(list(left or [])) == canonical_json(list(right or []))


def resume_operation(
    config: RunnerConfig,
    client,
    current_input_refs,
    *,
    allow_new_attempt: bool = False,
    clock=None,
) -> dict:
    operation_ids = pending_operation_ids(config.run_dir)
    if not operation_ids:
        raise NoPendingCall("this run has no pending Jev call to resume")
    if len(operation_ids) > 1:
        raise NoPendingCall(
            "this run has more than one pending Jev call: " + ", ".join(operation_ids)
        )
    operation_id = operation_ids[0]
    pending = read_json(pending_path(config.run_dir, operation_id))
    if pending is None:
        raise NoPendingCall(f"pending call for {operation_id} is unreadable")
    request = read_json(request_path(config.run_dir, operation_id))
    if request is None:
        raise NoPendingCall(f"stored request for {operation_id} is unreadable")

    if not _refs_equal(current_input_refs, pending.get("input_refs")):
        return _superseded(request, config, operation_id, "input_revisions_changed")
    if request_fingerprint(request) != pending.get("request_fingerprint"):
        return _superseded(request, config, operation_id, "request_fingerprint_mismatch")
    if pending.get("attempt_status") == "outcome_unknown":
        if not allow_new_attempt:
            return _superseded(request, config, operation_id, "outcome_unknown")
        raise AmbiguousAttempt(
            "a previous attempt may have been billed; Phase 1 does not create "
            "new attempts automatically"
        )
    return execute(request, config, client, clock=clock)


def _superseded(request, config, operation_id, reason) -> dict:
    pending = build_pending_call(request)
    pending["attempt_status"] = "failed"
    result = build_result(
        request=request, status="failed", error_class="superseded",
        attempts=0, elapsed_ms=0,
        price_usd_per_million_input_tokens=(
            config.policy["price_snapshot"]["price_usd_per_million_input_tokens"]
        ),
    )
    result["trace"] = {"superseded_reason": reason}
    validate_result(result)
    write_atomic(pending_path(config.run_dir, operation_id), pending)
    sync_decision_context(
        config, credential_status="available", pending_call=pending,
    )
    return result
```

`_superseded` 使用 `status="failed"` 且 `error_class="superseded"`：它不会产生 `screened_clear`、不会产生答案、不会删除知识，符合 spec §13"不把新输入伪装成旧 benchmark case"。

- [ ] **Step 4: 运行测试确认通过**

Run: `python plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/test_jev_runner.py`
Expected: PASS

- [ ] **Step 5: 运行聚合校验并提交**

Run: `python scripts/run_plugin_tests.py`
Expected: PASS

```bash
git add plugins/picturebook-screenwriter/skills/jev-decision-runtime
git commit -m "feat(jev): resume a pending call from a validated recovery point" -m "A missing key suspends the operation without dispatching; configuring the key locally resumes the same operation, and changed input revisions supersede the stale pending call instead of replaying it." -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 9: 执行租约与 `outcome_unknown` 的终态保护

spec §5.3：同一 `operation_id` 同时只能由一个 runner 持有未过期执行 lease。本地文件租约提供同主机互斥；**它不提供跨主机互斥**，这一点必须如实记录，不得在文档里夸大成分布式锁。

**Files:**
- Modify: `plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/jev_runner.py`
- Modify: `plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/test_jev_runner.py`

**Interfaces:**
- Consumes: Task 7/8 的 paths、`resume_operation`、`execute`
- Produces:
  - `jev_runner.LeaseHeld(RuntimeError)`
  - `jev_runner.Lease`（frozen dataclass：`operation_id`、`holder`、`started_at`、`expires_at`；`to_dict()`）
  - `jev_runner.acquire_lease(config, operation_id, now=None) -> Lease`
  - `jev_runner.release_lease(config, operation_id, holder) -> None`
  - `run_operation` / `resume_operation` 在调用期间持有租约，`finally` 释放

- [ ] **Step 1: 写失败测试**

在 `test_jev_runner.py` 的 import 块补充：

```python
from datetime import datetime, timedelta, timezone

from jev_runner import LeaseHeld, acquire_lease, release_lease
```

在文件末尾追加：

```python
class LeaseTests(RunnerCase):
    def test_acquire_then_release_frees_the_operation(self):
        lease = acquire_lease(self.config, self.operation_id)
        self.assertEqual(lease.holder, "primary")
        release_lease(self.config, self.operation_id, "primary")
        acquire_lease(self.config, self.operation_id)

    def test_a_second_holder_is_refused_while_the_lease_is_active(self):
        acquire_lease(self.config, self.operation_id)
        with self.assertRaises(LeaseHeld):
            acquire_lease(self.config, self.operation_id)

    def test_an_expired_lease_can_be_taken_over(self):
        start = datetime(2026, 9, 23, 10, 30, tzinfo=timezone.utc)
        acquire_lease(
            self.config, self.operation_id,
            now=start,
        )
        later = start + timedelta(minutes=self.config.lease_ttl_minutes + 1)
        lease = acquire_lease(self.config, self.operation_id, now=later)
        self.assertEqual(lease.holder, "primary")

    def test_release_by_another_holder_is_refused(self):
        acquire_lease(self.config, self.operation_id)
        with self.assertRaises(LeaseHeld):
            release_lease(self.config, self.operation_id, "someone-else")

    def test_the_lease_is_released_after_a_successful_run(self):
        client, _ = self.client([TransportResponse(200, success_body(), {})])
        run_operation(make_request(), self.config, client)
        self.assertFalse(lease_path(self.run_dir, self.operation_id).exists())

    def test_the_lease_is_released_after_a_waiting_run(self):
        client, _ = self.client(environ={})
        run_operation(make_request(), self.config, client)
        self.assertFalse(lease_path(self.run_dir, self.operation_id).exists())

    def test_a_run_in_progress_blocks_a_second_runner(self):
        acquire_lease(self.config, self.operation_id)
        client, transport = self.client([TransportResponse(200, success_body(), {})])
        with self.assertRaises(LeaseHeld):
            run_operation(make_request(), self.config, client)
        self.assertEqual(transport.calls, [])


class OutcomeUnknownTests(RunnerCase):
    def test_an_unknown_outcome_keeps_the_pending_call_resumable(self):
        client, _ = self.client(error=JevTransportOutcomeUnknown("read timed out"))
        result = run_operation(make_request(), self.config, client)
        self.assertEqual(result["status"], "outcome_unknown")
        pending = read_json(pending_path(self.run_dir, self.operation_id))
        self.assertEqual(pending["attempt_status"], "outcome_unknown")

    def test_an_unknown_outcome_writes_a_trace_but_no_result(self):
        client, _ = self.client(error=JevTransportOutcomeUnknown("read timed out"))
        run_operation(make_request(), self.config, client)
        self.assertTrue(trace_path(self.run_dir, self.operation_id, 1).is_file())
        self.assertFalse(result_path(self.run_dir, self.operation_id).exists())

    def test_the_lease_is_released_after_an_ambiguous_outcome(self):
        client, _ = self.client(error=JevTransportOutcomeUnknown("read timed out"))
        run_operation(make_request(), self.config, client)
        self.assertFalse(lease_path(self.run_dir, self.operation_id).exists())
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/test_jev_runner.py`
Expected: FAIL —— `ImportError: cannot import name 'acquire_lease'`

- [ ] **Step 3: 实现租约并接入执行路径**

在 `jev_runner.py` 的 `RunnerConfig` 之后加入：

```python
class LeaseHeld(RuntimeError):
    """Another runner holds an unexpired lease for this operation."""


@dataclass(frozen=True)
class Lease:
    operation_id: str
    holder: str
    started_at: str
    expires_at: str

    def to_dict(self) -> dict:
        return {
            "operation_id": self.operation_id,
            "holder": self.holder,
            "started_at": self.started_at,
            "expires_at": self.expires_at,
        }


def _lease_expired(lease: Mapping[str, Any], reference: datetime) -> bool:
    try:
        expires_at = datetime.fromisoformat(str(lease["expires_at"]))
    except (KeyError, TypeError, ValueError):
        return True
    if expires_at.tzinfo is None:
        return True
    return expires_at <= reference


def _reference_time(now: datetime | None) -> datetime:
    return now if now is not None else datetime.now(timezone.utc)


def acquire_lease(config: RunnerConfig, operation_id: str, now: datetime | None = None) -> Lease:
    """Take the per-operation execution lease, creating it exclusively.

    This is a same-host local-file lease. It does not coordinate across hosts.
    """

    path = lease_path(config.run_dir, operation_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    reference = _reference_time(now)
    lease = Lease(
        operation_id=operation_id,
        holder=config.holder,
        started_at=reference.isoformat(timespec="milliseconds"),
        expires_at=(reference + timedelta(minutes=config.lease_ttl_minutes)).isoformat(
            timespec="milliseconds"
        ),
    )
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        existing = read_json(path)
        if existing is None:
            raise LeaseHeld(f"{operation_id} has an unreadable lease file")
        if not _lease_expired(existing, reference):
            raise LeaseHeld(
                f"{operation_id} is held by {existing.get('holder')!r} "
                f"until {existing.get('expires_at')!r}"
            )
        write_atomic(path, lease.to_dict())
        return lease
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(lease.to_dict(), stream, ensure_ascii=False, sort_keys=True)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return lease


def release_lease(config: RunnerConfig, operation_id: str, holder: str) -> None:
    path = lease_path(config.run_dir, operation_id)
    existing = read_json(path)
    if existing is None:
        return
    if existing.get("holder") != holder:
        raise LeaseHeld(
            f"{operation_id} lease is held by {existing.get('holder')!r}, not {holder!r}"
        )
    path.unlink(missing_ok=True)
```

在 import 块补充：

```python
from datetime import datetime, timedelta, timezone
```

把 `run_operation` 与 `resume_operation` 改为持有租约。`run_operation` 替换为：

```python
def run_operation(request, config, client, clock=None, now=None) -> dict:
    operation_id = operation_id_from_request(request)
    lease = acquire_lease(config, operation_id, now=now)
    try:
        return execute(request, config, client, clock=clock)
    finally:
        release_lease(config, operation_id, lease.holder)
```

`resume_operation` 的末行 `return execute(request, config, client, clock=clock)` 替换为：

```python
    lease = acquire_lease(config, operation_id)
    try:
        return execute(request, config, client, clock=clock)
    finally:
        release_lease(config, operation_id, lease.holder)
```

注意：`acquire_lease` 必须在 `pending_operation_ids` / freshness 校验**之前**还是之后？本计划把它放在 freshness 校验之后、`execute` 之前——这样 `superseded` 与 `outcome_unknown` 的拒绝路径不会写租约文件，测试里 `test_the_lease_is_released_after_an_ambiguous_outcome` 仍然成立（该路径经 `execute`，会拿租约并在 `finally` 释放）。

- [ ] **Step 4: 运行测试确认通过**

Run: `python plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/test_jev_runner.py`
Expected: PASS

- [ ] **Step 5: 运行聚合校验并提交**

Run: `python scripts/run_plugin_tests.py`
Expected: PASS

```bash
git add plugins/picturebook-screenwriter/skills/jev-decision-runtime
git commit -m "feat(jev): guard each operation with a single-holder execution lease" -m "One runner at a time may hold an operation; an expired lease can be taken over, and the lease is always released on the way out." -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 10: 运行器 CLI 与技能文档

给运行器一个可被入口技能与知识层调用的命令行入口，并把"密钥不进命令行"这条约束做成**运行时拒绝**，而不只是文档约定。

**Files:**
- Modify: `plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/jev_runner.py`
- Modify: `plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/test_jev_runner.py`
- Modify: `plugins/picturebook-screenwriter/skills/jev-decision-runtime/SKILL.md`

**Interfaces:**
- Consumes: Task 1–9 的全部运行器 API
- Produces:
  - `jev_runner.main(argv=None, environ=None, transport_factory=None, stdout=None, stderr=None) -> int`
  - `jev_runner.CREDENTIAL_ARGUMENT_PREFIXES = ("--api-key", "--apikey", "--api_key", "--token", "--secret", "--authorization", "--bearer")`
  - CLI：`run --request <path> --run-dir <dir> [--policy <path>]`、`resume --run-dir <dir> --input-refs <path> [--policy <path>]`

- [ ] **Step 1: 写失败测试**

在 `test_jev_runner.py` 的 import 块补充：

```python
import io

from jev_runner import CREDENTIAL_ARGUMENT_PREFIXES, main
```

在文件末尾追加：

```python
class CliTests(RunnerCase):
    def _write(self, name, payload):
        path = self.run_dir / name
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def _main(self, argv, client=None, transport=None, **kwargs):
        stdout = io.StringIO()
        stderr = io.StringIO()
        if client is None:
            client, transport = self.client([TransportResponse(200, success_body(), {})])
        code = main(
            argv, environ={API_KEY_ENV: "sk-abc"}, transport_factory=lambda: transport,
            stdout=stdout, stderr=stderr, **kwargs,
        )
        return code, stdout.getvalue(), stderr.getvalue()

    def test_run_prints_the_result_json(self):
        path = self._write("request.json", make_request())
        code, out, _ = self._main(["run", "--request", str(path), "--run-dir", str(self.run_dir)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["status"], "succeeded")

    def test_resume_prints_the_result_json(self):
        client, _ = self.client(environ={})
        run_operation(make_request(), self.config, client)
        refs = self._write("refs.json", make_request()["context_refs"])
        code, out, _ = self._main(
            ["resume", "--run-dir", str(self.run_dir), "--input-refs", str(refs)]
        )
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["status"], "succeeded")

    def test_credential_arguments_are_refused_without_echoing_the_value(self):
        for prefix in CREDENTIAL_ARGUMENT_PREFIXES:
            with self.subTest(prefix=prefix):
                stdout = io.StringIO()
                stderr = io.StringIO()
                code = main(
                    ["run", f"{prefix}=SUPER-SECRET-VALUE", "--run-dir", str(self.run_dir)],
                    environ={}, stdout=stdout, stderr=stderr,
                )
                self.assertEqual(code, 2)
                self.assertNotIn("SUPER-SECRET-VALUE", stderr.getvalue())
                self.assertNotIn("SUPER-SECRET-VALUE", stdout.getvalue())

    def test_a_missing_policy_file_is_reported_as_a_contract_failure(self):
        path = self._write("request.json", make_request())
        code, _, err = self._main(
            ["run", "--request", str(path), "--run-dir", str(self.run_dir),
             "--policy", str(self.run_dir / "nope.json")]
        )
        self.assertEqual(code, 1)
        self.assertIn("error", err.lower())

    def test_usage_errors_exit_two(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        code = main([], environ={}, stdout=stdout, stderr=stderr)
        self.assertEqual(code, 2)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/test_jev_runner.py`
Expected: FAIL —— `ImportError: cannot import name 'CREDENTIAL_ARGUMENT_PREFIXES'`

- [ ] **Step 3: 实现 CLI**

在 `jev_runner.py` 末尾追加：

```python
CREDENTIAL_ARGUMENT_PREFIXES = (
    "--api-key",
    "--apikey",
    "--api_key",
    "--token",
    "--secret",
    "--authorization",
    "--bearer",
)


def _reject_credential_arguments(arguments) -> str | None:
    """Refuse credential flags before argparse can echo their values."""

    for argument in arguments:
        lowered = str(argument).lower()
        for prefix in CREDENTIAL_ARGUMENT_PREFIXES:
            if lowered.startswith(prefix):
                return (
                    f"credentials are not accepted on the command line: {prefix}. "
                    f"Set {API_KEY_ENV} in the environment instead."
                )
    return None


def _build_parser():
    import argparse

    parser = argparse.ArgumentParser(prog="jev_runner.py")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="execute one decision operation")
    run.add_argument("--request", required=True)
    run.add_argument("--run-dir", required=True)
    run.add_argument("--policy")

    resume = subparsers.add_parser("resume", help="resume a pending decision operation")
    resume.add_argument("--run-dir", required=True)
    resume.add_argument("--input-refs", required=True)
    resume.add_argument("--policy")
    return parser


def main(
    argv=None,
    environ=None,
    transport_factory=None,
    stdout=None,
    stderr=None,
) -> int:
    import sys

    arguments = list(sys.argv[1:] if argv is None else argv)
    out = sys.stdout if stdout is None else stdout
    err = sys.stderr if stderr is None else stderr

    refusal = _reject_credential_arguments(arguments)
    if refusal is not None:
        print(refusal, file=err)
        return 2

    parser = _build_parser()
    if not arguments:
        parser.print_usage(err)
        return 2
    try:
        args = parser.parse_args(arguments)
    except SystemExit as exit_error:
        return 2 if exit_error.code else 0

    factory = transport_factory or UrllibTransport
    try:
        policy = load_policy(args.policy or default_policy_path())
        config = RunnerConfig(run_dir=Path(args.run_dir), policy=policy)
        client = JevClient(factory(), environ=environ)
        if args.command == "run":
            request = json.loads(Path(args.request).read_text(encoding="utf-8"))
            result = run_operation(request, config, client)
        else:
            refs = json.loads(Path(args.input_refs).read_text(encoding="utf-8"))
            result = resume_operation(config, client, refs)
    except (ContractError, JevClientError, NoPendingCall, LeaseHeld, AmbiguousAttempt) as error:
        print(json.dumps({"status": "error", "error": str(error)}, ensure_ascii=False), file=err)
        return 1
    except (OSError, ValueError) as error:
        print(json.dumps({"status": "error", "error": str(error)}, ensure_ascii=False), file=err)
        return 1

    print(json.dumps(result, ensure_ascii=False, sort_keys=True), file=out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

在 import 块补充：

```python
from decision_contract import default_policy_path, load_policy
from jev_client import API_KEY_ENV, JevClient, JevClientError, UrllibTransport
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/test_jev_runner.py`
Expected: PASS

- [ ] **Step 5: 补全技能文档的执行段**

在 `plugins/picturebook-screenwriter/skills/jev-decision-runtime/SKILL.md` 末尾追加：

```markdown
## 执行

```bash
python scripts/jev_runner.py run \
    --request <pb-jev-request-v1.json> \
    --run-dir <run_dir> \
    [--policy <decision-policies.json>]

python scripts/jev_runner.py resume \
    --run-dir <run_dir> \
    --input-refs <当前 revision 向量.json> \
    [--policy <decision-policies.json>]
```

- 两个子命令都把 `pb-jev-result-v1` 打到 stdout，成功或进入等待状态返回 0，失败返回 1，用法错误返回 2。
- 凭证只从环境变量 `TYPESAFE_API_KEY` 读取。任何 `--api-key` / `--token` / `--secret` 形式的参数都会被**在解析前**拒绝，且错误信息只回显参数名、不回显参数值。
- `--policy` 省略时使用 `references/decision-policies.json`。
- `resume` 需要调用方提供**当前** revision 向量；与 pending call 中记录的不同即判定 `superseded`，不会改用新输入重跑。

## 强制力分级

本技能的强制力边界见 `docs/ENFORCEMENT.md`：

- `runtime_required`：无 key 不构造请求；endpoint 必须命中 allowlist；redirect 一律拒绝；响应的 `model` 必须等于策略里的 `pinned_model`；租约互斥；终态结果先原子落盘再清除 pending call。
- `script_checked`：pending call 的 fingerprint 与 revision freshness；成本与 token 口径。
- `prompt_only`：是否使用本技能、是否在缺 key 时暂停等待而不是自动回退普通 LLM。
```

- [ ] **Step 6: 运行聚合校验并提交**

Run: `python scripts/run_plugin_tests.py`
Expected: PASS

```bash
git add plugins/picturebook-screenwriter/skills/jev-decision-runtime
git commit -m "feat(jev): add the runner CLI and refuse credential arguments" -m "Expose run and resume as documented commands and reject any credential-shaped flag before the argument parser can echo its value." -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 11: 入口 Execution Choice Gate

spec §5：入口技能匹配到请求后，第一件事就是建立执行选择；在获得选择前不得做任何实质工作。这是 `prompt_only` 的强制力，必须同时写进技能指令与插件契约，并由契约测试固定"选择门在意图分类之前"。

**Files:**
- Modify: `plugins/picturebook-screenwriter/skills/picturebook-screenwriter/SKILL.md`
- Modify: `plugins/picturebook-screenwriter/config/plugin-contract.json`
- Modify: `plugins/picturebook-screenwriter/tests/test_skill_contract.py`
- Modify: `plugins/picturebook-screenwriter/tests/test_plugin_contract.py`

**Interfaces:**
- Consumes: Task 3 的 `stage_dag.DECISION_CONTEXT_SCHEMA`
- Produces:
  - `plugin-contract.json` 顶层 `execution_choice` 块
  - 入口 `SKILL.md` 的 `## Execution Choice Gate` 段

- [ ] **Step 1: 写失败测试**

在 `plugins/picturebook-screenwriter/tests/test_skill_contract.py` 末尾（`if __name__ == "__main__":` 之前）追加：

```python
class ExecutionChoiceGateTests(unittest.TestCase):
    def test_entry_asks_the_execution_choice_before_anything_else(self):
        text = ENTRY_SKILL.read_text(encoding="utf-8")
        self.assertIn("## Execution Choice Gate", text)
        self.assertIn("本次是否启用 Jev 辅助？", text)
        self.assertLess(
            text.index("## Execution Choice Gate"),
            text.index("**Intent**"),
            "执行选择门必须排在意图分类之前",
        )

    def test_entry_records_the_choice_as_decision_context(self):
        text = ENTRY_SKILL.read_text(encoding="utf-8")
        self.assertIn("pb-decision-context-v1", text)
        self.assertIn("waiting_for_execution_choice", text)

    def test_entry_never_asks_for_a_key_in_the_chat(self):
        text = ENTRY_SKILL.read_text(encoding="utf-8")
        self.assertIn("TYPESAFE_API_KEY", text)
        self.assertIn("请不要把密钥粘贴到对话中", text)

    def test_entry_does_not_probe_the_key_on_the_llm_path(self):
        text = ENTRY_SKILL.read_text(encoding="utf-8")
        self.assertIn("不得探测", text)
```

在 `plugins/picturebook-screenwriter/tests/test_plugin_contract.py` 末尾（`if __name__ == "__main__":` 之前）追加一个新的测试类——该文件目前只有一个 `PluginContractTests` 类，追加新类比在既有类里找插入点更稳妥：

```python
class JevExecutionChoiceContractTests(unittest.TestCase):
    def _contract(self):
        return json.loads(CONTRACT.read_text(encoding="utf-8"))

    def test_contract_declares_execution_choice_gate(self):
        self.assertEqual(
            self._contract()["execution_choice"],
            {
                "gate_position": "before_intent_classification",
                "question_scope": "once_per_root_run",
                "modes": ["llm", "jev_assisted"],
                "pending_state": "waiting_for_execution_choice",
                "decision_context_schema": "pb-decision-context-v1",
            },
        )

    def test_contract_declares_jev_runtime_boundary(self):
        runtime = self._contract()["jev_runtime"]
        self.assertEqual(runtime["endpoint"], "https://api.typesafe.ai/v1/systemone")
        self.assertEqual(runtime["credential_env"], "TYPESAFE_API_KEY")
        self.assertEqual(runtime["credential_sources"], ["environment"])
        self.assertEqual(runtime["key_logging"], "forbidden")
        self.assertEqual(runtime["base_url_override"], "forbidden")
        self.assertEqual(runtime["redirects"], "disabled")
        self.assertEqual(runtime["pinned_model"], "jev-1.13.0")
        self.assertEqual(runtime["moving_model_aliases"], "forbidden")
        self.assertEqual(
            runtime["operations"], ["knowledge_relevance", "text_quality_prefilter"]
        )

    def test_contract_registers_the_runtime_skill(self):
        self.assertIn("jev-decision-runtime", self._contract()["skills"])

    def test_execution_choice_schema_matches_the_runtime_constant(self):
        self.assertEqual(
            self._contract()["execution_choice"]["decision_context_schema"],
            stage_dag.DECISION_CONTEXT_SCHEMA,
        )
```

`test_plugin_contract.py` 已在模块顶层 `import json`、`import stage_dag` 并定义 `CONTRACT`，不需要新增 import。

- [ ] **Step 2: 运行测试确认失败**

Run: `python plugins/picturebook-screenwriter/tests/test_skill_contract.py`
Expected: FAIL —— `AssertionError: '## Execution Choice Gate' not found`

- [ ] **Step 3: 在契约中声明执行选择门**

编辑 `plugins/picturebook-screenwriter/config/plugin-contract.json`，在顶层加入 `execution_choice` 块（与 `jev_runtime` 同级）：

```json
  "execution_choice": {
    "gate_position": "before_intent_classification",
    "question_scope": "once_per_root_run",
    "modes": [
      "llm",
      "jev_assisted"
    ],
    "pending_state": "waiting_for_execution_choice",
    "decision_context_schema": "pb-decision-context-v1"
  },
```

- [ ] **Step 4: 在入口技能中加入选择门**

编辑 `plugins/picturebook-screenwriter/skills/picturebook-screenwriter/SKILL.md`，在 `# Picture Book Screenwriter` 的引言段之后、`## Workflow` 之前插入：

```markdown
## Execution Choice Gate

本技能匹配到用户请求后，**第一件事**是建立执行选择。在拿到选择之前，不得做意图分类、简报追问、飞书或本地知识读取、子 Agent 派发、创作或质检、外部 API 调用或文件写入。工作流保持 `waiting_for_execution_choice`。

第一响应只问一次，不得与简报问题合并：

```text
本次是否启用 Jev 辅助？

- 不启用：沿用普通 LLM 完整流程。
- 启用：将相关故事文本和知识片段发送给 TypeSafe Jev，
  用于知识筛选及文本质检预筛；创作、解释性终审和修改建议仍由普通 LLM 完成。
  尚未校准的检查会保留普通 LLM 全量复核，用于比较和校准。
  若本机尚未配置 Jev key，选择后会暂停并引导你在本机安全配置，再从原任务继续。
```

规则：

1. 只接受 `llm` 与 `jev_assisted` 两个值，并构造 `pb-decision-context-v1` 附加到 run manifest 和子 Agent task envelope。
2. 选择作用于一个 root run 及其 revision runs；同一 root run 内不重复询问，新的顶层创作、审稿、知识或插画请求必须重新询问。
3. 选择 `llm` 时**不得探测** `TYPESAFE_API_KEY`，也不得加载 Jev 运行器；只有选择 `jev_assisted` 后才检查凭证。
4. 用户选择 `jev_assisted` 但当前意图没有首轮支持的 Jev 操作时，仍记录选择，并明确说明该阶段暂时沿用普通 LLM 或确定型脚本。
5. 用户未回答时保持 `waiting_for_execution_choice`，不继续执行。
6. 缺 key 时进入 `waiting_for_jev_key`，使用以下固定提示，**不得**要求用户把密钥粘贴到对话中，也不得自动回退普通 LLM：

   ```text
   尚未检测到 TYPESAFE_API_KEY。请在运行 Codex 的本机环境中安全配置该变量，
   然后回复“已配置”；我会从当前待执行步骤继续。请不要把密钥粘贴到对话中。
   如果当前 Codex 进程无法读取新设置，请重启 Codex，回到本任务后回复“已配置”。
   ```

7. 用户本机配置后回复“已配置”时，先校验输入 revision 与 fingerprint，再从原待执行 operation 续跑；不得重新询问执行选择，也不得重复已完成的知识加载或确定型扫描。
8. 请求已发出但无法判断服务端是否完成时标记 `outcome_unknown`，不得自动重发。
9. 只有用户明确要求切换时，才记录路径切换并把 `fallback_used` 记为 true。
10. 不得把密钥写进插件目录、manifest、`decision-context.json`、trace 或日志。
```

`**Intent**` 这个字符串在 `## Workflow` 的第 1 步里已经存在（`1. **Intent**: classify ...`），插入位置必须保证 `## Execution Choice Gate` 出现在它之前。

- [ ] **Step 5: 运行测试确认通过**

Run: `python plugins/picturebook-screenwriter/tests/test_skill_contract.py`
Expected: PASS

Run: `python plugins/picturebook-screenwriter/tests/test_plugin_contract.py`
Expected: PASS

- [ ] **Step 6: 运行聚合校验并提交**

Run: `python scripts/run_plugin_tests.py`
Expected: PASS

```bash
git add plugins/picturebook-screenwriter/skills/picturebook-screenwriter/SKILL.md plugins/picturebook-screenwriter/config/plugin-contract.json plugins/picturebook-screenwriter/tests/test_skill_contract.py plugins/picturebook-screenwriter/tests/test_plugin_contract.py
git commit -m "feat(jev): gate the entry workflow on an explicit execution choice" -m "The entry skill now asks once per root run whether to use the Jev assisted path, records the answer as decision_context, and never probes the key on the plain LLM path." -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 12: 端到端集成与脱敏

把两条路径串起来验证：不选 Jev 不做任何 Jev 动作；选了 Jev 且缺 key 时进入等待、本机配置后续跑；任何写盘文件都不含密钥或草稿正文。

**Files:**
- Create: `plugins/picturebook-screenwriter/tests/test_jev_phase1_integration.py`

**Interfaces:**
- Consumes: Task 1–11 的全部公开 API
- Produces: 无（只做验证）

- [ ] **Step 1: 写集成测试**

创建 `plugins/picturebook-screenwriter/tests/test_jev_phase1_integration.py`：

```python
"""Phase 1 integration: both execution paths, credential recovery, redaction."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
RUNTIME_SCRIPTS = ROOT / "skills" / "jev-decision-runtime" / "scripts"
sys.path.insert(0, str(RUNTIME_SCRIPTS))

from decision_contract import load_policy, default_policy_path  # noqa: E402
from jev_client import (  # noqa: E402
    API_KEY_ENV,
    FakeTransport,
    JevClient,
    JevEndpointError,
    TransportResponse,
    UrllibTransport,
)
from jev_runner import (  # noqa: E402
    RunnerConfig,
    build_decision_context_for_run,
    operation_id_for,
    pending_path,
    read_decision_context,
    read_json,
    result_path,
    resume_operation,
    run_operation,
    sync_decision_context,
    trace_path,
    write_atomic,
)

RUN_ID = "20260923-integration-0001"
OPERATION = "knowledge_relevance"
MARKER_STATE = "小红帽把蛋糕递给了奶奶，奶奶说谢谢你"
API_KEY = "sk-integration-secret"


def make_request():
    return {
        "schema_version": "pb-jev-request-v1",
        "run_id": RUN_ID,
        "operation": OPERATION,
        "model": "jev-1.13.0",
        "policy_version": "knowledge-relevance-v1",
        "state": MARKER_STATE,
        "questions": {"relevant": {"type": "noul", "instructions": "是否相关？"}},
        "context_refs": [
            {"ref_id": "海外绘本/小老鼠迈尔斯/worldview", "kind": "knowledge_page",
             "revisions": {"node-a": "17"}}
        ],
        "benchmark_case_id": "sha256:" + "0" * 64,
    }


def success_body():
    return json.dumps({
        "model": "jev-1.13.0",
        "answers": {"relevant": {"type": "noul", "noul": 0.91}},
        "usage": {"input_tokens": 296, "output_tokens": 20},
    })


class Phase1IntegrationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self._tmp.name)
        self.config = RunnerConfig(
            run_dir=self.run_dir, policy=load_policy(default_policy_path())
        )
        self.operation_id = operation_id_for(RUN_ID, OPERATION)

    def tearDown(self):
        self._tmp.cleanup()

    def test_the_plain_llm_path_never_touches_the_runtime(self):
        context = build_decision_context_for_run(
            mode="llm", external_text_processing_acknowledged=False,
            selected_at="2026-09-23T10:30:00+08:00",
        )
        write_atomic(self.run_dir / "decision-context.json", context)
        self.assertFalse((self.run_dir / "jev").exists())
        self.assertFalse((self.run_dir / "decision-context.json").read_text(
            encoding="utf-8"
        ).count(API_KEY_ENV))

    def test_missing_key_then_local_key_then_resume(self):
        transport = FakeTransport(responses=[TransportResponse(200, success_body(), {})])

        waiting = run_operation(
            make_request(), self.config,
            JevClient(transport, environ={}, sleep=lambda _: None),
        )
        self.assertEqual(waiting["status"], "waiting_for_jev_key")
        self.assertEqual(transport.calls, [])
        context = read_decision_context(self.run_dir)
        self.assertEqual(context["credential_status"], "waiting_for_jev_key")
        self.assertIsNotNone(context["pending_call"])
        self.assertTrue(
            context["pending_call"]["request_fingerprint"].startswith("sha256:")
        )
        self.assertEqual(context["mode"], "jev_assisted")

        resumed = resume_operation(
            self.config,
            JevClient(transport, environ={API_KEY_ENV: API_KEY}, sleep=lambda _: None),
            make_request()["context_refs"],
        )
        self.assertEqual(resumed["status"], "succeeded")
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(
            read_json(result_path(self.run_dir, self.operation_id))["status"], "succeeded"
        )
        self.assertFalse(pending_path(self.run_dir, self.operation_id).exists())

    def test_recovery_does_not_repeat_completed_stages(self):
        transport = FakeTransport(responses=[TransportResponse(200, success_body(), {})])
        run_operation(make_request(), self.config,
                      JevClient(transport, environ={}, sleep=lambda _: None))
        operation_dir = self.run_dir / "jev" / self.operation_id
        request_before = read_json(operation_dir / "request.json")
        refs_digest_before = json.dumps(request_before["context_refs"], sort_keys=True)

        resume_operation(
            self.config,
            JevClient(transport, environ={API_KEY_ENV: API_KEY}, sleep=lambda _: None),
            make_request()["context_refs"],
        )
        request_after = read_json(operation_dir / "request.json")
        self.assertEqual(
            json.dumps(request_after["context_refs"], sort_keys=True), refs_digest_before
        )

    def test_changed_knowledge_revision_does_not_replay_the_old_request(self):
        transport = FakeTransport(responses=[TransportResponse(200, success_body(), {})])
        run_operation(make_request(), self.config,
                      JevClient(transport, environ={}, sleep=lambda _: None))
        moved = [{"ref_id": "海外绘本/小老鼠迈尔斯/worldview", "kind": "knowledge_page",
                  "revisions": {"node-a": "99"}}]
        result = resume_operation(
            self.config,
            JevClient(transport, environ={API_KEY_ENV: API_KEY}, sleep=lambda _: None),
            moved,
        )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_class"], "superseded")
        self.assertEqual(transport.calls, [])

    def test_both_paths_share_a_benchmark_case_id(self):
        transport = FakeTransport(responses=[TransportResponse(200, success_body(), {})])
        run_operation(make_request(), self.config,
                      JevClient(transport, environ={API_KEY_ENV: API_KEY}, sleep=lambda _: None))
        trace = read_json(trace_path(self.run_dir, self.operation_id, 1))
        self.assertEqual(trace["benchmark_case_id"], make_request()["benchmark_case_id"])
        self.assertEqual(trace["execution_mode"], "jev_assisted")

    def test_no_written_file_leaks_the_key(self):
        transport = FakeTransport(responses=[TransportResponse(200, success_body(), {})])
        run_operation(make_request(), self.config,
                      JevClient(transport, environ={API_KEY_ENV: API_KEY}, sleep=lambda _: None))
        for path in self.run_dir.rglob("*"):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=str(path.relative_to(self.run_dir))):
                self.assertNotIn(API_KEY, text)
                self.assertNotIn("Authorization", text)

    def test_the_state_body_only_lives_in_the_persisted_request(self):
        # The whole point of the run directory layout: story text lands in
        # exactly one file, the request the resume path needs, and never in the
        # pending descriptor, the decision context, the trace or the result.
        transport = FakeTransport(responses=[TransportResponse(200, success_body(), {})])
        run_operation(make_request(), self.config,
                      JevClient(transport, environ={API_KEY_ENV: API_KEY}, sleep=lambda _: None))
        carriers = sorted(
            str(path.relative_to(self.run_dir))
            for path in self.run_dir.rglob("*")
            if path.is_file() and MARKER_STATE in path.read_text(encoding="utf-8")
        )
        self.assertEqual(carriers, [f"jev/{self.operation_id}/request.json"])

    def test_the_real_transport_refuses_a_non_allowlisted_endpoint(self):
        with self.assertRaises(JevEndpointError):
            UrllibTransport().send("https://evil.example/v1/systemone", {}, b"{}", 1.0)

    def test_context_sync_keeps_the_schema_valid_through_every_transition(self):
        transport = FakeTransport(responses=[TransportResponse(200, success_body(), {})])
        run_operation(make_request(), self.config,
                      JevClient(transport, environ={}, sleep=lambda _: None))
        sync_decision_context(
            self.config, credential_status="available", pending_call=None,
            resume_cursor="after_execution_choice",
        )
        final = read_decision_context(self.run_dir)
        self.assertEqual(final["credential_status"], "available")
        self.assertEqual(final["selection_status"], "confirmed")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行集成测试**

Run: `python plugins/picturebook-screenwriter/tests/test_jev_phase1_integration.py`
Expected: PASS

- [ ] **Step 3: 运行聚合校验并提交**

Run: `python scripts/run_plugin_tests.py`
Expected: PASS

```bash
git add plugins/picturebook-screenwriter/tests/test_jev_phase1_integration.py
git commit -m "test(jev): cover both execution paths, credential recovery, and redaction" -m "Verified end to end with a fake transport: no dispatch without a key, resume from the validated recovery point, supersede on changed revisions, and no key or draft text in any written file." -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 13: 强制力分级、变更日志与发布说明

`docs/ENFORCEMENT.md` 是发布前的强制力契约；新增的每一个门都必须如实归类，不得把 `prompt_only` 写成运行时强制。

**Files:**
- Modify: `docs/ENFORCEMENT.md`
- Modify: `docs/CHANGELOG.md`
- Modify: `docs/RELEASE.md`
- Modify: `plugins/picturebook-screenwriter/README.md`
- Modify: `README.md`
- Modify: `plugins/picturebook-screenwriter/tests/test_plugin_contract.py`

**Interfaces:**
- Consumes: Task 1–12 的全部实现
- Produces: 无（文档与发布契约）

- [ ] **Step 1: 写失败测试**

在 `plugins/picturebook-screenwriter/tests/test_plugin_contract.py` 末尾（`if __name__ == "__main__":` 之前）追加另一个测试类：

```python
class JevPhase1DocumentationTests(unittest.TestCase):
    def test_enforcement_matrix_documents_the_jev_gates(self):
        text = ENFORCEMENT.read_text(encoding="utf-8")
        for required in (
            "jev_runner.py",
            "jev_client.py",
            "waiting_for_jev_key",
            "outcome_unknown",
            "model_version_mismatch",
            "request.json",
        ):
            with self.subTest(required=required):
                self.assertIn(required, text)

    def test_enforcement_matrix_does_not_overclaim_the_lease(self):
        text = ENFORCEMENT.read_text(encoding="utf-8")
        self.assertIn("不提供跨主机互斥", text)

    def test_plugin_readme_documents_the_jev_credential_environment(self):
        text = PLUGIN_README.read_text(encoding="utf-8")
        self.assertIn("TYPESAFE_API_KEY", text)
        self.assertIn("jev-decision-runtime", text)
        self.assertIn("不得把密钥粘贴到对话中", text)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python plugins/picturebook-screenwriter/tests/test_plugin_contract.py`
Expected: FAIL —— `AssertionError: 'jev_runner.py' not found`

- [ ] **Step 3: 扩充强制力矩阵**

编辑 `docs/ENFORCEMENT.md`，在既有矩阵表格的末尾追加以下行：

```markdown
| 缺 `TYPESAFE_API_KEY` 时不构造请求 | `runtime_required` | `skills/jev-decision-runtime/scripts/jev_client.py` | `read_api_key` 视为空即返回 `waiting_for_jev_key`，transport 不被调用。 |
| Jev endpoint allowlist 与禁用 redirect | `runtime_required` | `skills/jev-decision-runtime/scripts/jev_client.py` | 非 `https://api.typesafe.ai/v1/systemone` 的 URL 被拒绝；3xx 不被跟随。 |
| 单个 operation 的执行租约 | `runtime_required` | `skills/jev-decision-runtime/scripts/jev_runner.py` | 未过期租约持有期间第二次 acquire 抛 `LeaseHeld`。**这是同主机本地文件租约，不提供跨主机互斥。** |
| 终态结果先原子落盘再清除 pending call | `runtime_required` | `skills/jev-decision-runtime/scripts/jev_runner.py` | `result.json` 未写入前 `pending.json` 不被删除。 |
| 响应模型版本必须等于策略的 `pinned_model` | `runtime_required` | `skills/jev-decision-runtime/scripts/jev_runner.py` | 响应 `model` 与 `pinned_model` 不一致时判 `model_version_mismatch`，不产出 succeeded 结果。 |
| 只有 `request.json` 落盘携带 `state` 正文 | `runtime_required` | `skills/jev-decision-runtime/scripts/jev_runner.py` | `pending.json` / `decision-context.json` / trace / result 均不含正文；`request.json` 是可恢复所需的唯一例外，且不含凭证。 |
| 命令行凭证参数拒绝 | `runtime_required` | `skills/jev-decision-runtime/scripts/jev_runner.py` | 任何 `--api-key` / `--token` / `--secret` 形式参数在解析前被拒绝，且不回显值。 |
| pending call 的 fingerprint 与 revision freshness | `script_checked` | `skills/jev-decision-runtime/scripts/jev_runner.py` | 恢复前比对 fingerprint 与 revision 向量；不一致即判 `superseded`，但不阻止调用方伪造一致的输入。 |
| Jev 请求/结果/trace schema | `script_checked` | `skills/jev-decision-runtime/scripts/decision_contract.py` | 非法请求、非法结果、缺失答案题 ID 均抛 `ContractError`。 |
| 成本与 token 口径 | `script_checked` | `skills/jev-decision-runtime/scripts/telemetry.py` | 成本用 Decimal 定点；usage 缺失时 token 与成本为 `null`，不按字符数伪造。 |
| 第一响应必定询问执行选择 | `prompt_only` | 入口 Skill 指令 | 脚本无法证明"第一件事"真的是第一件事。 |
| 缺 key 时暂停等待而非自动回退普通 LLM | `prompt_only` | 入口与 `jev-decision-runtime` 指令 | 直接调用运行器的调用方不会被阻止。 |
| 只在用户明确选择后才调用 Jev | `prompt_only` | 入口 Skill 指令 | 没有 host 级阻止。 |
```

- [ ] **Step 4: 更新 CHANGELOG**

在 `docs/CHANGELOG.md` 的 `## [Unreleased]` 段内，`### Added` 列表末尾追加：

```markdown
- Jev 辅助决策层的共享基础设施：显式执行选择门、`pb-decision-context-v1` 传播、凭证据等待与恢复点、执行租约、原子终态、Decimal 成本估算与 benchmark case 对齐。
```

在 `### Changed` 列表末尾追加：

```markdown
- 入口工作流新增 `## Execution Choice Gate`，位于意图分类之前，作为每次顶层请求的第一步。
```

- [ ] **Step 5: 更新发布检查清单**

在 `docs/RELEASE.md` 的 `## Explicit live gates` 列表末尾追加一条：

```markdown
6. Jev 相关的 live smoke test 只在显式提供 `TYPESAFE_API_KEY` 时运行，不属于默认离线测试集合；密钥不得进入命令历史、日志或导出。
```

- [ ] **Step 6: 更新插件 README**

编辑 `plugins/picturebook-screenwriter/README.md`：

1. 在 `## 已支持` 列表的 `- \`lexile-check\`：仅使用用户提供的实测结果` 之前插入：

```markdown
- `jev-decision-runtime`：共享 Jev 决策运行器；只在用户选择 Jev 辅助路径后调用，负责凭证门、请求契约、重试、恢复点、租约、原子终态与成本估算
```

2. 在 `## 暂不支持` 列表末尾追加：

```markdown
- Jev 不参与生成、润色、修改建议或插画提示词；知识相关性筛选与文本质量预筛的 operation 策略在后续阶段落地
```

3. 在文件末尾新增一节：

```markdown
## Jev 辅助路径

入口工作流的第一件事是询问是否启用 Jev 辅助。选择启用后，相关故事文本和知识片段会发送给 TypeSafe Jev 做知识筛选与文本质检预筛；创作、解释性终审和修改建议仍由普通 LLM 完成。

凭证只从环境变量 `TYPESAFE_API_KEY` 读取。若本机尚未配置，工作流会暂停并提示在本机环境中安全设置该变量，然后回复“已配置”从原任务继续：

```powershell
$env:TYPESAFE_API_KEY = "<your-key>"
```

**不得把密钥粘贴到对话中**，也不要把它写进配置、仓库或插件目录。endpoint 固定为 `https://api.typesafe.ai/v1/systemone`，不接受 base URL 覆盖，禁用 redirect。模型固定为 `jev-1.13.0`，不使用会漂移的 `latest` 别名。

未校准期间所有 operation 均为 `experimental`：`screened_clear` 只是 Jev 的候选结论，不缩减普通 LLM 的复核范围。
```

- [ ] **Step 7: 更新仓库 README**

编辑 `README.md` 的 `The plugin supports:` 列表，在 `- Feishu authoritative knowledge retrieval and synchronized ingestion` 之前插入：

```markdown
- Explicit per-run choice between the plain LLM path and a Jev-assisted path (TypeSafe Jev) for knowledge filtering and text-quality pre-screening
```

并在 `## Verify locally` 之后新增一节：

```markdown
## Jev-assisted path

The entry workflow asks once per root run whether to use the Jev-assisted path. If you enable it, set the credential in your local environment — never in the chat, a config file, or the repository:

```bash
export TYPESAFE_API_KEY="<your-key>"
```

The plugin pins `jev-1.13.0` and the endpoint `https://api.typesafe.ai/v1/systemone`.
```

- [ ] **Step 8: 运行测试确认通过**

Run: `python plugins/picturebook-screenwriter/tests/test_plugin_contract.py`
Expected: PASS

- [ ] **Step 9: 运行聚合校验并提交**

Run: `python scripts/run_plugin_tests.py`
Expected: PASS

```bash
git add -f docs/ENFORCEMENT.md docs/CHANGELOG.md docs/RELEASE.md
git add plugins/picturebook-screenwriter/README.md README.md plugins/picturebook-screenwriter/tests/test_plugin_contract.py
git status
git commit -m "docs(jev): record the phase 1 enforcement levels and credential setup" -m "Classify every new gate honestly, note that the execution lease is same-host only and does not provide cross-host mutual exclusion, and document the TypeSafe credential environment for both READMEs." -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

`git status` 那一步是必要的：`docs/` 被忽略，只有 `git add -f` 才会暂存；确认三个文档确实出现在 "Changes to be committed" 里再提交。

---

## 完成后的状态

Phase 1 结束时，插件具备：

- 入口工作流第一步的执行选择门，选择以 `pb-decision-context-v1` 传播到 run manifest 与子 Agent task envelope。
- 一条可独立调用的共享运行器：凭证门、endpoint allowlist、禁用 redirect、有界重试、错误分类、执行租约、恢复点与 `superseded` 判定、原子终态、trace 与 Decimal 成本估算。
- 契约校验覆盖 `pb-jev-request-v1` / `pb-jev-result-v1` / `pb-decision-context-v1` / `pb-jev-policy-v1`，其中 `routes` 词表已定义但输出为空数组。
- `docs/ENFORCEMENT.md` 中每个新门都有如实分级。

**尚未实现（后续阶段）：** 路由计算（Phase 2/3 的 `question_templates` 与 `routing` 表）、知识分块与 required 标记（Phase 2）、`project_proxy` / `project_authority` 分层（Phase 3）、中文标注样本与阈值校准（Phase 3）、CC Switch 对比报告（Phase 4）。

---

## Self-Review

**1. Spec coverage（spec §15 Phase 1 的每一条）**

| spec 要求 | 覆盖任务 |
|---|---|
| 入口执行选择门 | Task 11 |
| `decision_context` 传播 | Task 3 |
| 共享 Jev utility skill 与 HTTP client | Task 1、Task 5 |
| `waiting_for_jev_key` 凭证门、恢复点和安全提示 | Task 5、Task 7、Task 8、Task 11 |
| pending call fingerprint、revision freshness、lease 与原子终态 | Task 3（契约）、Task 7（原子终态）、Task 8（fingerprint/freshness）、Task 9（lease） |
| 生产 endpoint allowlist 与隔离真实凭证的 fake transport | Task 5 |
| 请求/响应/trace 契约 | Task 1、Task 3、Task 4 |
| 计时、usage、成本估算和 benchmark case ID | Task 4 |
| fake transport、错误处理和安全测试 | Task 5、Task 6、Task 12 |

spec §17 的后续扩展点（`collision_disambiguation` / `illustration_risk_prefilter` / `staging_evidence_check` / `revision_impact_classification`）**有意不在本计划内**，符合 spec 自身把它们列为后续扩展的规定。

**2. Placeholder scan**

已逐任务检查：无 `TBD` / `TODO` / "implement later" / "add error handling" 之类措辞。`decision-policies.json` 的 `routing: {}` 与 `routes: []` 不是占位符，而是 Phase 1 的既定输出（路由表由 Phase 2/3 的 operation 策略提供），并已由 `validate_policy` 与 `validate_result` 的真实校验固定下来。

**3. Type consistency**

- `operation_id_for(run_id, operation, instance="")` 在 Task 7 定义，`operation_id_from_request` 从请求读取同名的可选 `operation_instance`；Task 10/12 一致使用。无 instance 时 `operation_id == f"{run_id}-{operation}"`
- `routes` 是**按 item**（知识块 / 页面 / 红线）而非按 question 的：Task 1 的 `_validate_routes` 要求 `item_id`，因为一条路由可以由多个答案共同决定；Phase 2/3 填充它
- Phase 1 的 `routing` 表校验为"必须为空"：路由规则无法在问题存在之前表达，因此按-operation 的路由 schema 由 Phase 2/3 随各自的问题一起定义
- `build_pending_call(request)` 在 Task 3 的契约校验下（`operation_id` / `operation` / `request_fingerprint` / `policy_version` / `requested_model` / `attempt_status` / `input_refs`）于 Task 7 实现，Task 8/9 复用
- `CallOutcome.status` 取值 `succeeded` / `failed` / `waiting_for_jev_key` / `waiting_for_jev_access` / `outcome_unknown` 在 Task 5/6 定义，Task 7 的 `_ATTEMPT_STATUS_FOR_OUTCOME` 与 `_CREDENTIAL_STATUS_FOR_OUTCOME` 覆盖全部五值（内部信号 `"retry"` 在 Task 6 说明为客户端私有，不进入结果）
- `Stopwatch.elapsed_ms` 在 Task 4 定义，Task 7 使用；`estimate_usage` 三元组返回签名在 Task 4/7 一致
- `validate_result` 在 Task 1 定义，Task 7 (`build_result`)、Task 8 (`_superseded`) 复用；`_superseded` 额外设置的 `result["trace"]` 对 `status="failed"` 合法（Task 1 只禁止 waiting 状态携带 trace）
- `sync_decision_context` 的 `resume_cursor` 使用 `operation_cursor(operation_id)`，与 Task 3 的 `validate_resume_cursor` 词表一致

**4. Review Focus**

开头的五条都落成了会先失败的测试：正文只允许落在 `request.json`（Task 7 `test_only_the_persisted_request_carries_the_state_body`、Task 12 `test_the_state_body_only_lives_in_the_persisted_request`）；响应模型版本必须匹配 `pinned_model`（Task 7 `test_a_different_resolved_model_is_refused`）；损坏的 `request.json` 不被重放（Task 8 `test_a_corrupt_stored_request_is_not_replayed`）；两个 pending 时拒绝猜测（Task 8 `test_two_pending_operations_cannot_be_resumed_by_guess`）；切回普通 LLM 不发请求、也不清 pending（Task 8 `test_switching_to_llm_dispatches_nothing_and_keeps_the_pending_call`）。
