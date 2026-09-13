# sop-capture（SOP 流程沉淀）

把口头讲述或零散说明的办事流程沉淀为标准 SOP：RACI 责任矩阵、文本流程图、详细步骤、例外场景、表单系统清单。本地化自 anthropics/knowledge-work-plugins 的 process-doc。

## 资产卡

| 字段 | 内容 |
| --- | --- |
| 内部名称 | SOP流程沉淀（sop-capture） |
| Owner | 高阳（198506） |
| 版本 | v1.0（2026-09-13） |
| 规划编号 | S12（建设清单与二开建议 V1.0，P0 第一梯队） |
| 触发条件 | 把流程经验固化为 SOP、新人接手交接、办事流程成文。不用于制度文件起草（chinese-drafting）、制度条款查询（policy-qa） |
| 输入 | 口述流程、零散笔记、现有制度节选、表单截图；用户对补缺问题的回答 |
| 输出 | SOP 文件（目的/范围/RACI/文本流程图/详细步骤/例外场景/表单系统/版本信息）＋待补信息清单 |
| 业务规则 | 访谈问题清单 references/interview.md；三关自检（新人测试/例外覆盖/责任边界）references/quality-checklist.md |
| 引用依据 | 不虚构步骤与责任人；口述缺失标〔待确认〕；制度与口述冲突时标注不取舍；草稿版与 v1.0 分离 |
| 依赖工具 | 内网模型宿主；本地文件读写；无脚本 |
| 数据权限 | 内部：流程内容仅本地处理 |
| 写操作 | 无 |
| 评测集 | evals/evals.json（3 个起步用例） |
| 许可证 | Apache-2.0（随目录 LICENSE.txt，复制自 knowledge-work-plugins） |

## 上游来源与修改说明

- 上游：anthropics/knowledge-work-plugins · operations/process-doc（Apache-2.0）。
- 保留：SOP 输出骨架（Purpose/Scope/RACI/Process Flow/Detailed Steps Who-When-How-Output/Exceptions/Metrics/Related Documents）、三条实战经验（从口述开始不用整理、例外最有价值、点名到人）、知识库查重提示。
- 修改（本地化）：流程场景替换为机关高频流程（入职调岗、请假、材料报送、账号开通、数据上报、会议筹备）；新增访谈问题清单（九节提问法）与三关质量自检（对应 docx 验收指标：新人能否独立完成、例外覆盖率、责任边界）；"点名人"改为"写岗位、人名备注"的机关惯例；新增待补信息清单与草稿版/v1.0 机制；表单与系统清单独立成节。

## 安装与使用

将整个 `sop-capture` 文件夹放入宿主 skills 目录，刷新技能列表。
