---
name: pre_create-baseline
description: pre_create 槽位的全产物类型兜底技能，用于复核简报完整性；只报告缺口，不猜默认值。
---

# Pre Create Baseline

## Scope

适用于所有 active medium 的 `positioning`、`topic`、`worldview`、`character`、`outline` 和 `script`。本技能是默认兜底，不承载项目专属规则。

## Medium Routing

### picturebook

复核目标年龄段、主题方向、页数预期、文字量、文体偏好、禁忌清单和参考作品；`content-spec` 优先沿用绘本权威知识的定义。

### shortdrama / tv_longform

复核主题方向、选中的 `medium_id` 与类型包、系列/项目/季/集上下文、单集时长、集数或段落预期、文体偏好、禁忌清单和参考作品；不得把绘本页数预期套用到非绘本项目。

## Workflow

1. 读取用户已提供的简报要素，并按上方 Medium Routing 选择对应媒介字段。
2. 对照权威知识中的 `content-spec`、世界观、角色和纠正登记册。
3. 对每个要素输出“有来源”或“缺口”。
4. 缺口必须交回用户补充或显式豁免；本技能不猜默认值。

## Output

```markdown
## pre_create 基线检查

- 目标年龄段：有来源 / 缺口
- 主题方向：有来源 / 缺口
- 页数预期：有来源 / 缺口
```

短剧与长篇连续剧输出对应字段，例如单集时长、季/集上下文和类型包要求的结构要素。

## Not In Scope

- 本技能不填充缺失简报，不新增角色、世界观或数值约束。
- 本技能不写入文件，不修改权威知识，不替代项目专属规则。
