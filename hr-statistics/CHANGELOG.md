# 变更记录

## v1.0（2026-09-13）

初版。对应《内网 AI Agent Skill 资产建设清单与二开建议 V1.0》S09。本地化自 people-report（Apache-2.0）。

- scripts/stats.py：count-by 分组计数、pivot 两列交叉表、ages 年龄段结构与平均年龄（--asof 基准日）、retire 退休预测（男/女法定年龄参数、超龄未注销提示）；xlsx/csv 只读，多格式日期解析。
- SKILL.md：五步流程（范围口径→认识台账→统计→校验→报告）、硬边界（不排名不评价不决策、脱敏、口径变更声明）。
- references/metrics.md：本单位口径定义表、报告模板、四条硬边界（本地化自上游 Output 模板）。
- tests：7 项机械回归；evals：3 个起步用例（月报生成、拒绝排名、口径差异排查）。
