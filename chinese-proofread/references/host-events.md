# 宿主派发、通知与恢复

仅文件队列的调度者使用；不把本文传给校对者或复核者。

## 协调身份

首选宿主真实、稳定的当前会话 ID，使用 --coordinator；例如宿主已提供 DSH_SESSION_ID 时直接使用其实际值。优先调用示例：

```text
python "<SKILL>/scripts/tasks.py" step --work "<WORK>" --coordinator "<宿主实际会话ID>"
```

只有没有可靠会话 ID 时，才由脚本生成一次本协调会话身份文件（父目录须已存在）：

```text
python "<SKILL>/scripts/host_bridge.py" identity --output "<WORK>/coordinator.json"
python "<SKILL>/scripts/tasks.py" step --work "<WORK>" --coordinator-file "<WORK>/coordinator.json"
```

后续沿用同一文件路径，不需要记随机字符串。该标识只是本地协调身份，不冒充宿主 context_id，也不是隔离证据。新会话确认原协调者退出后，生成自己的身份文件并显式 --takeover；不能读取旧文件冒充旧会话。以下绑定示例用身份文件展示；已有宿主会话 ID 时统一改用 --coordinator。两者互斥，不混用。

## 派发后立即绑定句柄

每个 dispatch task 返回 event（任务 ID@执行轮次）。允许逐个创建后绑定，也允许先创建本次全部代理，再立即批量绑定；两种方式都不等待代理完成。逐个绑定示例：

```text
python "<SKILL>/scripts/host_bridge.py" bind --work "<WORK>" --coordinator-file "<WORK>/coordinator.json" --event "<task@attempt>" --handle "<真实宿主句柄>"
```

批量绑定：把创建工具实际返回的对应关系写入临时 JSON 列表，如 `[ {"event":"A-batch-001@1","handle":"实际句柄"} ]`，执行：

```text
python "<SKILL>/scripts/host_bridge.py" bind-many --work "<WORK>" --coordinator-file "<WORK>/coordinator.json" --bindings "<WORK>/bindings.json"
```

全部校验通过后一次写入 WORK/host-tasks.json；不放正文、候选或消息内容。绑定前收到 submitted/finished 时，先用创建返回的句柄与原 dispatch.event 补绑定，再处理通知；当前轮次已提交甚至已完成仍可绑定。若已发生重查、原对应关系不明或创建返回不确定，先查宿主，不猜轮次，不重派。

assigned 只表示尚无 open 回执，不等于没有创建代理。status 中 dispatch_state=recorded 表示已有句柄；unrecorded 只表示缺少记录，不能排除创建成功但绑定前中断。恢复前均核对宿主。--resume-assigned 自动排除已绑定句柄的任务。

确认宿主任务未运行、尚未领取且没有结果时，才释放绑定并恢复：

```text
python "<SKILL>/scripts/host_bridge.py" release --work "<WORK>" --coordinator-file "<WORK>/coordinator.json" --event "<task@attempt>" --confirmed-not-running
python "<SKILL>/scripts/tasks.py" step --work "<WORK>" --coordinator-file "<WORK>/coordinator.json" --resume-assigned
```

stalled 仅提醒长期未领取，不判断已运行任务是否存活。运行中的代理异常须向宿主查询，不因耗时就重启。

## 按已收到的通知推进

异步宿主在回合结束后发送通知时，派发后交还控制权就是正常等待，无须模拟 barrier 或建立后台循环。有原生等待工具的宿主也可使用它。

“Agent sent a message”与“Background subagent finished”可能属于同一次执行。仅 submitted/blocked 的结束消息或执行结束通知属于本节事件；中间进度消息不触发完成处理。

事件优先直接使用那次派发返回的 event，不需要每次 lookup。通知只含任务 ID 时，只有明确知道它属于哪一次派发才可使用该轮次；不能把“当前 attempt”当成通知的轮次，重查前的通知可能延迟到达。尤其重查后不确定时必须按宿主句柄 lookup；通知没有句柄且无法确认对应关系时先查宿主，不能默认 @1 或猜 @2。

lookup 只读并显示 handled：

```text
python "<SKILL>/scripts/host_bridge.py" lookup --work "<WORK>" --handle "<通知中的宿主句柄>"
python "<SKILL>/scripts/tasks.py" step --work "<WORK>" --coordinator-file "<WORK>/coordinator.json" --event "<task1@attempt>" --event "<task2@attempt>"
```

每次只处理已经收到的通知：逐条唤醒时，一条新完成通知立即 step 一次即为合规；同次唤醒已有多条才合并。不要为凑批等待未来通知，以免空闲槽位迟迟得不到补充。同一事件去重，handled=true 的通知不用再次 step。传入的 event 必须来自实际派发与通知，不生成随机 nonce/tick，不为规避宿主告警改变参数。宿主仍告警时停止重复调用，依据已有进度解释并按宿主恢复机制处理，不能声称参数变化保证消除告警。

step 的 events 说明通知属于 new、already_handled 或 stale。全部已处理或旧轮次时返回 ignore_event：不预留任务；reservations 仍会列出尚未领取的预留任务，先核对是否有前次交接中断，再交还控制权等待新通知。缺少提交回执则返回 repair，先核对宿主。通知不修改检查结果，也不凭消息把任务标成完成。

submit 已经接收结果并可能推进阶段，因此完成数量可能早于通知增加；不要把“本次计数没加一”当作任务丢失。以任务回执和分阶段 progress 为准。

step 若已返回派发但交接中断，使用 status、句柄映射和 --resume-assigned 恢复；通知去重不能替代恢复。无完成通知时仍可执行 wait_command；主动恢复或首次启动可以不带 --event。
