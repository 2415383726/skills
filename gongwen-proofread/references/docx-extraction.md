# DOCX 有限范围提取

使用 Python 3.8+ 标准库，在内网本地运行，无依赖安装、宏执行、模型调用或外链访问：

```sh
python3 scripts/extract_docx.py --input /任务目录/材料.docx --output /任务目录/document.json
```

可选 `--title`、`--max-unit-chars 1800`、`--overwrite`。输出必须位于技能包外，不能覆盖输入及其符号链接或硬链接，默认拒绝覆盖已有输出。不会改写源 DOCX。提取前 snapshot，读取字节哈希核对，完成后 bind；后续沿用 `provenance.py verify` 检查来源变化。来源哈希只证明版本关联，不证明提取完整或语言判断正确。

## 实际范围

- 读取标准 `word/document.xml` 的正文段落及表格单元格文字，跨 run 拼接，保留空格、制表符、换行、软连字符、不换行连字符。`w:ptab` 定位制表符映射为 `\t`，不还原视觉对齐。`w:ruby` 只保留 `rubyBase` 正文，`rt` 注音清点但不提取、不检查。空白段落不编号，超长段落复用无损分片函数。
- 表格展平为带表、行、格坐标的 paragraph；嵌套表格深度优先，父单元格段落与嵌套表各取一次。坐标来自物理 XML；合并格、视觉排版、浮动表格和分页不还原。
- 默认**文字级最终修订视图**：包含 `ins`、`moveTo`，排除 `del`、`moveFrom`。不是 Word 接受全部修订的模拟器；表格结构、格式修订不还原。隐藏文字未按样式过滤，可能进入正文。
- `Heading*`、`标题*` 直接段落样式标识以及直接 `outlineLvl=0..8` 可识别为 heading；不解析样式继承，因此其他标题仍作为普通段落保留。
- 支持常见 Transitional/Strict WordprocessingML namespace；要求标准正文部件位置及 DOCX main 内容类型，不支持所有 OPC 部件布局或完整 Office 兼容。

## 明确未检查的结构

文本框、脚注/尾注、页眉/页脚、批注、绘图/图片、嵌入对象、数学公式、字体映射符号、注音（ruby 的 rt）、`altChunk`、`AlternateContent` 兼容分支均不抽取；字段不计算、不更新，正文中的缓存结果可能保留。修订中的注释和对象也可能被清点。外部关系只读声明，不追踪目标；二进制对象不打开。

`extraction_inventory` 记录每类结构的 `count`、实际 XML `parts` 和 `handling`，`extraction_xml_parts` 列出真正成功读取解析的 XML 部件。脚注等类别的定义和引用分别计数，不能将次数理解为可见对象数。XML 部件包括包内未引用部件，清点不单凭文件名推断覆盖。零次不代表不存在未知扩展结构；不能据此宣称整份文档已校对。`scope` 和 `limitations` 同时带入后续报告，非正文结构不会计入已检查单元。

## 输入与安全边界

拒绝非 `.docx`、旧 DOC/疑似加密复合文档、加密 ZIP、错误 ZIP、重复部件、无正文或无可检查文字。所有 XML/relationships 文件实际读取后解析；禁止 DTD/实体声明（包括 UTF-16 编码声明），不解析外部实体、不解压到磁盘、不执行任何文档代码。读入上限为包 128 MiB、XML 解压总量 64 MiB、部件 10000 个；超出即报错，不产生部分覆盖成功结果。损坏或不支持的 XML/ZIP 返回错误，CLI 非零退出。

这些上限用于控制常见资源消耗，不是完整恶意 Office 文件沙箱。

## 验证

统一入口的标准 DOCX 识别和宿主回退由 tests/test_extraction.py 验证。测试验证工程行为，不评价中文校对准确率。日常调用优先使用 extract_file.py；本适配器仍可单独使用。
