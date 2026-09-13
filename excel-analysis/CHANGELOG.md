# 变更记录

## v1.0（2026-09-13）

初版。对应《内网 AI Agent Skill 资产建设清单与二开建议 V1.0》S06。本地化自 analyze（Apache-2.0）。

- scripts/table.py：xlsx（标准库解包）/csv 读取（UTF-8/GBK 兼容），profile 列画像（类型推断、空值、范围、不同值）、preview 预览、groupby 分组聚合（sum/avg/max/min/count）；千分位与百分比自动换算、xlsx 日期序列号转换、--header 标题行适配、--sheet 多工作表。
- SKILL.md：六步流程（问题分级→口径→取数→交付前校验五项→三级呈现→补图），计算过程必须保留。
- references/data-rules.md：内网口径规则（标题行、合并表头、合计行剔除、单位统一、日期规范化、组织层级汇总、异常三要素）。
- tests：10 项机械回归；evals：3 个起步用例。
