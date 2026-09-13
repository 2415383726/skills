# chinese-review（材料审稿）

报送前对成文材料做内容把关：审逻辑、审数字、审时间、审依据、审一致性，输出定位到段落的问题清单和三档总评。本地化组合自 anthropics 的 validate-data 与 doc-coauthoring。

## 资产卡

| 字段 | 内容 |
| --- | --- |
| 内部名称 | 材料审稿（chinese-review） |
| Owner | 高阳（198506） |
| 版本 | v1.0（2026-09-13） |
| 规划编号 | S03（建设清单与二开建议 V1.0，P0 第一梯队） |
| 触发条件 | "审一下/把关/看看有没有问题/检查矛盾/核数字"等对成文材料的内容审读。不查错别字标点（chinese-proofread），不代笔起草（chinese-drafting） |
| 输入 | 成文材料（粘贴或本地文件）；可选：上级要求、参考文件、数据表 |
| 输出 | 问题清单（严重/一般/建议，含定位、理由、建议）＋三档总评（可直接报送/修改后报送/需重大修改）＋审查范围声明 |
| 业务规则 | 七步流程：语境→通读→一致性清单→数字抽查→陷阱排查→读者视角→出清单；清单见 references/ |
| 引用依据 | 每条意见必须给定位和理由；允许零问题；查过什么没查什么必须声明 |
| 依赖工具 | 内网模型宿主；本地文件读写；无脚本 |
| 数据权限 | 内部/敏感：材料内容仅本地处理 |
| 写操作 | 无（不回写用户文件，修订建议不直接改稿） |
| 评测集 | evals/evals.json（3 个起步用例） |
| 许可证 | Apache-2.0（随目录 LICENSE.txt，复制自 knowledge-work-plugins） |

## 上游来源与修改说明

- 上游一：anthropics/knowledge-work-plugins · data/validate-data（Apache-2.0）。保留其 QA 方法论骨架：交付前检查清单、常见陷阱目录、数字重算抽查、三档总评（Ready/Caveats/Revision → 可直接报送/修改后报送/需重大修改）、Validation Report 输出结构。
- 上游二：anthropics/skills · doc-coauthoring。取其读者测试思想（新读者找盲点、矛盾、歧义、空话），改造为 reader-checks.md，含"领导三问"内网化。
- 修改（本地化）：SQL/数据仓库语境（join、时区、GROUP BY）替换为公文材料语境——数字互算、口径漂移、时段不可比、跨表不一致；新增 docx S03 指定的一致性维度（题文、时间逻辑、主体称谓、政策依据、措施-问题对应、目标-指标、附件引用）；判级三级（严重/一般/建议）与"允许零问题、声明审查边界"的内网治理要求。
- 与 chinese-proofread 分工：本技能审内容不审字词，已在 description 和 SKILL.md 双向声明边界。

## 安装与使用

将整个 `chinese-review` 文件夹放入宿主 skills 目录，刷新技能列表。建议流水线：chinese-drafting 起草 → 本技能审内容 → chinese-proofread 校字词 → 报送。

## 测试

无脚本，无需机械回归；语言质量按 evals/evals.json 用例在真实内网模型上试跑。
