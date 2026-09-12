# 离线效果测评（按需运行）

日常用户校对不自动运行测评。`scripts/evaluate.py` 只用 Python 3.8+ 标准库读取已经产生的结果，不调用模型或网络，不生成预测，不把格式校验通过率说成校对准确率。

## 准备和使用

在技能目录执行（`WORK` 必须是尚不存在的新目录）：

```sh
python3 scripts/evaluate.py prepare --work /absolute/path/eval-work
```

生成 source.txt、带来源快照的 document.json 和 gold.json。内置 52 个合成文字单元，包含三类修改、正确表达、技术标点例外，新增使字结构、口语压缩、文言引文、跨段引号，以及四段连续机构简称语境。所有预期均为 seed-unreviewed；不是用户原稿或经过人工审定的代表性公文样本。

由宿主按正常技能流程使用此 `document.json` 校对，在这个 WORK 得到最终 `review.json`。只给初检/复核代理它们的任务输入和脚本生成的本角色指引；不要将 `gold.json`、种子文件、答案说明交给它们，不要求代理读取整个 WORK。金标只给独立人工标注者及评分器。若被测模型能够读到金标，必须在实验记录中标明污染，不能将该轮结果用于效果结论。

```sh
python3 scripts/evaluate.py score \
  --document /absolute/path/eval-work/document.json \
  --review /absolute/path/eval-work/review.json \
  --gold /absolute/path/eval-work/gold.json \
  --work /absolute/path/eval-work \
  --output /absolute/path/eval-work/evaluation.json
```

`--work` 和 `--output` 可省略。输出路径已经存在时拒绝覆盖。缺少真实模型产出的 `review.json` 就不能测量模型效果；不要用金标复制出的预测冒充模型结果。`tests/test_evaluation.py` 验证评分与配对比较；`tests/test_boundaries.py` 验证预算、范围和分支；其他测试验证调度与提取。这些机械测试不表示模型校对更好。

## 金标格式与审定

```json
{
  "document_sha256": "与最终 review.json 相同的完整 document 指纹",
  "annotation_status": "seed-unreviewed",
  "cases": [
    {
      "block_id": "p001",
      "text": "请尽快部暑下一阶段工作。",
      "annotation_status": "seed-unreviewed",
      "expected": [
        {"category": "错别字", "anchor": {"quote": "部暑"}, "suggestion": "部署"}
      ]
    }
  ]
}
```

每个非空文字单元必须恰有一条 case，`text` 必须与原文完全一致。正确表达用 `"expected": []` 或 `"expected": "no-change"`。金标分类必须为 `错别字`、`多漏字`、`标点`。每个 expected 表示一个独立修改，使用同一原始段落作为输入；锚点重复出现时必须填写从1起算的 `occurrence`。不要将整段最终修订稿作为多个独立错误的共同答案。插入操作使用包含相邻文字的非空锚点；删除允许空 suggestion。

只有实际独立人工逐条审定之后，标注维护者才能将对应条目及顶层状态设为 `human-reviewed`；保留审定人员、日期、依据及分歧处理记录。脚本不会作此升级。只要顶层或任何一条仍为 `seed-unreviewed`，全部结果明确标注为未经人工审定的开发基准。即使文件自报 `human-reviewed`，脚本也不能验证是谁审定的；需要外部审定记录作为证据。

## 计数规则

- 每条 confirmed 替换单独应用到原始单元，以 `(block_id, 修改后的完整单元文本)` 匹配预期。锚点长短不同但修改效果相同算同一项；重复预测去重并列入 `duplicate_confirmed`，不重复获奖或误罚。
- TP 是预测与金标修改效果交集；FP 是金标没有的预测修改；FN 是没有 confirmed 命中的预期。正确段落的误改另列 `no_change_false_positives`（计独立修改效果），不计算“真负例准确率”。
- `precision = TP / (TP + FP)`；`recall = TP / (TP + FN)`。分母为0输出 JSON `null`，不视为100%。
- pending 仅统计数量，不给 TP，也不算 confirmed FP；相应未被 confirmed 命中的金标仍算 FN。此版本不评估 pending 的价值或覆盖率。
- 命中项分类采用金标分类，错误修改分类按规则编号 `T-TYPO/W-*`、`T-MISSING/T-EXTRA`、`P-*`，category 自由文案仅作为后备；无法映射的误报进入 `其他`，不会默默丢弃。此指标评价修改效果，不评价分类标签正确率。
- 一条预测合并两个错误的修改，不等同于两个单项预测；金标也应拆成单项。此版本不拆分复合修改、不做模糊语义匹配、不接受多种替换答案集；因此需要人工核查这类不匹配。
- 严格核验来源文件快照、提取内容指纹、review/gold 文档指纹、金标文本及锚点。评分器允许重复/重叠预测以测去重效果，不代替生产报告的完整 schema 和重叠校验。

## 流程统计与解释边界

可选 `--work` 读取相同 document 指纹的 `task-state.json` 和 `submission-events/*.json`。首次提交通过率按有日志的逻辑 task_id 取最早 attempt/at 状态。`local_corrections` 仅统计同 task_id、attempt、ticket 内最终 accepted 之前的 invalid 次数；跨票据重查、尚未改正的 invalid 不算局部修正。此计数反映提交修正轮数，不能证明每次编辑内容。`fallback_jobs` 来自当前 jobs 的 executor。无日志任务不进入通过率分母；日志丢失可能造成偏差。

没有状态或事件的指标输出 null；fallback_jobs 在有 jobs 数据时可以为 0。phase_timings 按 execution 的 opened_at/submitted_at 分别记录 A、B、一致性和复核的墙钟跨度、各任务时长及其合计。包含工具和等待时间，不是模型计算时间；model_elapsed_seconds 仍为 null。时间记录不要求上下文 ID 可用，两种证据分别处理。

提供完整 WORK 时，stages 对 A、B、两路候选并集 union、merged、一致性、pre_review、final 分别计算修改效果。stage_comparisons 统计 a_unique_correct / b_unique_correct / shared_correct，以及 review_removed_correct / review_removed_incorrect / review_added_correct / review_added_incorrect。correct 只指匹配当前标注；标注未经审定时不能解释为人工确认正确。

每一路必须有完整批次及覆盖才能产生该路指标。脚本核对输入、原始结果、合并和复核指纹，并按修改效果对齐；阶段缺失输出 null。stage_evidence.final_linked_to_work 区分仅评分所给最终结果与已连接到规范复核工件。复核 removed 指复核前 confirmed 修改未在最终 confirmed 中保留，包含剔除、降为 pending 和改写，不只等于 reject 计数。名称 pending 的价值尚不计分。

## 复核诱导挑战

独立的 12 项未审定挑战包含 8 个错误修改提案和 4 个预期正确提案，附有刻意具有说服力的初检理由。用于测“能否拒绝错误意见，同时保住正确意见”，不运行 A/B，不测初检召回。准备两个新目录：

```sh
python3 scripts/review_benchmark.py prepare --work /absolute/path/review-hidden
python3 scripts/review_benchmark.py prepare --work /absolute/path/review-visible --show-initial-reasons
```

返回复核输入、本角色指引和输出正文路径。分别交给两个未接触答案、彼此不共享历史的新上下文；模型配置相同，记录模型版本与实际耗时。不向检查员提供 challenge-binding.json、gold.json 或种子。此专用挑战只写 group_decisions 正文，不运行生产队列 open/submit。

```sh
python3 scripts/review_benchmark.py score --work /absolute/path/review-hidden --body /absolute/path/review-hidden/challenge-decisions.json --output /absolute/path/review-hidden/score.json
```

对另一目录同样评分。challenge 对比提案基线与复核结果，分别统计错误提案未保留、正确提案误删和新引入修改。部分挑战与规则例句重合，属于校准回归，不能充当未见样本；外推效果需另外留出未写进规则的材料。预期需人工审定，多次配对运行才能观察模型波动；单次全拒绝不能被视为复核很好，因为会同时损失正确意见。

要回答“调整后是否更好”，应在同一批未泄露、人工审定的真实材料上，保留两版完整 WORK、模型配置和输出，比较分项 precision/recall、正确表达误改及各阶段增益与损失。多批长文、引文和真实转写稿仍需积累；52 个开发单元和 12 项挑战只是回归起点，合成预测自测不构成模型效果证据。


## 真实材料的人工标注入口

维护者从已授权使用的真实材料中分层抽样，至少包含通知、报告、讲话摘录、长文、表格、专名差异及技术标点例外；含正确原文，避免只收集错句。按文件划分开发集与留出集，避免同一文档的不同段落泄漏到两边。发布前使用独立标注者审定并记录分歧；不把合成例句改名为真实材料。

统一提取后，在检查员无权读取的评估目录生成标注模板：

```sh
python3 scripts/evaluate.py annotation-template --document /absolute/path/document.json --output /absolute/path/private-eval/gold-draft.json
```

模板 expected=null、annotation_status=unannotated，评分器会拒绝；不会把尚未标注的段落当无错。人工逐条填写 expected（正确原文填 []），记录 review_record，再按实际审定状态填写 human-reviewed，保存为 gold.json。该字段是人工声明，不是程序认证。名称 pending 当前只计数量，其有用性和是否值得交付另由标注者审查，不宣称已覆盖名称准确率。

## 四种模式的配对实验

实验模式只用于维护评估，不改变日常默认严格模式。每个模式使用相同 document.json、模型版本、推理/采样配置、上下文预算和原始用户请求，至少重复三个独立轮次，保留原始输出、耗时、失败原因和人工核对记录。不向运行模型展示金标或其他模式结果。

| variant | 给予运行模型的内容与执行方式 |
| --- | --- |
| no-skill | 原文及“仅校对文字和标点，不润色”的请求；不加载技能规则、角色文件或示例 |
| single-pass | 原文与 guidance.py 生成的初检指引；一个新上下文完成一次检查 |
| single-review | 与 single-pass 相同的初检；另一个新上下文按复核规则处理其候选，隐藏初检理由 |
| dual-review | 使用本技能正常严格流水线，包括名称一致性和候选复核 |

非流水线模式保留原始输出，再由评估维护者按原意见无损转成评分所需 findings；不得补查、补改或复制金标。document_sha256 使用同一文档指纹。评分的 reviewed:true 仅表示此模式交付的最终意见，不能用它声称 no-skill 或 single-pass 经过独立复核。不虚构 A/B 执行记录；非流水线评分省略 --work，相应阶段证据为 null。转换有歧义时记录为待人工处理，不偷偷替模型改答案。

分别执行 evaluate.py score，得到各自独立评分文件。新建 runs.json 记录所有实际执行，包括失败：

```json
{
  "model_config": "填写实际内网模型版本、推理档位和采样设置",
  "runs": [
    {"material":"通知甲","repeat":1,"variant":"no-skill","delivered":true,"elapsed_seconds":12.4,"score_path":"no-skill-score.json"},
    {"material":"通知甲","repeat":1,"variant":"single-pass","delivered":true,"elapsed_seconds":15.2,"score_path":"single-pass-score.json"},
    {"material":"通知甲","repeat":1,"variant":"single-review","delivered":true,"elapsed_seconds":23.8,"score_path":"single-review-score.json"},
    {"material":"通知甲","repeat":1,"variant":"dual-review","delivered":false,"elapsed_seconds":35.0,"score_path":null}
  ]
}
```

以上仅为字段示例，数值不是实测结果。实际文件必须记录每份材料、每轮的四种模式；失败无评分时 score_path=null，不能伪造零意见。耗时未知填 null。

```sh
python3 scripts/compare_evaluations.py --manifest /absolute/path/private-eval/runs.json --output /absolute/path/private-eval/comparison.json
```

比较器核验同一材料的文档及金标指纹，拒绝重复实验项或复用同一评分文件。修改质量只汇总四种模式均有评分的配对组，交付率包含所有实际执行；缺失耗时不视为零。不把单次结果或少量材料的均值当稳定结论。结合每份文件、每轮原始评分检查波动，并单独审查 pending、有多个合理改法和复合修改的不匹配。

保留第二路的依据应是未见材料上的新增正确发现值得额外耗时，且最终误改可接受；保留复核的依据应是减少误报同时没有不可接受的正确发现损失。若证据不足，继续保持严格模式默认，不把轻量模式宣传为等效替代。

## 触发与交付验收

在目标宿主用真实用户措辞检查：应触发“请校对这份通知的错字和标点”“检查附件文字”；不应把“美化公文版式”“核查政策是否合法”“重写得更有文采”误路由为本技能的完整能力。分别验收短附件含遗漏范围、明确快速检查、严格模式缺子代理、单批含名称差异、长文超预算及零候选场景。这里是行为验收清单，不以关键词匹配测试冒充宿主触发测试。

角色指引优化先保持原材料、分块、并发及内网模型配置不变，只替换指引，分别检查新增发现、最终误改和复核误删。目标部署为用户实际使用的 DeepSeek V4 Flash 0731 时，记录真实思考模式和推理配置；不能从其他版本的公开参数推定内网配置。roles/checks 示例仅作教学，留出测评应使用未写入这些文件的材料。
