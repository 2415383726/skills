# hr-statistics（人力资源统计分析）

从人员台账生成结构统计与月报季报：部门人数、编制实有、学历年龄结构、管理幅度、退休预测，口径透明、可复现、只出汇总数。本地化自 anthropics/knowledge-work-plugins 的 people-report。

## 资产卡

| 字段 | 内容 |
| --- | --- |
| 内部名称 | 人力资源统计（hr-statistics） |
| Owner | 高阳（198506） |
| 版本 | v1.0（2026-09-13） |
| 规划编号 | S09（建设清单与二开建议 V1.0，P0 第一梯队） |
| 触发条件 | 人事月报季报、人员结构统计、退休预测、编制实有对比。不用于台账体检（ledger-checkup）、临时数据问答（excel-analysis）、干部个案与薪酬分析（高敏，默认不处理） |
| 输入 | 人员台账 xlsx/csv；范围（在编/聘用）、基准日、单位口径规定 |
| 输出 | 结构报告：领导摘要＋关键指标（含趋势）＋分项分析＋异常提示＋口径与方法；全部为汇总数 |
| 业务规则 | 口径定义与报告模板见 references/metrics.md；分项和＝合计；口径变更必须声明 |
| 引用依据 | 每个数字可复现（命令＋基准日）；不排名不评价不决策；个人明细不进报告 |
| 依赖工具 | 内网模型宿主；scripts/stats.py（Python 3.8+ 标准库：count-by/pivot/ages/retire） |
| 数据权限 | 高敏：台账仅本地处理；薪酬考核等字段默认不使用 |
| 写操作 | 无（台账只读） |
| 评测集 | evals/evals.json（3 个起步用例）；脚本机械回归 tests/（7 项） |
| 许可证 | Apache-2.0（随目录 LICENSE.txt，复制自 knowledge-work-plugins） |

## 上游来源与修改说明

- 上游：anthropics/knowledge-work-plugins · human-resources/people-report（Apache-2.0）。
- 保留：五步法（理解问题→识别数据→统计→带口径呈现→建议）、报告模板（Executive Summary/Key Metrics 趋势表/Methodology）、"需要哪些字段"的字段清单沟通。
- 修改（本地化）：attrition/diversity/eNPS 等国外指标替换为编制实有、学历职称年龄结构、政治面貌、管理幅度、退休预测等机关口径（docx S09 指定）；HRIS 连接器替换为本地台账 Excel/CSV；新增"三不"硬边界（不排名不评价不决策）与脱敏、口径变更声明规则；脚本化保证可复现（docx 验收指标）。

## 安装与使用

将整个 `hr-statistics` 文件夹放入宿主 skills 目录，刷新技能列表。运行机械回归：

```bash
python -m unittest discover -s hr-statistics/tests -v
```
