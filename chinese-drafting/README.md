# chinese-drafting（材料起草）

把"要点和零散素材"变成"结构合规、事实可溯源、能直接进入审稿环节的中文办公材料初稿"，并用待补事实清单把缺口一次说清。

## 资产卡

| 字段 | 内容 |
| --- | --- |
| 内部名称 | 材料起草（chinese-drafting） |
| Owner | 高阳（198506） |
| 版本 | v1.0（2026-09-13） |
| 规划编号 | S01（建设清单与二开建议 V1.0，P0 第一梯队） |
| 触发条件 | 用户要"写、起草、拟、整理"工作总结、工作计划、情况汇报、请示、通知、会议材料、述职材料、经验交流材料、讲话稿/提纲；给要点求成文。不用于错别字校对（chinese-proofread）、内容审稿、公文版式 |
| 输入 | 用户要点/素材、历史同类材料、上级文件、单位模板；目标读者、篇幅、时间范围（后三项缺失时可按默认值开工） |
| 输出 | 结构化初稿（`draft.md` 或聊天内短文）＋待补事实清单；不带占位符并通过 check 的稿子才称"定稿" |
| 业务规则 | 公共规则见 `references/rules.md`；每类材料的结构、常用表达、禁忌、篇幅、事实核验点见 `references/types/`；占位符与定稿条件见 `references/fact-gap.md` |
| 引用依据 | 唯一硬约束：初稿中每个事实性内容必须来自用户素材，缺失一律【待补】占位，不编造数字、文号、人名 |
| 依赖工具 | 内网模型宿主；本地文件读写；`scripts/facts.py`（Python 3.8+ 仅标准库，缺失时可人工清点交付） |
| 数据权限 | 内部/敏感：材料内容仅本地处理，不外传、不联网；涉及人事干部等敏感表述由用户自行把关 |
| 写操作 | 无系统写回；仅在用户指定位置生成新文件，不覆盖用户原始素材 |
| 评测集 | `evals/evals.json`（3 个起步用例，随真实材料扩充）；脚本机械回归 `tests/` |
| 许可证 | 本包随仓库 MIT；上游 doc-coauthoring（anthropics/skills）仅为三阶段共创与交互模式的思路参考，未复制其文本 |

## 安装与使用

将整个 `chinese-drafting` 文件夹放入宿主 skills 目录，确保 `chinese-drafting/SKILL.md` 直接存在，刷新技能列表即可。用户直接说"帮我写个……"即触发；也可用 `/skill chinese-drafting` 强制加载。

典型一次使用：

```bash
# 生成骨架（可选，模型也可直接手写）
python chinese-drafting/scripts/facts.py new work-summary --title "××单位2025年工作总结" -o draft.md
# 交付前扫描待补事项，保证一个不漏
python chinese-drafting/scripts/facts.py scan draft.md --out 待补事实清单.md
# 用户回填素材后、宣布定稿前
python chinese-drafting/scripts/facts.py check draft.md
```

设计沿用三阶段共创流程（收集素材 → 按类型定结构逐段起草 → 读者自查后交付），每种材料只加载自己那份类型规则，其余规则按需渐进读取。

## 与流水线的衔接

按建设清单规划的材料生产线：**起草（本技能）→ 材料审稿 → 公文校对（chinese-proofread）→ 格式输出**。本技能交付时提示衔接；审稿技能建成前，先由用户人工审稿。

## 测试

```bash
python -m unittest discover -s chinese-drafting/tests -v
```

测试只验证脚本行为（扫描定位、类别判断、退出码、9 类骨架完整、UTF-8/GBK 兼容），不代表起草语言质量。语言质量按 `evals/evals.json` 用例在真实内网模型上试跑，与用户一起复盘后迭代规则。
