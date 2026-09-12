# 短文角色指引

主 Agent 在技能包外的临时 WORK 运行脚本，生成指引文件，不需要读取其正文：

```text
python "<SKILL>/scripts/guidance.py" --role proofread --chat --output "<WORK>/proofread-guidance.md"
```

严格模式给两个新子代理各自传入同一原始短文（或提取文件路径）与这个指引路径。只返回候选，不输出 JSON 或报告、不采集名称索引。二者不共享历史、不读对方结果。

有候选时生成另一份指引：

```text
python "<SKILL>/scripts/guidance.py" --role review --chat --output "<WORK>/review-guidance.md"
```

给一个新复核子代理原文、修改提案和复核指引，隐藏初检理由与来源；返回最终意见与待核实事项。短文提案没有完整 rule_id 时，复核指引保留全部领域判据，不让主 Agent 猜分类。无候选不生成复核任务。脚本生成的指引是内部临时资料，用户结果仍在聊天中交付。

用户明确选择轻量模式时，主 Agent 读取生成的初检指引，完成同一短文检查，并自行核对候选的具体依据与必要性；此模式不执行独立复核，须如实标注。附件的 scope 与 limitations 同样进入交付，实际未完成时不使用无错结语。
