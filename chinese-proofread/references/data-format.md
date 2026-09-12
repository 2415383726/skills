# 文件数据约定

本文件供提取和维护使用。检查员直接读任务指定的角色格式：[初检](formats/proofread.md)、[名称一致性](formats/consistency.md)、[候选复核](formats/review.md)，无需把所有角色格式读一遍。

## document.json

统一使用 extract_file.py；ready 后均得到下面结构。宿主回退优先用返回的 --resume 命令接收；宿主有带位置的 JSON 时通过 --host-document 传入。底层 report.py prepare、extract_docx.py 和 provenance.py 仍可维护使用。

```json
{
  "title": "工作通知",
  "source_name": "工作通知.docx",
  "scope": "标题、正文和正文表格；最终修订视图",
  "limitations": ["宿主未返回页眉页脚，未检查该部分"],
  "blocks": [
    {"id": "p1", "kind": "heading", "text": "工作通知", "location": "文档标题"},
    {"id": "p2", "kind": "paragraph", "text": "综合处根据年度工作部暑。", "location": "正文第1段"},
    {
      "id": "t1", "kind": "table", "location": "表1", "header_rows": 1,
      "rows": [
        [{"id": "c1", "text": "事项", "location": "表1 R1C1"}],
        [{"id": "c2", "text": "报送材料", "location": "表1 R2C1"}]
      ]
    }
  ]
}
```

blocks 按阅读顺序排列，支持 paragraph、heading、table；表格各行等列，文字单元及容器 id 全局唯一，只含 ASCII 字母、数字、下划线、连字符。空白单元保留结构但不计检查覆盖。文字由提取器直接落盘，不由 LLM 按摘要重建。

Excel 可把文字单元格表示为 paragraph，location 写“工作表名!B12”，保留相应表头。复杂表格可展平为带位置的 paragraph 并说明。数字、公式、版式不属于默认检查；公式不执行。

scope / limitations 写工具实际返回的区域、修订视图和已知缺漏。provenance 由脚本记录源路径/哈希、提取方式和提取内容指纹；不手填哈希、不把旧提取内容关联到新附件。哈希不证明提取完整性。

## 任务与中间结果

jobs/*.json 由脚本保存角色、输入、任务指引路径与来源清单、指令、票据和结果路径。检查员先执行派发提示中的 open --brief，只按返回的 instructions 读取本角色输入和写结果，不必读取任务元数据。只读本任务所需文件，不读取另一初检路结果或测评标准答案。

模型只写 .json.body 中的判断数据；submit 完整校验后绑定票据、原子发布并推进确定性阶段。step 再验证并派发后续任务或交付 HTML。定位字段错误可由原检查员局部修正，不重启初检；具体格式见对应角色文件。

中间文件 schema_version 使用 workflow.py 中的 SCHEMA 协议标识，与 SKILL.md 的发布版本分离。脚本补齐编号、输入/规则/原文指纹和执行记录；旧版工作目录不直接续跑。completed 是检查员声明，机械校验不能证明实际阅读。

复核输入按重叠连通组组织、上下文去重，不含初检 reason/reasons/sources。requires_necessity 标识已有必要性依据要求。confirmed 的 accept 列编号，explanations 按编号提供一句修改依据；单纯半角标点转全角可省略解释，由脚本生成。详细 necessity 保留在数据中，不替换报告短句。pending 用 replace 写复核后的具体疑问。原始理由和来源仍在 merged.json 中用于审计，不交给复核员。

execution 由脚本记录 ticket、context_id、context_source、opened_at、submitted_at、executor。上下文来源为 host-provided / agent-declared / unavailable；无可用标识或时间为 null。时间是本地脚本记录的领取/提交时刻，不是模型计算计时。没有 open 的兼容提交保留未知；不能用随机上下文 ID 提升证据等级。

task-state.json 保存调度状态，不要求 Agent 手工编辑；用 status 观察、step 派发和交付、retry 重查。coordinator 是当前调度实例标识与活动时间，coordinator-events 保存显式接管记录，submission-events 保存提交尝试。jobs/*.json.started 保留票据与上下文开启记录。它们用于追溯，不是防恶意篡改或信息隔离的安全机制。

最终 review.json 保留 execution_audit 和 process_statistics 供维护与测评；HTML 聚焦原文、修改点和实际未完成范围，不显示执行审计与过程计数。部分交付使用 tasks.py partial 一步渲染并明确未完成范围；缺少审计数据时显示未知。

manifest.consistency_required 决定名称阶段，long_document 仅保留分块兼容信息，不决定报告形式。复核 manifest 记录 max_input_chars、每批 input_chars / budget_exceeded；超限不可拆分组不派发、不发布其未复核候选。提取 ready 同时返回 scope 和 limitations，聊天交付也必须保留实际范围限制。

jobs/*.guidance.md 由 scripts/guidance.py 组装。角色只读该文件和任务 input_path；jobs 元数据中的 guidance_sources 供维护追踪，不要求模型再读源文件。指引正文哈希保存在状态中，open/submit 时验证。
