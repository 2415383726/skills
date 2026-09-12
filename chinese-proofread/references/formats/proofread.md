# 初检输出格式

文件任务把下面结构写入任务指定的 .json.body：

```json
{
  "completed": true,
  "candidates": [
    {
      "severity": "confirmed",
      "rule_id": "T-TYPO",
      "category": "错别字",
      "reason": "此处表示安排工作，应为部署。",
      "anchors": [{"block_id": "p2", "quote": "部暑"}],
      "suggestion": "部署"
    }
  ],
  "terms": [{"text": "综合处", "kind": "机构名称"}],
  "limitations": []
}
```

- completed=true 声明本批 main_units 已完整检查；未完成写 false、checked_unit_ids（实际完成单元）和 limitations，不以空候选假装完成。
- confirmed 只有一个锚点，suggestion 为确定替换字符串；删除可为空。pending 的 suggestion=null，可引用多个锚点，reason 说明具体核实事项。
- block_id 来自本批主区；quote 精确取自该单元，重复出现时填写 occurrence（从1起算）。不能猜序号，漏字用包含插入点的非空短语定位。
- terms 只写本批主区出现的原始名称与种类，同名一次，无须抄每处位置。空 candidates / terms 均合法。
- 不手写候选编号、票据或哈希。写完执行任务给定的 submit 命令，成功才结束。
