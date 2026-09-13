# report-check（报表智能复核）

报送前对报表做数字把关：脚本机械检查每一个数值列，模型做语义复核，输出红黄绿问题清单和三档总评。只读不改原表。本地化自 anthropics/knowledge-work-plugins 的 validate-data。

## 资产卡

| 字段 | 内容 |
| --- | --- |
| 内部名称 | 报表智能复核（report-check） |
| Owner | 高阳（198506） |
| 版本 | v1.0（2026-09-13） |
| 规划编号 | S07（建设清单与二开建议 V1.0，P0 第一梯队） |
| 触发条件 | "核一下这张表""报送前把关""检查数字对不对"。不用于数据分析出结论（excel-analysis）、内容文字审读（chinese-review）、导入前字段体检（ledger-checkup） |
| 输入 | xlsx/csv 报表；可选：底表、口径说明、历史报表 |
| 输出 | 红黄绿问题清单（定位＋复核依据＋建议更正值）＋三档总评＋复核范围声明 |
| 业务规则 | 机械五查（合计勾稽/负值/可疑比率/跳变/空值解析）＋语义清单（口径/基期/勾稽/加权/展示），见 references/ |
| 引用依据 | 每条问题给定位与复核公式；查不了的写进"待用户确认"；允许零问题 |
| 依赖工具 | 内网模型宿主；scripts/check.py（Python 3.8+ 标准库） |
| 数据权限 | 内部/敏感：报表内容仅本地处理 |
| 写操作 | 无（只读，不回写原表，建议值须用户确认） |
| 评测集 | evals/evals.json（3 个起步用例）；脚本机械回归 tests/（11 项） |
| 许可证 | Apache-2.0（随目录 LICENSE.txt，复制自 knowledge-work-plugins） |

## 上游来源与修改说明

- 上游：anthropics/knowledge-work-plugins · data/validate-data（Apache-2.0）。
- 保留："分享之前先复核"的定位、机械检查与语义判断分离、三档评估（Ready/Caveats/Revision → 可以报送/核实后报送/需更正后报送）、Validation Report 式输出。
- 修改（本地化）：SQL/BI 语境替换为机关 Excel 报表语境；新增只读红线与红黄绿判级（红色=确定性不一致、黄色=可疑待核）；机械检查固化为 scripts/check.py（合计分组勾稽、负值、0%/100% 可疑比率、中位数 3 倍跳变、空值、全角数字解析失败）；语义清单按机关口径改造（口径漂移、基期、跨表勾稽、加权平均、图表歪曲）。
- 与 excel-analysis 分工：本技能"找错"，分析技能"算数"；与 chinese-review 分工：本技能管表和数字，材料审稿管文字内容。

## 安装与使用

将整个 `report-check` 文件夹放入宿主 skills 目录，刷新技能列表。运行机械回归：

```bash
python -m unittest discover -s report-check/tests -v
```
