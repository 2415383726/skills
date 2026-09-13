#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""chinese-drafting 确定性脚本：骨架生成、待补占位符扫描与定稿检查。

子命令：
  new <type> [--title 标题] [-o 输出文件]   从 assets/templates 复制骨架并生成初稿文件
  new --list                                列出全部可用材料类型
  scan <稿子.md> [--out 清单.md] [--json]   扫描【待补：…】占位符，生成待补事实清单
  check <稿子.md>                           定稿前检查；退出码 0=可定稿，1=有未落实事项，2=用法或文件错误

说明：
- 仅用 Python 3.8+ 标准库；输出文件写 UTF-8（带 BOM），便于 Windows 记事本直接打开。
- 待补清单的"建议来源"列需要业务判断，由 Agent 按 references/fact-gap.md 人工补全；
  本脚本负责的是"一个不漏"地定位占位符。
"""

import argparse
import json
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "assets", "templates"))

MARKER_RE = re.compile(r"【待补：([^】]*)】")
MARKER_OPEN = "【待补"

# 类别判断按此顺序取第一个命中的关键词；类别只是辅助信息，以"待补内容"文字为准。
CATEGORY_RULES = [
    ("文号", ("文号", "号文", "〔", "文件", "条款", "规定名称", "办法名称")),
    ("人名", ("人名", "姓名", "职务", "联系人", "讲话人", "述职人", "汇报人", "领导", "局长", "主任", "科长")),
    ("部门", ("部门", "单位名称", "科室", "牵头", "主管机关", "主送", "落款", "单位")),
    ("数字", ("数字", "金额", "万元", "元", "人数", "期数", "人次", "件数", "比例", "百分比", "百分点", "电话", "总数", "合计", "序号", "基数值", "目标值")),
    ("时间", ("时间", "日期", "时限", "节点", "截止", "底前", "月底", "年底", "成文", "起止", "季度", "年度")),
]


def read_text(path):
    """按 utf-8-sig / utf-8 / gbk 依次尝试读取，均失败时报错退出。"""
    with open(path, "rb") as f:
        data = f.read()
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise SystemExit("facts.py: 无法识别文件编码（已尝试 UTF-8/GBK）：%s" % path)


def write_text(path, text):
    """写 UTF-8 带 BOM，Windows 记事本可直接打开；自动建立父目录。"""
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="\n") as f:
        f.write(text)


def classify(desc):
    for cat, keywords in CATEGORY_RULES:
        if any(k in desc for k in keywords):
            return cat
    return "其他"


def find_markers(text):
    """返回 [{line, category, text}]；行号从 1 开始。"""
    items = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for m in MARKER_RE.finditer(line):
            desc = m.group(1).strip()
            items.append({"line": lineno, "category": classify(desc), "text": desc})
    return items


def find_warnings(text):
    """定稿前的弱提醒：不参与退出码，仅供人工确认。"""
    warnings = []
    opened = text.count(MARKER_OPEN)
    closed = len(MARKER_RE.findall(text))
    if opened != closed:
        warnings.append("存在 %d 处未闭合的【待补 标记（缺右括号】，按未落实处理）" % (opened - closed))
    for lineno, line in enumerate(text.splitlines(), start=1):
        if "×××" in line or "某某" in line:
            warnings.append("第 %d 行：含 ×××/某某 占写，请确认是否为有意匿名" % lineno)
    return warnings


def find_english_placeholders(text):
    """TODO/TBD 类英文占位按未落实处理；XXX 不在此列（与中文匿名占写易混淆，走 warnings）。"""
    hits = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if re.search(r"\b(TODO|TBD|FIXME)\b", line):
            hits.append(lineno)
    return hits


def list_types():
    if not os.path.isdir(TEMPLATE_DIR):
        raise SystemExit("facts.py: 找不到模板目录 %s" % TEMPLATE_DIR)
    names = sorted(f[:-3] for f in os.listdir(TEMPLATE_DIR) if f.endswith(".md"))
    return names


def cmd_new(args):
    if args.list:
        for name in list_types():
            print(name)
        return 0
    if not args.type:
        raise SystemExit("facts.py: new 需要材料类型，见 `facts.py new --list`")
    src = os.path.join(TEMPLATE_DIR, args.type + ".md")
    if not os.path.isfile(src):
        raise SystemExit("facts.py: 未知材料类型 %r，可用类型见 `facts.py new --list`" % args.type)
    text = read_text(src)
    if args.title:
        # 只替换第一个一级标题；备用结构（如讲话全稿）保持不动，由起草时处理。
        text = re.sub(r"^# .*$", "# " + args.title, text, count=1, flags=re.M)
        text = text.replace("{{TITLE}}", args.title)
    out = args.out or ("%s-draft.md" % args.type)
    write_text(out, text)
    pending = len(MARKER_RE.findall(text))
    print("已生成骨架：%s（类型 %s，含 %d 个待补槽位）" % (out, args.type, pending))
    print("起草完成后运行：python %s scan %s --out 待补事实清单.md" % (os.path.basename(__file__), out))
    return 0


def render_markdown(items, source, warnings):
    lines = ["# 待补事实清单", ""]
    lines.append("来源：%s　|　共 %d 处" % (source, len(items)))
    lines.append("")
    lines.append("| # | 行号 | 类别 | 待补内容 |")
    lines.append("| --- | --- | --- | --- |")
    for i, it in enumerate(items, start=1):
        lines.append("| %d | %d | %s | %s |" % (i, it["line"], it["category"], it["text"]))
    lines.append("")
    lines.append("「建议来源」列需按 references/fact-gap.md 人工补全（业务台账、上级文件、用户本人等）。")
    for w in warnings:
        lines.append("")
        lines.append("提醒：%s" % w)
    return "\n".join(lines) + "\n"


def cmd_scan(args):
    if not os.path.isfile(args.path):
        raise SystemExit("facts.py: 找不到文件 %s" % args.path)
    text = read_text(args.path)
    items = find_markers(text)
    warnings = find_warnings(text)
    if args.json:
        payload = {"source": args.path, "items": items, "warnings": warnings}
        out = json.dumps(payload, ensure_ascii=False, indent=2)
    else:
        out = render_markdown(items, args.path, warnings)
    if args.out:
        write_text(args.out, out)
        print("待补事实清单已写入：%s（共 %d 处）" % (args.out, len(items)))
    else:
        print(out, end="" if out.endswith("\n") else "\n")
    return 0


def cmd_check(args):
    if not os.path.isfile(args.path):
        raise SystemExit("facts.py: 找不到文件 %s" % args.path)
    text = read_text(args.path)
    items = find_markers(text)
    english = find_english_placeholders(text)
    warnings = find_warnings(text)
    if not items and not english:
        print("未发现未落实事项，可申请定稿。")
        for w in warnings:
            print("提醒：%s" % w)
        return 0
    print("尚有未落实事项，不能定稿：")
    for i, it in enumerate(items, start=1):
        print("  %d. 第 %d 行 [%s] %s" % (i, it["line"], it["category"], it["text"]))
    for lineno in english:
        print("  - 第 %d 行含 TODO/TBD/FIXME 占位" % lineno)
    for w in warnings:
        print("提醒：%s" % w)
    return 1


def main(argv=None):
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass  # Python < 3.7 或输出流不支持时保持默认
    parser = argparse.ArgumentParser(prog="facts.py", description="材料起草：骨架生成与待补事项扫描")
    sub = parser.add_subparsers(dest="command")

    p_new = sub.add_parser("new", help="按类型生成骨架初稿")
    p_new.add_argument("type", nargs="?", help="材料类型，如 work-summary")
    p_new.add_argument("--title", help="替换首个一级标题")
    p_new.add_argument("-o", "--out", help="输出文件，默认 <type>-draft.md")
    p_new.add_argument("--list", action="store_true", help="列出可用类型")
    p_new.set_defaults(func=cmd_new)

    p_scan = sub.add_parser("scan", help="扫描【待补】占位符并生成清单")
    p_scan.add_argument("path", help="稿子文件路径")
    p_scan.add_argument("--out", help="清单输出路径；省略则打印")
    p_scan.add_argument("--json", action="store_true", help="以 JSON 输出")
    p_scan.set_defaults(func=cmd_scan)

    p_check = sub.add_parser("check", help="定稿前检查未落实事项")
    p_check.add_argument("path", help="稿子文件路径")
    p_check.set_defaults(func=cmd_check)

    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
