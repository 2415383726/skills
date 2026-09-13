# skills

这个仓库用于持续沉淀我在日常工作中搭建和使用的 agent skills，面向内网环境（Windows 7 / 麒麟 V10、Python 3.8+ 标准库、无外网）。目前收录十三个技能，对应《建设清单与二开建议 V1.0》的 **P0 第一梯队已全部落地**。每个技能是仓库下的一个独立文件夹，整体拷入宿主的 skills 目录即可使用。

建设方法遵循 skill-creator 规范：能借鉴的上游开源 skill 以其为底本做内网本地化（保留 Apache-2.0 许可证与逐项修改说明），自研项按"草稿 → 测试 → 与用户复盘迭代"的循环建设。每个技能都带 README（资产卡）、CHANGELOG（变更记录）和 evals（起步测评用例）；带脚本的技能另有机械回归测试。

---

## 一图总览：三条产品线

```text
材料线  chinese-briefing → chinese-drafting → chinese-review → chinese-proofread
        （工作简报）        （材料起草）        （材料审稿）       （文字校对）

制度线  policy-qa ⇄ policy-diff
        （制度问答）    （新旧对比）

数据线  ledger-checkup → excel-analysis → report-check → hr-statistics
        （台账体检）     （数据分析）      （报表复核）    （人事统计）

会议线  meeting-brief → meeting-minutes → sop-capture
        （会前材料）    （纪要督办）      （SOP 沉淀）
```

| # | 技能 | 一句话 | 规划 | 上游 |
| --- | --- | --- | --- | --- |
| 1 | [chinese-proofread](#chinese-proofread-中文文字校对已有) | 查错别字、多字漏字、标点 | 已有 | — |
| 2 | [chinese-briefing](#chinese-briefing-工作简报s02) | 写周报月报、工作动态、FAQ、领导更新 | S02 | internal-comms |
| 3 | [chinese-drafting](#chinese-drafting-材料起草s01) | 起草 9 类公文材料初稿＋待补事实清单 | S01 | doc-coauthoring（思路） |
| 4 | [chinese-review](#chinese-review-材料审稿s03) | 审逻辑、数字、时间、依据，出问题清单 | S03 | validate-data + doc-coauthoring |
| 5 | [policy-qa](#policy-qa-制度政策问答s04) | 制度问题带条款出处回答，查不到不猜 | S04 | policy-lookup |
| 6 | [policy-diff](#policy-diff-制度新旧对比s05) | 新旧制度条款对齐、变化判类、影响清单 | S05 | 自研 |
| 7 | [ledger-checkup](#ledger-checkup-台账数据体检s08) | 花名册导入前体检：身份证校验、查重 | S08 | explore-data |
| 8 | [excel-analysis](#excel-analysis-excel-数据分析s06) | 用自然语言问 Excel，结论附计算过程 | S06 | analyze |
| 9 | [report-check](#report-check-报表智能复核s07) | 报表数字把关：合计勾稽、跳变、可疑比率 | S07 | validate-data |
| 10 | [hr-statistics](#hr-statistics-人力资源统计s09) | 人员结构月报、退休预测，只汇总不排名 | S09 | people-report |
| 11 | [meeting-brief](#meeting-brief-会前材料s10) | 一页会前简报＋准备缺口诚实标注 | S10 | meeting-briefing |
| 12 | [meeting-minutes](#meeting-minutes-会议纪要督办s11) | 纪要草稿＋督办台账，缺责任人标待确认 | S11 | meeting-briefing |
| 13 | [sop-capture](#sop-capture-sop-流程沉淀s12) | 把口头流程沉淀为 SOP（RACI＋例外场景） | S12 | process-doc |

---

## 材料生产线

### chinese-proofread（中文文字校对｜已有）

仓库的第一个技能，作为后续技能的质量标杆独立演进：校对公文、通知、报告、讲话稿中的错别字、多字漏字、用字和标点问题，文件队列另查文内名称一致性。默认严格模式（两路独立初检＋候选复核，需宿主子代理），约 500 字以内的短文可走轻量模式；长文生成左右对照、可双向定位的离线 HTML 报告。**只查字词，不做润色、不核事实**——与审稿技能分工。

安装与使用详见 [chinese-proofread/INSTALL.md](chinese-proofread/INSTALL.md)，测评与规则维护见其 references 目录。

### chinese-briefing（工作简报｜S02）

**做什么**：把零散进展写成 30-60 秒能读完的内部沟通成文。四种格式分治：**周报/月报**用 3P 结构（进展、计划、问题，来自上游 internal-comms 的严格格式）；**工作动态/单位简报**用 Newsletter 式分板块（15-25 条，每条 1-2 句注明来源）；**FAQ** 汇总高频问题并基于官方口径作答；**领导更新等其他沟通**遵循"结论先行 → 进展 → 数据 → 问题 → 下一步 → 需协调"的固定信息顺序。

**什么时候用**：说"写个周报""整一份简报""发个工作动态""汇总一下大家最近在问什么""给领导汇报下进展"。

**输入 → 输出**：粘贴的进展、纪要、台账 → 按类型固定格式的成文（领导速览 200 字内 / 一页简报 500-800 字 / 正式汇报版 1000-1500 字，三档按读者选）。

**规则与边界**：数据必须有来源，素材里没有的写"【数据待补】"；问题项没有责任人标"待确认"，不替用户指派；不用于对外正式公文（那是材料起草的事）。

**上游与许可**：internal-comms（Apache-2.0，随目录 LICENSE.txt），README 记录逐项修改说明。纯规则技能，无脚本。

### chinese-drafting（材料起草｜S01）

**做什么**：把要点和零散素材变成结构合规、事实可溯源的公文初稿，覆盖 9 类材料——工作总结、工作计划、情况汇报、请示、通知、会议材料、述职材料、经验交流材料、讲话稿/提纲。每类材料一份独立规则文件（结构骨架、常用表达、禁忌、篇幅、事实核验点），起草哪类只读哪份。

**什么时候用**：说"帮我写个工作总结/通知/请示/述职""把这几条要点整成材料""给领导写个讲话提纲"。

**输入 → 输出**：素材（要点、历史材料、上级文件）→ `draft.md` 初稿 ＋ 待补事实清单。**唯一硬约束：素材里没有的时间、数字、人名、文号一律写`【待补：类别－说明】`占位，不编造**——占位符由脚本保证一个不漏。

**怎么用**：
```bash
python chinese-drafting/scripts/facts.py new work-summary --title "××单位2025年工作总结" -o draft.md  # 生成骨架
python chinese-drafting/scripts/facts.py scan draft.md --out 待补事实清单.md   # 交付前扫描，保证不漏
python chinese-drafting/scripts/facts.py check draft.md                        # 定稿闸口，有占位不放行
```
两种模式：素材齐了说"直接写"就走快速模式；重要材料走结构化模式（先确认骨架再逐段写，主体先行、总述最后）。

**测试**：facts.py 20 项机械回归。上游 doc-coauthoring（anthropics/skills）仅作三阶段共创与交互模式参考，未复制文本。

### chinese-review（材料审稿｜S03）

**做什么**：报送前对成文材料做内容把关——审逻辑、审数字、审时间、审依据、审前后一致性，输出定位到段落的问题清单（严重/一般/建议三级）和三档总评（可直接报送/修改后报送/需重大修改）。七步流程：明确语境 → 通读 → 一致性清单（题文、数字互算、时间逻辑、主体称谓、政策依据、措施与问题对应、附件引用）→ 数字抽查 → 常见陷阱排查（口径漂移、时段不可比、平均数再平均等）→ 读者视角检查 → 出清单。

**什么时候用**：说"帮我审一下这篇""报送前把把关""看看有没有前后矛盾""核一下数字"。

**输入 → 输出**：成文材料（可附上级要求、数据表）→ 问题清单（每条含位置、理由、建议）＋总评＋审查范围声明。

**规则与边界**：每条意见必须给定位和理由，**允许零问题**；查过什么、没查什么（如无底表未核数据）必须声明；只审内容不查错别字——字词交 chinese-proofread。

**上游与许可**：validate-data + doc-coauthoring（Apache-2.0），README 记录修改说明。纯规则技能。

---

## 制度线

### policy-qa（制度政策问答｜S04）

**做什么**：回答制度类问题并**强制带出处**——结论、文件名＋文号＋条款原文引用、大白话解释、例外情形、咨询渠道、来源六字段缺一不可。三渠道找依据：本地制度库文件夹（脚本检索）、用户粘贴的制度文本、宿主知识库；都查不到就明确回答"未检索到明确规定"，**绝不猜**。自动识别新旧版本冲突，提示以新版为准。

**什么时候用**：问"年休假怎么休""差旅报销标准是多少""这个流程找谁批""制度里有没有规定"。

**怎么用**：
```bash
python policy-qa/scripts/search.py "D:\zidu" "年休假" "带薪年休假"   # 制度库检索，支持 txt/md/docx
```

**规则与边界**：引用条文不改写原意、不编文号；"规定如此"与"个人理解"分开标注；干部人事敏感个案升级为线下咨询。

**测试**：search.py 9 项机械回归。上游 policy-lookup（Apache-2.0）。

### policy-diff（制度新旧对比｜S05）

**做什么**：对比新旧两版制度文件，产出可直接用于宣贯的对比报告——变化总览、逐条差异判类（实质修改/口径变化/流程变化/责任变化/时限变化/文字性修改/编号调整七类）、影响对象清单（必须同步修改 vs 建议同步更新的表单、流程、FAQ、系统、台账）、执行注意事项、待确认事项。条款做语义对齐而非纯文本 diff：支持中文条号（"第十二条"），能识别编号调整、拆分合并，并专门防范两个高危误判——"文字没变但含义变"（引用的外部文件换版了）和"文字变了但意思没变"。

**什么时候用**：说"对比一下新旧版本""这次修订改了什么""制度修订后要注意什么"。

**怎么用**：
```bash
python policy-diff/scripts/clauses.py align 旧办法.docx 新办法.docx --out 对齐报告.md
```
脚本做确定性的拆分与对齐，语义判类和影响解读由模型基于对照表完成，拿不准的进"待确认"。

**测试**：clauses.py 13 项机械回归。docx 规划明示自研实现（仅借鉴上游工作流）。

---

## 数据生产线

### ledger-checkup（台账数据体检｜S08）

**做什么**：人员台账、花名册导入系统或上报前的字段级体检。机械检查：**身份证校验码（GB 11643）及出生段有效性**、身份证出生段与出生日期列交叉、性别位与性别列交叉、年龄列推算核对、唯一键（身份证/工号）重复、必填缺失、同列日期格式混用、未来日期、枚举值漂移（"财务科 "与"财务科"这种空格差异）、占位值（N/A、未知）。输出红（必须处理）黄（建议核对）错误行清单＋字段完整性分级＋修复建议。可选生成清洗副本（去空格、日期规范化），**原文件永不改动**。

**什么时候用**：说"这表要导入系统，帮我查查""上报前体检一下""花名册有没有问题"。

**怎么用**：
```bash
python ledger-checkup/scripts/ledger.py check 花名册.xlsx --key 身份证号 --key 工号 --required 姓名 --asof 2026-09-13
python ledger-checkup/scripts/ledger.py clean 花名册.xlsx 花名册_clean.csv   # 可选，仅用户明示时
```

**规则与边界**：身份证号在报告中打码或只报行号；部门名称映射、字段口径等脚本查不了的列入待确认。

**测试**：ledger.py 14 项机械回归。上游 explore-data（Apache-2.0）。

### excel-analysis（Excel 数据分析｜S06）

**做什么**：用自然语言回答台账数据问题——查数、分组汇总、找异常、看趋势。六步流程：理解问题并分级（快速查数/完整分析/正式报告）→ 确认口径 → 取数计算 → **交付前校验五项**（行数、空值、量级、断档、分项合计）→ 呈现结论 → 视需要补图。**每个结论附所用命令和中间结果**，第二个人能算出同样的数。支持中文字段、标题行、合并表头、千分位、百分比、日期序列号。

**什么时候用**：丢来一个 Excel/CSV 说"这个表里……多少""按部门汇总一下""哪个科室异常""帮我分析这份数据"。

**怎么用**：
```bash
python excel-analysis/scripts/table.py profile 台账.xlsx --header 1                    # 列画像
python excel-analysis/scripts/table.py groupby 台账.xlsx --by 科室 --agg sum:金额      # 分组聚合
```

**规则与边界**：只读原文件；结论必须有数据支撑；异常按"数值＋判定标准＋建议动作"三要素呈现；个人敏感信息只出汇总数。

**测试**：table.py 10 项机械回归。上游 analyze（Apache-2.0）。

### report-check（报表智能复核｜S07）

**做什么**："数字版公文校对"——报送前对报表做数字把关。脚本机械检查每一个数值列：**合计行与分组数据勾稽**、人数/金额负值、0%/100% 可疑比率、超中位数 3 倍的跳变、空值与全角数字解析失败；模型再做语义复核：口径定义、同比环比基期、跨表勾稽、平均数加权、图表是否歪曲。输出**红黄绿清单**（红＝确定性不一致，黄＝可疑待核，绿＝通过）＋三档总评（可以报送/核实后报送/需更正后报送）＋建议更正值（附复核公式，**不回写原表**）。

**什么时候用**：说"帮我核一下这张表""报出去之前把把关""这报表有没有问题"。

**怎么用**：
```bash
python report-check/scripts/check.py 报表.xlsx --out 复核清单.md
```

**规则与边界**：红黄不混淆、拿不准就黄并写明疑点；每条给定位与复核公式；无底表时声明"未做报表数与底表核对"；允许零问题。

**测试**：check.py 11 项机械回归。上游 validate-data（Apache-2.0）。

### hr-statistics（人力资源统计｜S09）

**做什么**：从人员台账生成结构统计与月报季报——部门人数、编制实有对比、学历/年龄/职称结构、管理幅度、未来 N 年退休预测（男/女法定年龄可配）。报告固定结构：领导摘要（2-3 条带数字）→ 关键指标表（含趋势）→ 分项分析 → 异常提示 → 口径与方法。**口径先行**：台账范围（在编/聘用）、基准日、算法全部写进报告，每个数字可用命令复现。

**什么时候用**：说"出个人事月报""统计一下人员结构""各部门多少人""退休预测"。

**怎么用**：
```bash
python hr-statistics/scripts/stats.py count-by 台账.xlsx --col 部门
python hr-statistics/scripts/stats.py pivot 台账.xlsx --rows 部门 --cols 学历
python hr-statistics/scripts/stats.py ages 台账.xlsx --col 出生日期 --asof 2026-09-13
python hr-statistics/scripts/stats.py retire 台账.xlsx --col 出生日期 --gender 性别 --years 5
```

**规则与边界（硬）**：**不排名、不评价、不决策**——不做人员优劣排名，不给任免调岗建议；报告只有汇总数，个人明细不进报告不落盘；与上期口径变了必须声明。

**测试**：stats.py 7 项机械回归。上游 people-report（Apache-2.0），国外指标已替换为单位口径。

---

## 会议与流程线

### meeting-brief（会前材料｜S10）

**做什么**：会前五分钟的简报。核心产出是**一页会前卡片**（固定栏目：这个会要解决什么、必须知道的 3 件事、上次会定了什么/遗留什么、本次要决策什么＋选项和建议倾向、可能的质疑与回应、要带的材料、**准备缺口**），重要会议另附详细背景材料（参会人关注点、事项脉络、未决事项、发言要点）。按会议类型定准备重点：决策会、专题协调会、汇报调度会、外部会谈、全体会议各有清单。

**什么时候用**：说"下周有个会帮我准备一下""出个会前简报""这个会我要讲什么"。

**规则与边界**：重要事实标注来源；推断内容（对方立场）标注"推断"；**查不到的历史结论和数据如实写"未查到"进准备缺口，不编造**——缺口本身也是准备成果。

**上游与许可**：meeting-briefing（Apache-2.0）去法律领域化本地化。纯规则技能。

### meeting-minutes（会议纪要督办｜S11）

**做什么**：从录音转写或笔记生成三件套——**纪要草稿**（机关纪要结构：要素/议题讨论要点/决议/行动项）、**领导速览**（半页：定了什么、谁在何时交什么）、**督办台账 CSV**（固定九列，可跟踪）。核心纪律：区分决议、行动项、讨论记录三类；行动项四要素（具体事项、唯一责任人、明确日期、依赖）缺一就标"**待确认**"，**绝不编造**——脚本不生成默认责任人和日期，模糊表述（"这事抓紧办"）保留原话进备注。台账可反复检查：缺字段、日期非法、**逾期未办结**逐条列出。

**什么时候用**：说"整理一下会议纪要""把转写整成纪要""提取一下会议决议""生成督办台账""查查哪些逾期了"。

**怎么用**：
```bash
python meeting-minutes/scripts/actions.py build --from 行动项.json --out 督办台账.csv --meeting "××办公会" --date 2026-09-10
python meeting-minutes/scripts/actions.py check 督办台账.csv --asof 2026-09-13
```

**测试**：actions.py 8 项机械回归。上游 meeting-briefing 的 action tracking 范式（Apache-2.0）。

### sop-capture（SOP 流程沉淀｜S12）

**做什么**：把"存在某个人脑子里"的办事流程沉淀为标准 SOP——目的、适用范围、**RACI 责任矩阵**、文本流程图、详细步骤（每步：谁、何时触发、怎么操作、产出什么）、**例外与边界场景表**、所需表单与系统清单、关联制度、版本信息。访谈式补齐：口述想到哪说到哪，技能按九节问题清单找缺口（分支判断、例外场景、表单系统、完成标志），一次问不超过 3 个。

**什么时候用**：说"把这个流程整理成SOP""老师傅快退休了把经验固化下来""新来的要接手这个活"。

**规则与边界**：口述里没有的环节标〔待确认〕不脑补；"制度归综合科、实际小王在干"如实双标注并提示理顺；SOP 写岗位不写人名（人走流程不走）；三关自检——新人能否只靠 SOP 走全程、例外覆盖够不够、每步是否唯一 A（签字负责者）——未过自检保持"草稿版"，闭环后才升 v1.0。

**上游与许可**：process-doc（Apache-2.0），保留其 SOP 骨架与"从口述开始、例外最有价值"的经验。纯规则技能，含 SOP 骨架模板。

---

## 目录结构

```text
skills/
├── chinese-proofread/   # 中文文字校对（含 INSTALL.md，独立演进）
├── chinese-briefing/    # S02 工作简报
├── chinese-drafting/    # S01 材料起草
├── chinese-review/      # S03 材料审稿
├── policy-qa/           # S04 制度政策问答
├── policy-diff/         # S05 制度新旧对比
├── ledger-checkup/      # S08 台账数据体检
├── excel-analysis/      # S06 Excel 数据分析
├── report-check/        # S07 报表智能复核
├── hr-statistics/       # S09 人力资源统计
├── meeting-brief/       # S10 会前材料
├── meeting-minutes/     # S11 会议纪要督办
├── sop-capture/         # S12 SOP 流程沉淀
├── chinese-proofread.zip
├── 来源项目总览/         # 上游参考项目（agentskills、anthropics/skills 等）
├── 建设清单与二开建议_V1.0.docx
├── LICENSE
└── README.md
```

每个技能文件夹内的标准组成：

```text
<skill>/
├── SKILL.md          # 触发条件、边界、主流程（宿主加载的入口）
├── README.md         # 资产卡：Owner、版本、触发条件、输入输出、数据权限、许可证、上游修改说明
├── CHANGELOG.md      # 每次规则/脚本变化可追溯
├── references/       # 渐进加载的规则、检查清单、格式规范（起草哪类只读哪份）
├── scripts/          # 确定性脚本（Python 3.8+ 标准库，UTF-8/GBK 兼容）
├── tests/            # 脚本机械回归（unittest）
├── evals/evals.json  # 起步测评用例（真实内网模型上试跑迭代）
└── LICENSE.txt       # Apache-2.0 上游技能携带；自研技能随仓库 MIT
```

## 使用方式

把所需技能的整个文件夹放入宿主的 skills 目录，确保 `SKILL.md` 直接位于该文件夹下，刷新技能列表即可。日常直接说需求（"写个周报""核一下这张表"）会自动触发对应技能；各技能的依赖和典型用法见上文小节及各自 README。

技能间按流水线协作，不必手动串：材料线从简报或起草进入，审稿后交校对；数据线先体检再分析复核，最后汇成人事报告；会议线从会前准备到纪要督办，流程成熟后沉淀为 SOP。制度问答与新旧对比随时独立使用。

## 测试与评测

带脚本的技能均有机械回归，全部通过（合计 92 项）：

```bash
python -m unittest discover -s chinese-drafting/tests -v    # 20 项
python -m unittest discover -s policy-qa/tests -v           #  9 项
python -m unittest discover -s policy-diff/tests -v         # 13 项
python -m unittest discover -s excel-analysis/tests -v      # 10 项
python -m unittest discover -s report-check/tests -v        # 11 项
python -m unittest discover -s ledger-checkup/tests -v      # 14 项
python -m unittest discover -s hr-statistics/tests -v       #  7 项
python -m unittest discover -s meeting-minutes/tests -v     #  8 项
```

机械测试验证脚本与流程行为，不代表实际模型的语言/分析质量；各技能 `evals/evals.json` 的起步用例（每技能 3 条）应在真实内网模型上试跑，与用户复盘后迭代规则。中文校对的专门测评见 [chinese-proofread/references/evaluation.md](chinese-proofread/references/evaluation.md)。

## 治理要点

- **数据权限**：人员身份、薪酬、考核等按敏感处理，仅本地处理；报告只出汇总数。
- **只读红线**：数据类技能一律不回写原文件；清洗副本、修订稿均新建文件且需用户明示。
- **不编造**：起草的待补占位、问答的无依据拒答、纪要的待确认责任人、简报的数据待补——同一原则在不同场景的落地。
- **许可证**：仓库自研内容 MIT；本地化技能保留上游 Apache-2.0（随目录 LICENSE.txt），修改说明见各自 README。
- **版本与回滚**：规则/脚本变化记录在各自 CHANGELOG；技能升级前先跑机械回归。

## License

仓库自研内容采用 [MIT](LICENSE)。本地化技能与上游参考资料保留各自许可证和来源说明，以对应目录为准。
