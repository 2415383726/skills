# 3.0 离线效果测评（按需运行）

日常用户校对不自动运行测评。`scripts/evaluate.py` 只用 Python 3.8+ 标准库读取已经产生的结果，不调用模型或网络，不生成预测，不把格式校验通过率说成校对准确率。

## 准备和使用

在技能目录执行（`WORK` 必须是尚不存在的新目录）：

```sh
python3 scripts/evaluate.py prepare --work /absolute/path/eval-work
```

生成 source.txt、带来源快照的 document.json 和 gold.json。内置 52 个合成文字单元，包含三类修改、正确表达、技术标点例外，新增使字结构、口语压缩、文言引文、跨段引号，以及四段连续机构简称语境。所有预期均为 seed-unreviewed；不是用户原稿或经过人工审定的代表性公文样本。

由宿主按正常技能流程使用此 `document.json` 校对，在这个 WORK 得到最终 `review.json`。只给初检/复核代理它们的任务输入；不要将 `gold.json`、种子文件、答案说明交给它们，不要求代理读取整个 WORK。金标只给独立人工标注者及评分器。若被测模型能够读到金标，必须在实验记录中标明污染，不能将该轮结果用于效果结论。

```sh
python3 scripts/evaluate.py score \
  --document /absolute/path/eval-work/document.json \
  --review /absolute/path/eval-work/review.json \
  --gold /absolute/path/eval-work/gold.json \
  --work /absolute/path/eval-work \
  --output /absolute/path/eval-work/evaluation.json
```

`--work` 和 `--output` 可省略。输出路径已经存在时拒绝覆盖。缺少真实模型产出的 `review.json` 就不能测量模型效果；不要用金标复制出的预测冒充模型结果。包内目前没有评分器专用回归测试；`tests/test_pipeline.py` 和 `tests/test_extraction.py` 分别验证调度流程和文件提取，不能替代评分器验证，也不表示模型校对更好。

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

返回复核输入、规则、格式和输出正文路径。分别交给两个未接触答案、彼此不共享历史的新上下文；模型配置相同，记录模型版本与实际耗时。不向检查员提供 challenge-binding.json、gold.json 或种子。此专用挑战只写 group_decisions 正文，不运行生产队列 open/submit。

```sh
python3 scripts/review_benchmark.py score --work /absolute/path/review-hidden --body /absolute/path/review-hidden/challenge-decisions.json --output /absolute/path/review-hidden/score.json
```

对另一目录同样评分。challenge 对比提案基线与复核结果，分别统计错误提案未保留、正确提案误删和新引入修改。部分挑战与规则例句重合，属于校准回归，不能充当未见样本；外推效果需另外留出未写进规则的材料。预期需人工审定，多次配对运行才能观察模型波动；单次全拒绝不能被视为复核很好，因为会同时损失正确意见。

要回答“3.0 是否更好”，应在同一批未泄露、人工审定的真实材料上，保留两版完整 WORK、模型配置和输出，比较分项 precision/recall、正确表达误改及各阶段增益与损失。多批长文、引文和真实转写稿仍需积累；52 个开发单元和 12 项挑战只是回归起点，合成预测自测不构成模型效果证据。
