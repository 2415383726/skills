#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""台账/报表读取与聚合：把 Excel/CSV 变成模型可复核的数字。

用法：
  python table.py profile <文件> [--sheet 名称|序号] [--header 行号]
  python table.py preview <文件> [--rows 10] [--sheet ...]
  python table.py groupby <文件> --by 列名 [--agg sum:列 --agg count] [--sheet ...] [--header 行号]

说明：
- 仅用 Python 3.8+ 标准库；xlsx 解包读取，csv 直读（utf-8-sig/utf-8/gbk）；
- --header 指定表头所在行（从 0 计），适配合并表头/标题行在前的工作表；
- 日期列按表头名（日期/时间/月份）识别，xlsx 序列号转日期（1900 日期系统）；
- 本脚本只做读取、类型推断和聚合，不做分析结论；口径与判断由 Agent 完成。
"""

import argparse
import csv
import datetime
import json
import os
import re
import sys
import zipfile

import xml.etree.ElementTree as ET

XLDATE_EPOCH = datetime.date(1899, 12, 30)
DATE_HEADER_RE = re.compile(r"日期|时间|月份|年份|date", re.I)
NUM_RE = re.compile(r"^-?\d{1,3}(,\d{3})+(\.\d+)?$|^-?\d+(\.\d+)?$|^-?\d+(\.\d+)?%$")


def read_csv_rows(path):
    with open(path, "rb") as f:
        data = f.read()
    text = None
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise SystemExit("table.py: 无法识别编码（已尝试 UTF-8/GBK）：%s" % path)
    return [row for row in csv.reader(text.splitlines()) if any(c.strip() for c in row)]


def read_xlsx_rows(path, sheet=None):
    with zipfile.ZipFile(path) as z:
        ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            sroot = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in sroot.findall(ns + "si"):
                shared.append("".join(t.text or "" for t in si.iter(ns + "t")))
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = {}
        rels_root = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        for rel in rels_root:
            rels[rel.get("Id")] = rel.get("Target")
        sheets = [(s.get("name"), rels.get(s.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id", ""))) for s in wb.iter(ns + "sheet")]
        target = None
        if sheet:
            for name, rel in sheets:
                if name == sheet or (sheet.isdigit() and sheets[int(sheet) - 1][0] == name):
                    target = rel
                    break
            if target is None:
                raise SystemExit("table.py: 找不到工作表 %r；现有：%s" % (sheet, [n for n, _ in sheets]))
        else:
            target = sheets[0][1]
        if not target:
            raise SystemExit("table.py: 工作表关系缺失")
        if not target.startswith("xl/"):
            target = "xl/" + target.lstrip("/")
        root = ET.fromstring(z.read(target))
        rows = []
        for row in root.iter(ns + "row"):
            cells = {}
            for c in row.iter(ns + "c"):
                ref = c.get("r", "")
                col = column_index(re.match(r"[A-Z]+", ref).group(0)) if ref else len(cells) + 1
                t = c.get("t")
                v = c.find(ns + "v")
                is_el = c.find(ns + "is")
                if t == "s" and v is not None:
                    val = shared[int(v.text)]
                elif t == "inlineStr" and is_el is not None:
                    val = "".join(x.text or "" for x in is_el.iter(ns + "t"))
                elif v is not None and v.text is not None:
                    val = v.text
                else:
                    val = ""
                cells[col] = val
            width = max(cells) if cells else 0
            rows.append([cells.get(i, "") for i in range(1, width + 1)])
        return [r for r in rows if any(str(c).strip() for c in r)]


def column_index(letters):
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n


def load_rows(path, sheet=None):
    if not os.path.isfile(path):
        raise SystemExit("table.py: 文件不存在：%s" % path)
    if path.lower().endswith((".xlsx", ".xlsm")):
        return read_xlsx_rows(path, sheet)
    if path.lower().endswith(".csv"):
        if sheet:
            print("提示：csv 无工作表概念，忽略 --sheet。")
        return read_csv_rows(path)
    raise SystemExit("table.py: 暂只支持 xlsx/csv，收到：%s" % path)


def to_number(text):
    s = str(text).strip()
    if not s or not NUM_RE.match(s):
        return None
    percent = s.endswith("%")
    s = s.replace(",", "").replace("%", "")
    try:
        n = float(s)
    except ValueError:
        return None
    return n / 100 if percent else n


def maybe_xldate(text):
    """表头像日期列且值为纯数字时，按 1900 系统序列号转日期。"""
    try:
        serial = int(float(text))
    except (TypeError, ValueError):
        return None
    if not (20000 <= serial <= 60000):
        return None
    return (XLDATE_EPOCH + datetime.timedelta(days=serial)).isoformat()


def header_index(rows, header):
    if header is None:
        return 0
    if header >= len(rows):
        raise SystemExit("table.py: --header 行号 %d 超出范围（共 %d 行）" % (header, len(rows)))
    return header


def col_map(header_row):
    return {str(v).strip(): i for i, v in enumerate(header_row) if str(v).strip()}


def resolve(name, mapping):
    if name in mapping:
        return mapping[name]
    compact = {k.replace(" ", "").replace("\u3000", ""): v for k, v in mapping.items()}
    if name.replace(" ", "") in compact:
        return compact[name.replace(" ", "")]
    raise SystemExit("table.py: 找不到列 %r；现有列：%s" % (name, list(mapping)))


def cmd_profile(args):
    rows = load_rows(args.file, args.sheet)
    hi = header_index(rows, args.header)
    header, data = rows[hi], rows[hi + 1:]
    mapping = col_map(header)
    lines = ["文件：%s（数据 %d 行 × %d 列，表头第 %d 行）" % (args.file, len(data), len(header), hi)]
    for name, idx in mapping.items():
        values = [r[idx] if idx < len(r) else "" for r in data]
        nonempty = [v for v in values if str(v).strip()]
        numbers = [to_number(v) for v in nonempty]
        numbers = [n for n in numbers if n is not None]
        kind = "数值" if numbers and len(numbers) >= len(nonempty) * 0.8 else "文本"
        note = ""
        if kind == "数值" and DATE_HEADER_RE.search(name):
            dates = [maybe_xldate(v) for v in nonempty]
            if any(dates):
                kind, note = "日期", "（序列号已可转日期，如 %s）" % next(d for d in dates if d)
        stat = "空值 %d" % (len(data) - len(nonempty))
        if numbers:
            stat += "，最小 %s，最大 %s，合计 %s" % (fmt(min(numbers)), fmt(max(numbers)), fmt(sum(numbers)))
        distinct = len({str(v).strip() for v in nonempty})
        lines.append("- %s[%s]：%s；不同值 %d%s" % (name, kind, stat, distinct, note))
    print("\n".join(lines))
    return 0


def fmt(n):
    if n == int(n):
        return str(int(n))
    return ("%.4f" % n).rstrip("0").rstrip(".")


def cmd_preview(args):
    rows = load_rows(args.file, args.sheet)
    hi = header_index(rows, args.header)
    shown = rows[hi:hi + args.rows + 1]
    width = max(len(r) for r in shown)
    out = ["| | " + " | ".join("列%d" % (i + 1) for i in range(width)) + " |",
           "| --- " * (width + 1) + "|"]
    for ri, r in enumerate(shown):
        r = r + [""] * (width - len(r))
        tag = "表头" if ri == 0 else str(hi + ri)
        out.append("| %s | %s |" % (tag, " | ".join(str(c) for c in r)))
    print("\n".join(out))
    print("（显示 %d 行，文件共 %d 行；列名以 profile 为准）" % (len(shown), len(rows)))
    return 0


def cmd_groupby(args):
    rows = load_rows(args.file, args.sheet)
    hi = header_index(rows, args.header)
    header, data = rows[hi], rows[hi + 1:]
    mapping = col_map(header)
    by_idx = resolve(args.by, mapping)
    aggs = []
    for spec in (args.agg or ["count"]):
        if ":" in spec:
            op, col = spec.split(":", 1)
            aggs.append((op.lower(), resolve(col, mapping)))
        else:
            aggs.append((spec.lower(), None))
    groups = {}
    for r in data:
        key = str(r[by_idx]).strip() if by_idx < len(r) else ""
        groups.setdefault(key, []).append(r)
    head = ["| %s | " % args.by + " | ".join("%s%s" % (op, ("(" + colname(idx, header) + ")") if idx is not None else "") for op, idx in aggs) + " |"]
    lines = head + ["|" + "---|" * (len(aggs) + 1)]
    for key in sorted(groups):
        grp = groups[key]
        cells = [key]
        for op, idx in aggs:
            if op == "count":
                cells.append(str(len(grp)))
            elif op in ("sum", "avg", "max", "min"):
                nums = [to_number(r[idx]) for r in grp if idx < len(r)]
                nums = [n for n in nums if n is not None]
                if not nums:
                    cells.append("-")
                elif op == "sum":
                    cells.append(fmt(sum(nums)))
                elif op == "avg":
                    cells.append(fmt(sum(nums) / len(nums)))
                elif op == "max":
                    cells.append(fmt(max(nums)))
                else:
                    cells.append(fmt(min(nums)))
            else:
                raise SystemExit("table.py: 不支持的聚合 %r（可用 sum/avg/max/min/count）" % op)
        lines.append("| " + " | ".join(cells) + " |")
    print("\n".join(lines))
    print("（分组 %d 个，数据 %d 行；数值列含百分号或千分位已自动处理）" % (len(groups), len(data)))
    return 0


def colname(idx, header):
    return str(header[idx]) if idx < len(header) else "列%d" % (idx + 1)


def main(argv=None):
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    parser = argparse.ArgumentParser(prog="table.py", description="Excel/CSV 读取与聚合")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("file", help="xlsx/csv 文件")
        p.add_argument("--sheet", help="工作表名或序号（xlsx）")
        p.add_argument("--header", type=int, default=None, help="表头所在行（从0计，默认第0行）")

    p1 = sub.add_parser("profile", help="列级画像：类型、空值、范围、不同值")
    common(p1)
    p1.set_defaults(func=cmd_profile)

    p2 = sub.add_parser("preview", help="预览前 N 行")
    common(p2)
    p2.add_argument("--rows", type=int, default=10)
    p2.set_defaults(func=cmd_preview)

    p3 = sub.add_parser("groupby", help="分组聚合")
    common(p3)
    p3.add_argument("--by", required=True, help="分组列名")
    p3.add_argument("--agg", action="append", help="聚合：count 或 sum:列名/avg:列名/max/min")
    p3.set_defaults(func=cmd_groupby)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except SystemExit as exc:
        if exc.code and str(exc.code) not in ("0", "None"):
            print(str(exc.code))
            return 2
        raise


if __name__ == "__main__":
    sys.exit(main())
