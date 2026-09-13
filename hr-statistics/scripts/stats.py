#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""人员台账统计：分组计数、交叉表、年龄段结构、退休预测——全部只读汇总。

用法：
  python stats.py count-by <文件> --col 部门
  python stats.py pivot <文件> --rows 部门 --cols 学历
  python stats.py ages <文件> --col 出生日期 [--brackets 30,40,50] [--asof 2026-09-13]
  python stats.py retire <文件> --col 出生日期 --gender 性别 [--male-age 60] [--female-age 55]
                          [--years 5] [--asof ...]
  公共参数：--sheet 名称 --header 行号

说明：
- 仅用 Python 3.8+ 标准库；xlsx/csv 只读；
- 日期支持 2025-01-01 / 2025/1/1 / 2025.1.1 / 20250101 / 2025年1月1日；
- 输出为汇总表，不含个人明细行；口径解释由 Agent 结合 references/metrics.md 完成。
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

DATE_PATTERNS = [
    (re.compile(r"^\d{4}-\d{1,2}-\d{1,2}$"), "%Y-%m-%d"),
    (re.compile(r"^\d{4}/\d{1,2}/\d{1,2}$"), "%Y/%m/%d"),
    (re.compile(r"^\d{4}\.\d{1,2}\.\d{1,2}$"), "%Y.%m.%d"),
    (re.compile(r"^\d{8}$"), "%Y%m%d"),
    (re.compile(r"^\d{4}年\d{1,2}月\d{1,2}日$"), "%Y年%m月%d日"),
]


def col_index(letters):
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n


def load_rows(path, sheet=None):
    if not os.path.isfile(path):
        raise SystemExit("stats.py: 文件不存在：%s" % path)
    if path.lower().endswith((".xlsx", ".xlsm")):
        return read_xlsx(path, sheet)
    if path.lower().endswith(".csv"):
        with open(path, "rb") as f:
            data = f.read()
        for enc in ("utf-8-sig", "utf-8", "gbk"):
            try:
                text = data.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise SystemExit("stats.py: 无法识别编码：%s" % path)
        return [r for r in csv.reader(text.splitlines()) if any(c.strip() for c in r)]
    raise SystemExit("stats.py: 暂只支持 xlsx/csv：%s" % path)


def read_xlsx(path, sheet=None):
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    rel_ns = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            sroot = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in sroot.findall(ns + "si"):
                shared.append("".join(t.text or "" for t in si.iter(ns + "t")))
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = {r.get("Id"): r.get("Target")
                for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
        sheets = [(s.get("name"), rels.get(s.get(rel_ns, ""))) for s in wb.iter(ns + "sheet")]
        target = None
        if sheet:
            for i, (name, rel) in enumerate(sheets, start=1):
                if name == sheet or (sheet.isdigit() and i == int(sheet)):
                    target = rel
            if not target:
                raise SystemExit("stats.py: 找不到工作表 %r" % sheet)
        else:
            target = sheets[0][1]
        if not target:
            raise SystemExit("stats.py: 工作表关系缺失")
        target = target if target.startswith("xl/") else "xl/" + target.lstrip("/")
        root = ET.fromstring(z.read(target))
        rows = []
        for row in root.iter(ns + "row"):
            cells = {}
            for c in row.iter(ns + "c"):
                ref = c.get("r", "")
                m = re.match(r"[A-Z]+", ref)
                col = col_index(m.group(0)) if m else len(cells) + 1
                t, v, is_el = c.get("t"), c.find(ns + "v"), c.find(ns + "is")
                if t == "s" and v is not None:
                    val = shared[int(v.text)]
                elif t == "inlineStr" and is_el is not None:
                    val = "".join(x.text or "" for x in is_el.iter(ns + "t"))
                else:
                    val = v.text if (v is not None and v.text is not None) else ""
                cells[col] = val
            width = max(cells) if cells else 0
            rows.append([cells.get(i, "") for i in range(1, width + 1)])
        return [r for r in rows if any(str(c).strip() for c in r)]


def table(headers, rows):
    head = "| " + " | ".join(headers) + " |"
    sep = "|" + "---|" * len(headers)
    body = ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join([head, sep] + body)


class Dataset:
    def __init__(self, args):
        rows = load_rows(args.file, getattr(args, "sheet", None))
        if args.header >= len(rows):
            raise SystemExit("stats.py: --header 超出范围（共 %d 行）" % len(rows))
        self.headers = [str(h).strip() for h in rows[args.header]]
        self.rows = rows[args.header + 1:]

    def index(self, name):
        for i, h in enumerate(self.headers):
            if h == name:
                return i
        for i, h in enumerate(self.headers):
            if name in h:
                return i
        raise SystemExit("stats.py: 找不到列 %r；现有列：%s" % (name, self.headers))

    def value(self, r, idx):
        return str(r[idx]).strip() if idx < len(r) else ""

    def dates(self, col):
        idx = self.index(col)
        out = []
        bad = 0
        for r in self.rows:
            v = self.value(r, idx)
            d = None
            for pattern, fmt in DATE_PATTERNS:
                if pattern.match(v):
                    try:
                        d = datetime.datetime.strptime(v, fmt).date()
                        break
                    except ValueError:
                        continue
            if d is None:
                if v:
                    bad += 1
                out.append(None)
            else:
                out.append(d)
        return out, bad


def cmd_count_by(args):
    ds = Dataset(args)
    idx = ds.index(args.col)
    counter = {}
    for r in ds.rows:
        v = ds.value(r, idx) or "（空）"
        counter[v] = counter.get(v, 0) + 1
    total = sum(counter.values())
    items = sorted(counter.items(), key=lambda kv: -kv[1])
    body = [[k, v, "%.1f%%" % (v * 100.0 / total)] for k, v in items]
    body.append(["合计", total, "100%"])
    print(table([args.col, "人数", "占比"], body))
    print("（%d 行数据按「%s」分组；空值单列为（空））" % (total, args.col))
    return 0


def cmd_pivot(args):
    ds = Dataset(args)
    ri, ci = ds.index(args.rows), ds.index(args.cols)
    matrix, row_keys, col_keys = {}, [], []
    for r in ds.rows:
        rv, cv = ds.value(r, ri) or "（空）", ds.value(r, ci) or "（空）"
        if rv not in matrix:
            matrix[rv] = {}
            row_keys.append(rv)
        if cv not in col_keys:
            col_keys.append(cv)
        matrix[rv][cv] = matrix[rv].get(cv, 0) + 1
    body = []
    for rk in row_keys:
        row = [rk] + [matrix[rk].get(ck, 0) for ck in col_keys] + [sum(matrix[rk].values())]
        body.append(row)
    body.append(["合计"] + [sum(matrix[rk].get(ck, 0) for rk in row_keys) for ck in col_keys]
                + [sum(matrix[rk].get(ck, 0) for rk in row_keys for ck in col_keys)])
    print(table([args.rows] + col_keys + ["合计"], body))
    print("（交叉表 %d 行 × %d 列；单元格为记录数）" % (len(row_keys), len(col_keys)))
    return 0


def cmd_ages(args):
    ds = Dataset(args)
    dates, bad = ds.dates(args.col)
    asof = datetime.date.fromisoformat(args.asof) if args.asof else datetime.date.today()
    brackets = [int(x) for x in args.brackets.split(",")]
    labels = ["%d岁及以下" % brackets[0]]
    for lo, hi in zip(brackets, brackets[1:]):
        labels.append("%d-%d岁" % (lo + 1, hi))
    labels.append("%d岁以上" % brackets[-1])
    counts = dict.fromkeys(labels, 0)
    unknown = 0
    for d in dates:
        if d is None:
            unknown += 1
            continue
        age = asof.year - d.year - ((asof.month, asof.day) < (d.month, d.day))
        if age <= brackets[0]:
            counts[labels[0]] += 1
        elif age > brackets[-1]:
            counts[labels[-1]] += 1
        else:
            for lo, hi in zip(brackets, brackets[1:]):
                if lo < age <= hi:
                    counts["%d-%d岁" % (lo + 1, hi)] += 1
                    break
    total = len(dates) - unknown
    body = [[k, v, "%(p).1f%%" % {"p": v * 100.0 / total if total else 0}] for k, v in counts.items()]
    body.append(["合计", total, "100%"])
    if unknown:
        body.append(["（无法解析出生日期）", unknown, "-"])
    body.append(["平均年龄", round(sum(
        (asof.year - d.year - ((asof.month, asof.day) < (d.month, d.day)))
        for d in dates if d) / total, 1) if total else "-", "-"])
    print(table(["年龄段", "人数", "占比"], body))
    print("（基准日 %s；%s「%s」列无法解析 %d 条）" % (asof.isoformat(), "注意：" if bad else "", args.col, unknown))
    return 0


def cmd_retire(args):
    ds = Dataset(args)
    dates, bad = ds.dates(args.col)
    gi = ds.index(args.gender)
    asof = datetime.date.fromisoformat(args.asof) if args.asof else datetime.date.today()
    end_year = asof.year + args.years
    rows_out = []
    for r, d in zip(ds.rows, dates):
        if d is None:
            continue
        g = ds.value(r, gi)
        limit = args.male_age if g == "男" else args.female_age if g == "女" else None
        if limit is None:
            continue
        retire_date = datetime.date(d.year + limit, d.month, d.day)
        if asof.year <= retire_date.year <= end_year or retire_date < asof:
            rows_out.append((retire_date.year, g, retire_date))
    by_year = {}
    already = 0
    for year, g, d in rows_out:
        if d < asof:
            already += 1
        by_year[year] = by_year.get(year, 0) + 1
    body = [[y, by_year[y]] for y in sorted(by_year) if by_year[y] > 0 and y >= asof.year]
    body.append(["合计（%d年内应到龄）" % args.years, sum(c for _, c in body)])
    if already:
        body.append(["（已超龄未注销，需人工核实）", already])
    print(table(["年份", "预计到龄人数"], body))
    print("（口径：男%d岁/女%d岁，按出生日期推算，含按月到龄；不含提前退、延退等政策差异；基准日 %s）"
          % (args.male_age, args.female_age, asof.isoformat()))
    return 0


def main(argv=None):
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    parser = argparse.ArgumentParser(prog="stats.py", description="人员台账统计（只读汇总）")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("file")
        p.add_argument("--sheet")
        p.add_argument("--header", type=int, default=0)

    p1 = sub.add_parser("count-by", help="单列分组计数")
    common(p1)
    p1.add_argument("--col", required=True)
    p1.set_defaults(func=cmd_count_by)

    p2 = sub.add_parser("pivot", help="两列交叉表")
    common(p2)
    p2.add_argument("--rows", required=True)
    p2.add_argument("--cols", required=True)
    p2.set_defaults(func=cmd_pivot)

    p3 = sub.add_parser("ages", help="年龄段结构")
    common(p3)
    p3.add_argument("--col", default="出生日期")
    p3.add_argument("--brackets", default="30,40,50")
    p3.add_argument("--asof")
    p3.set_defaults(func=cmd_ages)

    p4 = sub.add_parser("retire", help="退休预测")
    common(p4)
    p4.add_argument("--col", default="出生日期")
    p4.add_argument("--gender", default="性别")
    p4.add_argument("--male-age", type=int, default=60)
    p4.add_argument("--female-age", type=int, default=55)
    p4.add_argument("--years", type=int, default=5)
    p4.add_argument("--asof")
    p4.set_defaults(func=cmd_retire)

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
