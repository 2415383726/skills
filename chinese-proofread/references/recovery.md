# 异常与恢复（仅遇到异常时读取）

主 Agent 只调度，不补做失败的初检、一致性检查或复核，不读取失败任务的正文、候选或拦截原话。只接收任务 ID 与简短状态。确认子任务是否仍在运行，不凭等待时间推断失败。正文结果修正交回原检查员。

step/wait 返回 stalled 表示预留超过90秒仍无 open 回执。先核对宿主句柄，确认未启动才重交接；宿主已经派发但尚未领取时继续等待该句柄，不重复创建。启动延迟不能作为失败或跳过依据，脚本不自动重启。

恢复先只读查看，再处理未启动任务：

```text
python "<SKILL>/scripts/tasks.py" status --work "<WORK>" --compact
python "<SKILL>/scripts/tasks.py" step --work "<WORK>" --coordinator "<COORDINATOR>" --compact --resume-assigned
```

status 不分配、接收或推进任务；显示属主、有效并发、任务票据、开启时间和停留时长。response_pending 是结果已提交待接收，running 是已启动，assigned 表示尚无领取回执，可能已在宿主排队启动；结合 host_handle 和 dispatch_state 核对。last_reconciliation 记录上次接收数。状态是观察时快照，领取时 open 再检查。

恢复时只重交接已核对尚未启动且无绑定句柄的 assigned，沿用原票据，不消耗判断次数。如果原协调实例已经退出，用当前实例 ID 加 --takeover 显式接管；脚本记录切换并保留原检查员任务。仅因 last_activity_at 很旧，不能断言旧实例已退出。不要盲目接管仍在活动的实例；可以先等待已有检查员提交。

## 结果局部修正

检查员按 instructions 写 .json.body，执行其中已经转义的 submit 命令。完整校验失败会说明错误字段、片段或名称，结果不发布：

1. 原检查员在当前上下文核对相关单元，局部改字段后再 submit。
2. 连续最多修正 3 次，修正不消耗 retry 次数。保留已经做过的判断，不重查整批，不猜 occurrence。
3. 仍无法确定时按任务指引回传任务 ID、blocked 和简短类别；不要删除真实候选来凑通过，或为此直接声称独立性降低。
4. submit 成功后才结束；step 仍会复验输入版本及结果。

submission-events 记录成功/无效提交，供后续测评区分格式修正与语言重查。脚本不会把“必要性依据已填写”说成“语言判断已验证”。

## 真正失败或重查

已启动检查员异常退出、无法继续检查时，确认旧执行结束后才恢复：

```text
python "<SKILL>/scripts/tasks.py" retry --work "<WORK>" --coordinator "<COORDINATOR>" --task "<任务id>"
python "<SKILL>/scripts/tasks.py" step --work "<WORK>" --coordinator "<COORDINATOR>" --compact
```

普通重查最多一次（初次加重查共两次）。第二次失败后再调用 retry，脚本自动标记 skipped；step 也会跳过第二次结果校验失败的任务。随后执行 step，继续其他任务直至交付。脚本无法自行感知宿主的内容拦截或崩溃，主 Agent 须根据宿主状态报告失败，不要把等待超时当成失败。

明确内容拦截、不可恢复错误或无法派发时，可直接跳过，无需用满重查次数。先确认该执行已停止，再调用：

```text
python "<SKILL>/scripts/tasks.py" skip --work "<WORK>" --coordinator "<COORDINATOR>" --task "<任务id>"
python "<SKILL>/scripts/tasks.py" step --work "<WORK>" --coordinator "<COORDINATOR>"
```

旧参数 retry --fallback 兼容为跳过，绝不触发主 Agent 补做。跳过不生成伪造结果，晚到提交被拒绝；已经接收的有效结果保留。报告简短显示未完成范围，初检缺失可点击定位段落；复核缺失的候选不发布为明确错误。格式局部修正、未启动重交接不消耗普通重查次数。

step/next/retry/skip/open/submit/partial 共用命令锁；只串行处理文件和状态，模型推理在锁外并发执行。异常退出留下 .coordinator.lock 时，确认占锁进程已退出再删除。提交采用短暂的 .publish-lock 空目录和同目录原子替换；若进程在提交中退出且结果尚未发布，确认原执行结束后删除相应遗留空锁目录，用原 job 再 submit，无需重查。

来源、规则或已接收结果变化时新建工作目录，不复用旧结论。旧版工作目录不直接续跑。


## 无子代理能力

子代理流水线无法启动时，说明缺少执行能力，不降级为主 Agent 检查。若已有部分结果，对无法执行的预留任务逐项 skip 后 step，或用下述 partial 交付已有成果。严格模式的短文同样需要子代理；缺少能力时不能宣称已经校对。用户预先明确选择的短文轻量模式按 SKILL.md 执行；一旦进入严格流水线，失败内容不回流主 Agent。

## 无法继续时交付部分 HTML

工作区至少已执行过一次 step。运行以下单个命令，脚本接收已有有效结果、汇总已复核意见并渲染 HTML：

```text
python "<SKILL>/scripts/tasks.py" partial --work "<WORK>" --coordinator "<COORDINATOR>"
```

交付返回的 report_path，明确说明是部分报告。未复核候选不作为明确错误展示；没有最终意见不代表原文无错。此命令生成独立快照，不覆盖完整报告、不停止正在运行的子代理；主 Agent 若要结束整个任务，应先通过宿主处理仍在执行的子任务。

submit 返回 submitted=true 但提示自动推进失败时，结果已经保存，不让子代理重复提交。主 Agent 执行 step 重试推进；若仍失败，按错误处理文件、权限或模板问题，不能假称报告已生成。

## 仅补做名称一致性

原任务完成后（包括名称阶段跳过），使用新补查目录：

```text
python "<SKILL>/scripts/recheck_names.py" --source-work "<原WORK>" --work "<新补查WORK>" --coordinator "<当前协调员ID>"
```

随后在新补查 WORK 按正常 step 流程派发名称检查与候选复核。必要时在准备命令中加 --max-input-chars 指定经部署确认的输入预算；默认仍为16000字符。

补查只复用已保存且指纹吻合的名称原字、位置和采集覆盖记录，重新从原文构建去重索引；允许读取旧版索引，不复用旧判断。原始源文件必须保持不变，原任务须已结束。不会补齐当时未采集到的名称；缺失批次仍会明示。输出为独立名称补查报告，不覆盖原报告，不重跑初检、不包含原报告其他修改。不要把补查报告当作完整重新校对。

协调员 ID 可通过只读 status --compact 查询。查询到旧身份不等于新会话继承身份；不同会话接管仍显式使用 --takeover，不自动借用原协调员 ID。

已绑定句柄的预留任务不会被 --resume-assigned 重派；确认宿主不再运行后按[宿主事件协议](host-events.md)释放绑定。结束消息与执行结束通知应按同一任务轮次去重。
