# 名称检查输出格式

```json
{
  "checked": true,
  "candidates": [{
    "severity": "pending", "rule_id": "N-CONSISTENCY", "category": "名称疑点",
    "reason": "两处指同一事项的牵头机构，请核实名称。",
    "anchors": [{"block_id": "p3", "quote": "综合处"}, {"block_id": "p8", "quote": "综合科"}],
    "suggestion": null
  }],
  "limitations": []
}
```

只返回 pending；不改写正确名称。quote 精确取自索引原文，重复片段照索引填写 occurrence（从1起算）。无具体矛盾时 candidates=[]。checked=true 声明本次输入已检查；输入不完整时如实标记并填写 limitations。

结果写入指定 .json.body，执行任务给定的 submit 命令，成功才结束。不写票据、哈希或报告。
