# 变更记录

## v1.0（2026-09-13）

初版。对应《内网 AI Agent Skill 资产建设清单与二开建议 V1.0》S08。本地化自 explore-data（Apache-2.0）。

- scripts/ledger.py：check（身份证校验码与出生/性别/年龄交叉、唯一键重复、必填缺失、日期格式混用与未来日期、枚举漂移、占位值、完整性分级）＋clean（显式 opt-in 的清洗副本）；xlsx/csv 只读，UTF-8/GBK 兼容，markdown/JSON 输出。
- SKILL.md：五步体检流程、红黄判级、敏感字段打码、只读红线。
- references/ledger-checklist.md：主键粒度、字段口径、字典映射、逻辑交叉、上报格式五节＋完整性分级表。
- tests：14 项机械回归（校验码向量、查重、必填、交叉校验、漂移、清洗副本）；evals：3 个起步用例。
