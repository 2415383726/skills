# meeting-minutes（会议纪要督办）

从转写文字或笔记生成纪要草稿、领导速览、督办台账：决议/讨论/行动项三分，行动项四要素缺一标"待确认"，绝不编造。本地化自 anthropics/knowledge-work-plugins 的 meeting-briefing（action tracking 范式）。

## 资产卡

| 字段 | 内容 |
| --- | --- |
| 内部名称 | 会议纪要督办（meeting-minutes） |
| Owner | 高阳（198506） |
| 版本 | v1.0（2026-09-13） |
| 规划编号 | S11（建设清单与二开建议 V1.0，P0 第一梯队） |
| 触发条件 | 整理会议纪要、提取决议、生成督办台账、查逾期。不用于会前准备（meeting-brief）、录音转写本身（需宿主能力） |
| 输入 | 录音转写文字、笔记、议程、参会名单；既有督办台账（检查时） |
| 输出 | 纪要草稿＋领导速览＋督办台账 CSV（固定九列）；check 模式输出待补齐与逾期清单 |
| 业务规则 | 纪要格式见 references/minutes-format.md；行动项四要素与提取规则见 references/actions.md |
| 引用依据 | 决议、责任人、日期不虚构；缺字段标"待确认"（脚本不生成默认值）；模糊表述保留原话 |
| 依赖工具 | 内网模型宿主；scripts/actions.py（Python 3.8+ 标准库：build/check） |
| 数据权限 | 内部/敏感：纪检人事内容按密级管理，仅本地处理 |
| 写操作 | 无系统写回；台账为本地 CSV，分发由用户执行 |
| 评测集 | evals/evals.json（3 个起步用例）；脚本机械回归 tests/（8 项） |
| 许可证 | Apache-2.0（随目录 LICENSE.txt，复制自 knowledge-work-plugins） |

## 上游来源与修改说明

- 上游：anthropics/knowledge-work-plugins · legal/meeting-briefing 的 Action Item Tracking 部分（Apache-2.0）。
- 保留：行动项最佳实践（具体、唯一责任人、明确日期、注明依赖、四类型区分）、跟踪节奏（高每日/中每周/低下次会议、逾期升级）。
- 修改（本地化）：邮件/日历/CLM 渠道去除；新增纪要格式规范（机关纪要结构、决议与讨论的区分）；"不编造"上升为硬红线并脚本化——build 不生成默认责任人与日期，缺字段强制"待确认"；check 模式新增逾期排查（docx 验收：虚构率=0、决议召回率）。

## 安装与使用

将整个 `meeting-minutes` 文件夹放入宿主 skills 目录，刷新技能列表。运行机械回归：

```bash
python -m unittest discover -s meeting-minutes/tests -v
```
