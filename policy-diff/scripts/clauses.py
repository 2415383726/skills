#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""制度条款拆分与对齐：把新旧两版制度切成条款，按条号对齐并标注变化类型。

用法：
  python clauses.py align <旧版文件> <新版文件> [--out 报告.md] [--json]

支持 md/txt/docx。报告内容：
- 总览统计：旧版条数、新版条数、文字相同、文字有差异、新增、删除、编号调整；
- 逐条对照表：条号对、变化类型、旧文本、新文本（供 Agent 做语义判断）。

职责边界：本脚本只做确定性的拆分、对齐和文本比较；"口径变化/含义变化/影响解读"
等语义判断由 Agent 基于对照表完成。仅用 Python 3.8+ 标准库。
"""

import argparse
import json
import os
import re
import sys
import zipfile

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
CLAUSE_RE = re.compile(r"^第([0-9零一二两三四五六七八九十百千]+)条")
NUMERAL = {
    "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}


def read_text(path):
    """md/txt 直读（utf-8-sig/utf-8/gbk），docx 解包取段落。"""
    if path.lower().endswith(".docx"):
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml")
        import xml.etree.ElementTree as ET

        root = ET.fromstring(xml)
        paras = []
        for p in root.iter(W_NS + "p"):
            paras.append("".join(t.text or "" for t in p.iter(W_NS + "t")))
        return "\n".join(paras)
    with open(path, "rb") as f:
        data = f.read()
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise SystemExit("clauses.py: 无法识别编码（已尝试 UTF-8/GBK）：%s" % path)


def clause_number(marker):
    if marker.isdigit():
        return int(marker)
    return chinese_to_int(marker)


def chinese_to_int(s):
    """中文数字转整数，支持零到九千九百九十九的常见写法；解析失败返回 None。

    规则：数字字符累加进当前小节，单位字符把小节乘位后并入总计。
    例：二十五=25、一百零五=105、一千二百=1200、十三=13。
    """
    if not s:
        return None
    digit = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
             "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    unit = {"十": 10, "百": 100, "千": 1000}
    total, section = 0, 0
    for ch in s:
        if ch in digit:
            section += digit[ch]
        elif ch in unit:
            total += (section or 1) * unit[ch]
            section = 0
        else:
            return None
        if total + section > 9999:
            return None
    return total + section


def parse_clauses(text):
    """切成 [(条号, 条款全文)]；条号无法解析时按出现顺序记录为 None 并跳进前款。"""
    clauses, current_no, buf = [], None, []
    for line in text.splitlines():
        m = CLAUSE_RE.match(line.strip())
        if m:
            if current_no is not None or buf:
                clauses.append((current_no, "\n".join(buf).strip()))
            current_no, buf = clause_number(m.group(1)), [line.strip()]
        elif current_no is not None:
            buf.append(line.rstrip())
    if current_no is not None or buf:
        clauses.append((current_no, "\n".join(buf).strip()))
    return [(n, t) for n, t in clauses if t]


def normalize(text):
    return re.sub(r"\s+", "", text)


def body(text):
    """去掉行首"第X条"标记后的正文，用于文本比较（编号调整不等于内容变化）。"""
    return normalize(CLAUSE_RE.sub("", text.strip(), count=1))


def align(old_clauses, new_clauses):
    """对齐新旧条款，返回记录列表：type ∈ same|modified|added|deleted|renumbered。"""
    old_map, new_map = {}, {}
    for n, t in old_clauses:
        old_map.setdefault(n, []).append(t)
    for n, t in new_clauses:
        new_map.setdefault(n, []).append(t)

    records, used_new = [], set()
    old_unmatched = []
    old_nums = [n for n, _ in old_clauses]
    seen = set()
    for n in old_nums:
        if n in seen:
            continue
        seen.add(n)
        old_text = old_map[n][0]
        if n is not None and n in new_map:
            new_text = new_map[n][0]
            used_new.add(n)
            kind = "same" if body(old_text) == body(new_text) else "modified"
            records.append({"type": kind, "old_no": n, "new_no": n,
                            "old": old_text, "new": new_text})
        else:
            old_unmatched.append((n, old_text))

    new_unmatched = [(n, new_map[n][0]) for n in new_map if n not in used_new]
    # 正文相同但条号不同 → 编号调整
    for i, (on, ot) in enumerate(old_unmatched):
        for j, (nn, nt) in enumerate(new_unmatched):
            if ot is not None and nt is not None and body(ot) == body(nt):
                records.append({"type": "renumbered", "old_no": on, "new_no": nn,
                                "old": ot, "new": nt})
                new_unmatched[j] = (None, None)
                old_unmatched[i] = (None, None)
                break
    for on, ot in old_unmatched:
        if on is not None or ot:
            records.append({"type": "deleted", "old_no": on, "new_no": None,
                            "old": ot, "new": ""})
    for nn, nt in new_unmatched:
        if nn is not None or nt:
            records.append({"type": "added", "old_no": None, "new_no": nn,
                            "old": "", "new": nt})
    order = {"modified": 0, "same": 1, "renumbered": 2, "added": 3, "deleted": 4}
    records.sort(key=lambda r: (order[r["type"]],
                                r["new_no"] if r["new_no"] is not None else 9999,
                                r["old_no"] if r["old_no"] is not None else 9999))
    return records


def no_label(n):
    return "第%s条" % n if n is not None else "（无条号）"


def render(records, old_path, new_path):
    stats = {}
    for r in records:
        stats[r["type"]] = stats.get(r["type"], 0) + 1
    lines = ["# 制度条款对齐报告", "",
             "旧版：%s　新版：%s" % (old_path, new_path), ""]
    lines.append("| 文字相同 | 有文字差异 | 新增 | 删除 | 编号调整 |")
    lines.append("| --- | --- | --- | --- | --- |")
    lines.append("| %d | %d | %d | %d | %d |" % (
        stats.get("same", 0), stats.get("modified", 0), stats.get("added", 0),
        stats.get("deleted", 0), stats.get("renumbered", 0)))
    lines += ["", "逐条对照（语义判断由 Agent 继续）：", ""]
    for r in records:
        title = {"same": "文字相同", "modified": "文字有差异", "added": "新增",
                 "deleted": "删除", "renumbered": "编号调整"}[r["type"]]
        if r["type"] == "renumbered":
            head = "%s → %s（编号调整，文字相同）" % (no_label(r["old_no"]), no_label(r["new_no"]))
            lines.append("## %s" % head)
        elif r["type"] == "added":
            lines.append("## %s（新增）" % no_label(r["new_no"]))
            lines += ["", r["new"]]
            continue
        elif r["type"] == "deleted":
            lines.append("## %s（删除）" % no_label(r["old_no"]))
            lines += ["", r["old"]]
            continue
        else:
            lines.append("## %s（%s）" % (no_label(r["new_no"] if r["type"] == "modified" else r["old_no"]), title))
            lines += ["", "**旧版**：", "", r["old"], "", "**新版**：", "", r["new"]]
            continue
        lines += ["", r["old"], ""]
    return "\n".join(lines) + "\n"


def main(argv=None):
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    parser = argparse.ArgumentParser(prog="clauses.py", description="制度条款拆分与对齐")
    sub = parser.add_subparsers(dest="command")
    p_align = sub.add_parser("align", help="对齐新旧两版")
    p_align.add_argument("old", help="旧版文件（md/txt/docx）")
    p_align.add_argument("new", help="新版文件（md/txt/docx）")
    p_align.add_argument("--out", help="报告输出路径；省略则打印")
    p_align.add_argument("--json", action="store_true", help="JSON 输出")
    args = parser.parse_args(argv)
    if args.command != "align":
        parser.print_help()
        return 2
    if not (os.path.isfile(args.old) and os.path.isfile(args.new)):
        print("clauses.py: 新旧版文件不存在，请检查路径。")
        return 2
    old_text, new_text = read_text(args.old), read_text(args.new)
    old_clauses, new_clauses = parse_clauses(old_text), parse_clauses(new_text)
    if not old_clauses or not new_clauses:
        which = "旧版" if not old_clauses else "新版"
        print("clauses.py: %s未识别到\"第X条\"条款结构，请确认文件内容或改用整段对照。" % which)
        return 2
    records = align(old_clauses, new_clauses)
    if args.json:
        payload = {"old": args.old, "new": args.new,
                   "old_clauses": len(old_clauses), "new_clauses": len(new_clauses),
                   "records": records}
        out = json.dumps(payload, ensure_ascii=False, indent=2)
    else:
        out = render(records, args.old, args.new)
    if getattr(args, "out", None):
        parent = os.path.dirname(os.path.abspath(args.out))
        os.makedirs(parent, exist_ok=True)
        with open(args.out, "w", encoding="utf-8-sig", newline="\n") as f:
            f.write(out)
        print("对齐报告已写入：%s" % args.out)
    else:
        print(out, end="" if out.endswith("\n") else "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
