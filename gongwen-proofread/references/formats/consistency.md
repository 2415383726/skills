# 名称一致性检查结果格式（3.0）

input_path 的 terms 包含实际名称、种类、每处位置与局部语境。只比较可能指向同一对象的不同写法；不凭相似、少见或出现频次判断错误。

```json
{
  "checked": true,
  "candidates": [
    {
      "severity": "pending",
      "rule_id": "N-CONSISTENCY",
      "category": "机构名称疑点",
      "reason": "两处均指本事项牵头部门，请核实是否为同一机构。",
      "anchors": [
        {"block_id": "p3", "quote": "综合处"},
        {"block_id": "p8", "quote": "综合科"}
      ],
      "suggestion": null
    }
  ],
  "limitations": []
}
```

本角色只新增 pending，后续由候选复核读取相关原文。quote 必须精确存在；重复时照索引指定 occurrence。没有具体矛盾时 candidates=[]；索引不是权威词典，也不能证明没有漏收名称。

写到指定 .json.body 后运行 instructions 中的 submit；字段/定位错误在本任务局部修正，最多连续 3 次，成功后才结束。无需手写票据、哈希或候选编号。
