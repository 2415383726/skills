# skills

A personal collection of agent skills I build and use daily.

这个仓库用于持续沉淀我在日常工作中搭建和使用的 agent skills。每个 skill 是仓库下的一个独立文件夹，自带 `SKILL.md`、参考文档、脚本和测试，可整体拷入宿主的 skills 目录直接使用。目前收录了第一个技能，后续会继续增加。

## 技能总览

| Skill | 说明 | 状态 |
| --- | --- | --- |
| [gongwen-proofread](gongwen-proofread/) | 中文公文文字校对：错别字、多字漏字、中文标点 | 可用 |
| *更多技能* | 建设中，陆续加入 | 规划 |

## 目录结构

```text
skills/
├── gongwen-proofread/   # 公文文字校对技能
├── LICENSE
└── README.md
```

## 使用方式

将某个 skill 的整个文件夹放入宿主的 skills 目录，确保其 `SKILL.md` 直接位于该文件夹下，然后刷新技能列表即可。以 gongwen-proofread 为例，安装与使用见 [INSTALL.md](gongwen-proofread/INSTALL.md)。

## 当前技能：gongwen-proofread（公文文字校对）

校对中文公文、通知、报告和办公材料中的错别字、多字漏字及中文标点。支持粘贴文字和本地 Word、WPS、Excel、TXT 材料；短文直接回复，长文生成离线 HTML 报告。不默认润色，不核查外部事实。

**特性**

- 双路全文初检 + 候选复核：两个独立子代理完整检查原文，复核子代理逐条判断候选修改，允许零意见，不为凑数改字。
- 广泛的文件支持：DOCX、XLSX、PPTX、TXT/Markdown 直接提取；旧 XLS 与解析失败文件有明确的安装建议与宿主回退路径。
- 按内容决定交付：约 500 字以内的短文在聊天内直接回复；长文生成浅航空蓝、左右对照、可双向定位的离线 HTML 报告，内嵌 CSS/JS，不依赖外网资源。
- 低依赖：核心流程与基础提取仅用 Python 3.8+ 标准库，可选解析库缺失时给出明确回退动作，适配 Windows 7 与麒麟 V10 内网环境。
- 脚本化调度：主 Agent 只按 `tasks.py step` 返回的 dispatch / wait / repair / deliver 动作执行，并发、分批、去重、定位校验与报告渲染全部由脚本托管。

运行该技能的机械回归测试：

```bash
python -m unittest discover -s gongwen-proofread/tests -v
```

## License

[MIT](LICENSE)
