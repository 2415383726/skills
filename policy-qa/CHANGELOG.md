# 变更记录

## v1.0（2026-09-13）

初版。对应《内网 AI Agent Skill 资产建设清单与二开建议 V1.0》S04。本地化自 policy-lookup（Apache-2.0）。

- SKILL.md：四步作答流程（弄清问题→三渠道找依据→按格式作答→版本时效检查）、四道护栏（必引出处、检索不到明说、区分规定与理解、敏感个案升级）。
- references/answer-format.md：六字段答案格式（结论/依据/具体说明/例外/咨询渠道/来源）、拒答与降级话术表、质量 self-check。
- scripts/search.py：制度库关键词检索（递归遍历、或关系关键词、txt/md/docx 标准库解析、行/段落定位、JSON 输出）。
- tests：9 项机械回归；evals：3 个起步用例（标准查询、版本冲突、无依据拒答）。
