# 候选组复核结果格式（3.0）

input_path 包含 candidate_groups 与去重的 context_units；按各组 context_unit_ids 读取原文。输入已隐藏初检理由、来源及票数，不另读初检或合并工件。先读原文，尝试一个合理的词义、句法解释，再看修改提案是否排除了这种解释。发现原文成立即可剔除，无须替候选寻找支持理由。

每个候选编号恰好处理一次；一组可以保留多个不重叠修改。保留意见在 explanations 中用一个短句说明为什么改，通常 10—30 字。不要重复“原文 A 应为 B”，不要写“复核确认”“修改后更规范”。只有单纯半角标点转全角可省略解释，由脚本生成。例：“‘历练’指经历锻炼，此处应使用‘练’。”

```json
{
  "group_decisions": [
    {
      "group_id": "group-0001",
      "accept": ["candidate-0001"],
      "explanations": {"candidate-0001": "安排工作应写作‘部署’。"},
      "reject": [
        {"id": "candidate-0002", "code": "valid-original", "reason": "原句成立，只是另一种表达。"}
      ]
    }
  ],
  "limitations": []
}
```

## 易误报意见必须证明必要性

输入 requires_necessity=true 的明确候选（补字、多字、的／地／得等）不能只写 accept 编号；在同组 necessity 中写一条简短依据：**原句的哪处词义或句法关系不能成立，以及为什么不是可省略助词、口语压缩或风格差异**。该依据保留在数据中；报告只显示 explanations 的短句，不把详细审查过程塞进卡片。

```json
{
  "group_decisions": [
    {
      "group_id": "group-0002",
      "accept": ["candidate-0003"],
      "explanations": {"candidate-0003": "‘度’重复录入，删去一个。"},
      "necessity": {
        "candidate-0003": "“进度”是此处名词，第二个“度”不成词且无句法功能，属于重复录入。"
      }
    }
  ],
  "limitations": []
}
```

仅说“缺少地”“加上更顺”“状语要用地”不合格。若不能排除原文成立，剔除这条修改；不要为了保留它而编造解释，也不要把普通表达批量降为 pending。脚本检查依据字段是否存在，不验证这句话的语法结论是否正确；你仍须作判断。

多字候选先尝试另一种切词与口语省略，检查删除后是否丢失实义。“一个动词已经够用”不能证明动词重叠有误；不能只凭一种固定切词否定原句。例如“接触外界面较窄”须考虑“接触外界的面较窄”的解析，不能只把“界面”当技术名词就删去“外界”。无法排除原文成立时剔除修改，不编造必要性理由。

## 改变候选结论

需要合并、缩短锚点、改变等级或保留 pending 时用 replace。其 reason 同样只用一个短句说明依据。待核实须由你写出具体核实对象，不能通过 accept 沿用初检疑问。不把未经你核验的初检理由带进报告。未用的 accept/reject/replace 可省略：

```json
{
  "group_decisions": [
    {
      "group_id": "group-0001",
      "replace": [
        {
          "candidate_ids": ["candidate-0001", "candidate-0002"],
          "reason": "两条意见重复，保留最小修改。",
          "findings": [
            {
              "severity": "confirmed",
              "rule_id": "T-TYPO",
              "category": "错别字",
              "reason": "此处表示安排工作，应为部署。",
              "anchors": [{"block_id": "p2", "quote": "部暑"}],
              "suggestion": "部署"
            }
          ]
        }
      ]
    }
  ],
  "limitations": []
}
```

替换意见如属于易误报修改，在 finding 内增加 necessity 字符串。脚本也按实际改动检测补删文字/的地得，换 rule_id 不能绕过。pending 的 suggestion 为 null；confirmed 一个锚点，suggestion 是替换该原文片段的字符串。

所有 quote 精确取自原文，重复片段用 occurrence（从 1 起算）。锚点在本组原候选覆盖范围内；需要扩大到组外才能成立的意见不在本组擅自发布。缺任一候选决定时整组不交付。

reject.code 选 valid-original（原文成立）、duplicate（与保留意见重复）、insufficient-evidence（连具体疑点也缺依据）、protected-context（技术语境例外）、out-of-scope（如润色）。P-CN 中文标点样式属于范围，不得仅以全半角是风格为由剔除。

正文写到指定 .json.body，按 instructions 运行 submit。失败在本复核任务内修正对应字段，最多连续 3 次；不重查整篇、不调用 retry。提交成功才结束。
