# 飞书知识库只读提取协议

## 适用边界

本协议只服务 `wiki-ingest` 的原始资料提取阶段。目标是把配置的飞书知识库读完整、读可审计，并保留机器可解析的来源信息。

必须遵守：

1. 每条 CLI 命令都写全 setup/`store_cli` 解析出的绝对可执行路径，并显式绑定 named profile（`"<resolved-cli-path>" --profile "<profile>" ...`）；不得使用 PATH 上的裸 `lark-cli`，也不得退回 CLI 默认 profile。
2. 源知识库只读；不执行任何写操作。
3. 输出只进入当前运行目录，不进入共享权威状态。
4. lark-cli 以 `--as user` 运行，保留实际用户身份。
5. 飞书文档不得用普通网页抓取替代 `docs +fetch`；网页通道只能用于用户确认后的非飞书外链。
6. 提取失败要报告，不得静默截断或用部分内容假装完整。

## Setup Gate

本协议只会在 setup 为 `ready` 后执行。开始提取前，AI 先检查 setup 状态；若运行时、兼容 CLI、named profile、应用配置、用户授权、知识库配置或源资源 ACL 尚未完成，由 setup 在内部闭环并恢复原提取任务。不得向用户展示或要求用户执行安装、认证、配置或刷新路径命令。

setup 完成后的真实状态必须同时满足：当前会话使用兼容 CLI 的绝对路径、用户身份已核验、源根节点及采样内容可读。认证或资源权限失败时进入对应的等待状态，批准后重新读取真实状态再继续；不得保存、输出或转发令牌。

## 节点枚举

1. 用 `"<resolved-cli-path>" --profile "<profile>" wiki +node-get --node-token <source_root_token> --as user --format json` 读取根节点，得到 `space_id`。
2. 用 `wiki +node-list --space-id <space_id>` 分页递归列出节点（同一条命令前缀）。
3. 每个节点记录 `node_token`、`obj_token`、标题、URL、对象类型、扩展名、编辑时间和可用修订号。
4. 文件夹节点只递归，不进入候选。
5. 节点数超过 100 时分批处理并报告进度。

将节点元数据写入：

```text
.general-screenwriter/tmp/<run_id>/nodes_snapshot.json
```

节点 token 缺失、对象类型不可识别或元数据格式错误时标为 `unknown`，继续用只读方式复核；不得因解析失败直接删除状态。文件夹节点只递归，不下载容器正文，也不进入内容节点 verdict。

## 增量判定

先由 `feishu-knowledge-store` 的只读 `source-baseline` 命令生成：

```text
.general-screenwriter/tmp/<run_id>/source_baseline.json
```

再运行 `check_delta.py --nodes <snapshot> --source-baseline <baseline>`。`cache/` 仍可位于当前运行目录，但不作为跨轮判据，也不参与 `unchanged` 决策。

处理规则：

- `first_run`、`new`、`changed`、`unknown` 必须读取内容。
- `unchanged` 必须有完整远端 edit time 与适用 revision 证据。
- `deleted` 必须再次只读复核；无权限或不确定时改回 `unknown`。
- 远端 baseline 缺失、时间缺失/冲突或 revision 不一致时 fail-safe 为 `changed`/`unknown`。

没有跨运行的共享本地增量权威。上一轮运行目录不应被当作本轮默认基线。

## 文件类型路由

### 原生 docx / Wiki

使用：

```bash
"<resolved-cli-path>" --profile "<profile>" docs +fetch \
  --doc <doc_url_or_token> \
  --doc-format markdown \
  --as user \
  --format json
```

不得携带 `--scope` 参数。解析返回 JSON 后记录：

- `content`
- `title`
- `document_id`
- `revision_id`

`revision_id` 必须写入候选的来源版本向量。若 API 未返回修订号，停止生成该候选并报告，不得用占位符替代。

### 上传的 Markdown 文件

先下载到运行目录：

```bash
"<resolved-cli-path>" --profile "<profile>" drive +download \
  --file-token <obj_token> \
  --output .general-screenwriter/tmp/<run_id>/cache/<node_token>.md \
  --as user
```

再以 UTF-8 读取。下载失败时该节点进入失败报告。

### 上传的 Word 文档

下载到当前运行目录，用标准库或可用工具解析正文。解析必须覆盖正文、表格、脚注、页眉页脚中的文字，并还原以下三种超链接：

1. OOXML relationship 中的外部链接
2. `fldSimple` 中的 `HYPERLINK`
3. 被拆分到多个 run 的字段码超链接

输出为内联 Markdown 链接。未还原 URL 的 Word 文档不得直接进入候选。

### 上传的 XLSX

下载后转换为 Markdown 表格，并保留每个 sheet、每一行和每一列。输出必须包裹：

```text
<!-- BEGIN_XLSX_PRESERVATION: source="{filename}.xlsx" rows="{rows}" cols="{cols}" sheets="{sheets}" -->
...
<!-- END_XLSX_PRESERVATION -->
```

`rows`、`cols`、`sheets` 必须从实际输出统计。不得概括、排序、合并单元格或改写值。每个来源表旁写：

```text
> 结构化数据来源：{飞书文档标题}（{filename}.xlsx，Sheet “{sheet_name}”）
```

### 其他对象

`sheet`、`bitable`、PDF、PPT、图片或未知对象不自动转写。在报告中记录对象类型、标题、URL 和“需人工处理”，不得伪造候选内容。

## 内容完整性

每次提取后检查：

1. Markdown 非空。
2. 标题、节点 token、修订号齐全。
3. 内容没有明显截断标记或不完整句子。
4. 标题提示多章节时，正文有对应章节结构。
5. Word/XLSX 输出保留了要求的链接和表格数据。

疑似不完整时标记 `PARTIAL`，报告原因。只有完整内容才能进入候选合成。

## 外链扫描

将提取后的正文按节点 token 写入：

```text
.general-screenwriter/tmp/<run_id>/texts/<node_token>.md
```

再运行 `scan_external_links.py`。机械层扫描 Markdown 链接、尖括号链接和裸 URL，并执行归一化、内部链接识别、硬排除、代理打分和上限裁剪。

报告必须包含：

```text
SCAN_DONE: {raw} raw → {unique} unique → {candidates} candidates → {feishu} feishu + {web} web
```

还必须列出：

- 源知识库内部链接转交叉引用的数量
- 硬排除数量和原因
- 代理层丢弃数量和原因
- 超限未抓取数量
- 待用户确认的清单

零 URL 时报告“已验证零 URL”。

非飞书外链只有在用户明确确认后才能抓取。抓取时保留原链接、抓取时间和摘要，并将其作为宿主候选的补充来源。外链失败不阻塞宿主候选。

## 候选来源字段

每个候选 frontmatter 必须包含：

```yaml
source_feishu_url: "{source-url}"
source_node_tokens:
  - "node-token-a"
source_revision_parts:
  - "42"
source_edit_time_parts:
  - 1756572300000
```

规则：

- `source_node_tokens`、`source_revision_parts` 与 `source_edit_time_parts` 长度和顺序一致。
- token 不得重复、不得为空。
- 修订号不得为空，不得使用 `N/A`。
- 编辑时间必须是正整数毫秒时间戳，并与本轮 `nodes_snapshot.json` 的 `edit_time_ms` 一致。
- 正文中的事实声明必须写中文来源引用。
- 冲突内容写入 `corrections.md` 候选，不得自行裁决。
- 任何 corrections promotion 都必须先读取当前远端权威页，再追加新卡片；不得以空模板替换，且必须保留已有红线和词表。

## 失败处理

| 故障 | 处理 |
| --- | --- |
| CLI 不存在 | 先回到 setup 内部补齐运行时和 CLI；仍失败时终止，并列出尝试过的候选路径 |
| CLI 版本不兼容 | 终止，报告版本和路径，不自动替换 |
| 认证失效 | 先回到 setup 内部重新发起或续跑授权，完成后恢复本任务 |
| 根节点无权限 | 终止，不创建替代知识库 |
| 单节点无权限 | 记录失败，继续其他独立节点 |
| 内容不完整 | 标记 `PARTIAL`，不得生成候选 |
| 修订号缺失 | 该候选不通过 |
| Word 超链接丢失 | 该候选不通过 |
| XLSX 行列缺失 | 该候选不通过 |
| 外链抓取失败 | 报告失败，宿主候选继续 |

任何故障都不得改变成“写入目标 Wiki”或“使用本地缓存作为权威”。

## 清理

所有下载、解析脚本、扫描输出和临时状态都只存在于当前运行目录。运行报告完成后删除：

```text
.general-screenwriter/tmp/<run_id>/
```

若 `feishu-knowledge-store` 尚未消费 `_manifest.json`，等待 `prepare` 完成后再删除。删除前必须向用户报告确切目录。
