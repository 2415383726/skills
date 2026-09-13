# skills

A personal collection of agent skills I build and use daily.

这个仓库用于持续沉淀我在日常工作中搭建和使用的 agent skills。目前收录十三个技能，覆盖中文办公材料起草、简报、审稿、校对，制度问答和版本对比，数据分析、报表复核、台账体检、人力资源统计，以及会议全流程和 SOP 沉淀——对应建设清单的 P0 第一梯队。每个技能以独立文件夹组织，包含 `SKILL.md` 和按需提供的参考文档、脚本、测试或测评用例；使用前请确认宿主满足该技能的依赖要求。

## 技能总览

| Skill | 说明 | 使用说明 |
| --- | --- | --- |
| [chinese-proofread](chinese-proofread/) | 中文文字校对：错别字、多字漏字、用字和标点；文件队列另查名称一致性 | [安装与使用](chinese-proofread/INSTALL.md) |
| [chinese-drafting](chinese-drafting/) | 材料起草：9 类常用材料结构化初稿及待补事实清单 | [说明](chinese-drafting/README.md) |
| [chinese-briefing](chinese-briefing/) | 工作简报：周报、月报、工作动态、FAQ 和领导更新 | [说明](chinese-briefing/README.md) |
| [chinese-review](chinese-review/) | 材料审稿：逻辑、数字、时间、依据和一致性检查 | [说明](chinese-review/README.md) |
| [policy-qa](policy-qa/) | 制度政策问答：基于所提供制度给出带条款出处的回答 | [说明](policy-qa/README.md) |
| [policy-diff](policy-diff/) | 制度新旧对比：条款变化、影响对象和执行注意事项 | [说明](policy-diff/README.md) |
| [excel-analysis](excel-analysis/) | Excel 数据分析：问题理解、口径、计算、校验、结论 | [说明](excel-analysis/README.md) |
| [report-check](report-check/) | 报表智能复核：合计勾稽、负值、跳变、可疑比率 | [说明](report-check/README.md) |
| [ledger-checkup](ledger-checkup/) | 台账数据体检：身份证校验、查重、必填、枚举漂移 | [说明](ledger-checkup/README.md) |
| [hr-statistics](hr-statistics/) | 人力资源统计：结构月报、退休预测，只汇总不排名 | [说明](hr-statistics/README.md) |
| [meeting-brief](meeting-brief/) | 会前材料：一页会前卡片，缺口如实标注 | [说明](meeting-brief/README.md) |
| [meeting-minutes](meeting-minutes/) | 会议纪要督办：纪要草稿、督办台账，不编造责任人 | [说明](meeting-minutes/README.md) |
| [sop-capture](sop-capture/) | SOP 流程沉淀：RACI、流程图、例外场景、三关自检 | [说明](sop-capture/README.md) |

## 目录结构

```text
skills/
├── chinese-proofread/   # 中文文字校对技能
├── chinese-drafting/    # 材料起草技能
├── chinese-briefing/    # 工作简报技能
├── chinese-review/      # 材料审稿技能
├── policy-qa/           # 制度政策问答技能
├── policy-diff/         # 制度新旧对比技能
├── excel-analysis/      # Excel 数据分析技能
├── report-check/        # 报表智能复核技能
├── ledger-checkup/      # 台账数据体检技能
├── hr-statistics/       # 人力资源统计技能
├── meeting-brief/       # 会前材料技能
├── meeting-minutes/     # 会议纪要督办技能
├── sop-capture/         # SOP 流程沉淀技能
├── chinese-proofread.zip # 与校对技能目录一致的分发包
├── 来源项目总览/         # 上游参考项目（agentskills、anthropics/skills 等）
├── 建设清单与二开建议_V1.0.docx
├── LICENSE
└── README.md
```

## 使用方式

将所需技能的整个文件夹放入宿主的 skills 目录，确保其 `SKILL.md` 直接位于该文件夹下，然后刷新技能列表。各技能的依赖、输入输出和使用方式见上表链接。`来源项目总览/` 是参考资料，不需要整体安装。

常用衔接为：材料起草或工作简报 → 材料审稿 → 文字校对；数据线为台账体检 → 数据分析 → 报表复核 → 人力资源统计汇报；会议线为会前材料 → 纪要督办 → SOP 流程沉淀。制度问答用于查明条文依据，制度新旧对比用于理解版本变化；各技能按用户请求分别调用。

## 当前技能：chinese-proofread（中文文字校对）

校对公文、通知、报告、讲话稿及日常办公文字中的错别字、多字漏字、用字和标点问题；文件队列另检查文内名称一致性。支持粘贴文字及多种本地办公文件，按实际提取范围检查。不做润色改写、公文版式检查或外部事实核验。

**特性**

- 默认严格模式：两路独立初检及候选复核，要求宿主提供新上下文子代理和共享文件系统。只有用户明确选择快速检查、且内容约 500 字以内并结构简单时才使用轻量模式，交付注明未经独立复核。
- 角色指引分开：脚本为初检、名称检查和复核分别组装所需步骤、判据及格式，减少无关指令；上下文隔离由宿主配合执行。
- 统一文件提取：DOCX、XLSX、PPTX、TXT/Markdown 有本地提取路径；旧 XLS 可选 xlrd，DOC/PPT、WPS 原生格式及解析失败文件按返回动作交给宿主。提取限制随结果交付，不承诺检查未读取区域。
- 按内容决定交付：约 500 字以内、结构简单且完整可见的内容在聊天内回复，短附件也一样；长文或复杂材料生成左右对照、可双向定位的离线 HTML。尊重用户指定的格式，原文件不回写。
- 低依赖：核心流程与基础提取仅用 Python 3.8+ 标准库。目标环境为内网宿主，Windows 7 与麒麟 V10 尚未实机验证。
- 脚本化调度：主 Agent 按 `tasks.py step` 返回动作派发、等待、恢复或交付。宿主句柄持久化，重复和旧轮次通知返回 `ignore_event`；默认最多 8 个子代理并行，按宿主实际容量调低。
- 恢复与追溯：名称检查可独立补查并保留原采集覆盖记录；未完成范围明确披露，未复核候选不作为明确错误交付。交付后可结合最终报告和相关原文解释意见。

运行该技能的机械回归测试：

```bash
python -m unittest discover -s chinese-proofread/tests -v
```

## 当前技能：chinese-drafting（材料起草）

把要点和零散素材变成结构合规、事实可溯源的中文办公材料初稿，覆盖工作总结、工作计划、情况汇报、请示、通知、会议材料、述职材料、经验交流材料、讲话稿/提纲九类。按材料类型渐进加载写作规则，初稿中所有非用户提供的时间、数字、人名、文号一律【待补】占位并自动汇总为待补事实清单，交付即可进入审稿环节。

**特性**

- 事实可溯源：唯一硬约束是不编造——素材里没有的事实占位标注，待补清单一次说清缺口，减少来回改稿轮次。
- 按类型加载规则：每类材料独立 reference，含结构骨架、常用表达、禁忌、篇幅、事实核验点，起草哪类只读哪份。
- 脚本保底：`facts.py new/scan/check` 分别负责骨架生成、占位符无遗漏扫描、定稿前检查；Python 3.8+ 标准库，UTF-8/GBK 兼容。
- 流水线衔接：对应建设清单 S01，规划为"起草 → 材料审稿 → 公文校对（chinese-proofread）→ 格式输出"的第一环。

运行机械回归测试：

```bash
python -m unittest discover -s chinese-drafting/tests -v
```

## 验证与迭代

其他带脚本的技能可分别运行机械回归：

```bash
python -m unittest discover -s policy-qa/tests -v
python -m unittest discover -s policy-diff/tests -v
python -m unittest discover -s excel-analysis/tests -v
python -m unittest discover -s report-check/tests -v
python -m unittest discover -s ledger-checkup/tests -v
python -m unittest discover -s hr-statistics/tests -v
python -m unittest discover -s meeting-minutes/tests -v
python -m unittest discover -s chinese-drafting/tests -v
```

机械测试验证脚本与流程行为，不代表实际模型的语言准确率。中文校对的效果测评、人工审定与模式比较见 [离线测评](chinese-proofread/references/evaluation.md)，规则维护见 [规则维护](chinese-proofread/references/quality.md)；其他技能的起步测评用例位于各自的 `evals/`。模型效果与目标环境兼容性需在实际内网宿主验收。

## License

仓库自研内容采用 [MIT](LICENSE)。本地化技能与上游参考资料保留各自许可证和来源说明；例如 chinese-briefing、chinese-review、policy-qa 附有 Apache-2.0 许可证，具体以对应目录为准。
