---
name: pre_output-baseline
description: pre_output 槽位的全产物类型兜底技能，先做廉价代理扫描，再做语义判定。
---

# Pre Output Baseline

## Medium Routing

### picturebook

使用 `../craft-benchmark-check/SKILL.md` 获取确定性指标，并对权威红线、禁忌词、称呼一致性和插画描述做零假阴性扫描。

### shortdrama / tv_longform

运行选中类型包声明的廉价代理与结构化检查；不调用绘本工艺基准，也不扫描插画描述，除非选中类型包显式声明可选插画工作流。

## Stage 2: Semantic Review

对每个 FLAG 逐条判定 `PASS`、`WARN` 或 `FAIL`，必须引用权威来源。项目权威 FAIL 阻断，工艺基准 FAIL 不阻断但必须向用户说明。

## Output

输出 FLAG 表格、判定结果、阻断建议和来源。

## Not In Scope

- 本技能不生成图片，不写入文件，不跳过权威 FAIL。
- 本技能不替代 quality-baseline 的读者视角和跨产物一致性检查。
