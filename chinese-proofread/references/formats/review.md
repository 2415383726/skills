# 复核输出格式

文件任务读取 candidate_groups 及 context_units，按 context_unit_ids 关联。每组填写一次，每个候选编号恰好出现在 accept、reject 或 replace 中一次。正常保留用 accept，剔除用 reject；只有改写意见、合并意见或保留待核实时用 replace。

```json
{
  "group_decisions": [
    {
      "group_id": "group-0001",
      "accept": ["candidate-0001"],
      "explanations": {"candidate-0001": "此处表示安排工作，应使用部署。"},
      "reject": [{"id": "candidate-0002", "code": "valid-original", "reason": "地在此处可以省略。"}]
    }
  ],
  "limitations": []
}
```

accept 仅用于原 confirmed 候选。explanations 按编号写一句依据，单纯半角标点转全角可省略。requires_necessity=true 时另填 necessity；补删文字或的／地／得的实际改动也须填写，改 rule_id 不能绕过：

例如，候选 candidate-0004 是“进度度 → 进度”时：

```json
{
  "group_id": "group-0003",
  "accept": ["candidate-0004"],
  "explanations": {"candidate-0004": "度字重复录入。"},
  "necessity": {"candidate-0004": "进度已完整，末尾另一个度重复录入且无句法作用。"}
}
```

necessity 留在审计数据；explanations 是面向用户的简短依据。无需长篇论证或复述修改对照。

需要重写意见时：

```json
{
  "group_id": "group-0002",
  "replace": [{
    "candidate_ids": ["candidate-0003"],
    "reason": "只能确认名称存在差异，正确写法需核实。",
    "findings": [{
      "severity": "pending", "rule_id": "N-CONSISTENCY", "category": "名称疑点",
      "reason": "两处指同一牵头部门，请核实机构名称。",
      "anchors": [{"block_id": "p3", "quote": "综合处"}, {"block_id": "p8", "quote": "综合科"}],
      "suggestion": null
    }]
  }]
}
```

- replace 也可产生 confirmed：一个原文锚点、确定 suggestion；易误报实际改动在 finding 内填写 necessity。
- quote 精确取自原文，重复时填写 occurrence（从1起算）。锚点在本组原候选覆盖范围内；需要组外位置才能成立的修改不在本组发布。
- reject.code：valid-original（原文成立）、duplicate（重复意见）、insufficient-evidence（无具体依据）、protected-context（技术语境）、out-of-scope（如润色）。
- 省略未使用的 accept/reject/replace 即可。同组可保留多个不重叠意见；不能缺少任何候选的决定。

正文写到任务指定的 .json.body，再执行任务给定的 submit 命令，成功才结束。不写票据、哈希、报告或其他批次结果。
