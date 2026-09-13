# excel-analysis（Excel/台账数据分析）

用自然语言回答 Excel/CSV 台账数据问题：查数、汇总、找异常、看趋势，交付必附可复核的计算过程。本地化自 anthropics/knowledge-work-plugins 的 analyze。

## 资产卡

| 字段 | 内容 |
| --- | --- |
| 内部名称 | Excel数据分析（excel-analysis） |
| Owner | 高阳（198506） |
| 版本 | v1.0（2026-09-13） |
| 规划编号 | S06（建设清单与二开建议 V1.0，P0 第一梯队） |
| 触发条件 | 对本地 xlsx/csv 提数据问题：查数、分组汇总、趋势、异常。不用于报表纠错（report-check）、导入前体检（ledger-checkup）、固定口径人事报告（hr-statistics） |
| 输入 | 本地 xlsx/csv 文件＋自然语言问题＋口径说明 |
| 输出 | 结论＋关键指标表＋异常点＋计算过程（命令与中间结果）；正式场合加汇报摘要 |
| 业务规则 | 六步流程（理解问题→口径→取数→校验→呈现→补图）；内网口径规则见 references/data-rules.md |
| 引用依据 | 结论由数据支撑；校验五项（行数/空值/量级/断档/合计）不过不带病交付 |
| 依赖工具 | 内网模型宿主；scripts/table.py（Python 3.8+ 标准库：xlsx/csv 读取、profile/preview/groupby） |
| 数据权限 | 内部/敏感：输出只给汇总数，不展开个人明细 |
| 写操作 | 无（原文件只读，输出写新文件） |
| 评测集 | evals/evals.json（3 个起步用例）；脚本机械回归 tests/（10 项） |
| 许可证 | Apache-2.0（随目录 LICENSE.txt，复制自 knowledge-work-plugins） |

## 上游来源与修改说明

- 上游：anthropics/knowledge-work-plugins · data/analyze（Apache-2.0）。
- 保留：问题分级（快速查数/完整分析/正式报告）、六步工作流、交付前校验五项、三级呈现结构、"结果验证后才交付"纪律。
- 修改（本地化）：数据仓库/SQL 取数替换为本地 xlsx/csv 读取（table.py：中文字段、标题行 --header、合并表头、千分位与百分比、日期序列号转换、groupby 聚合）；图表依赖（data-visualization skill）降级为"内网无图表库时给分组表＋文字解读"；新增内网口径规则（合计行剔除、单位统一、组织层级汇总、异常三要素）。

## 安装与使用

将整个 `excel-analysis` 文件夹放入宿主 skills 目录，刷新技能列表。运行机械回归：

```bash
python -m unittest discover -s excel-analysis/tests -v
```
