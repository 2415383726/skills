#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""报表数值机械复核：对 Excel/CSV 做合计校验、可疑值与跳变检查，输出红黄绿清单。

用法：
  python check.py <文件> [--sheet 名称|序号] [--header 行号] [--out 报告.md] [--json]

检查项（确定性规则，语义判断由 Agent 继续）：
- 合计行校验：首列含"合计/总计/小计"的行，逐列核对是否等于上一合计行之后各数据行之和（红）；
- 负值检查：列名含 人数/件数/数量/金额 的列出现负数（红）；
- 可疑比率：列名含 率/比例/占比 的列出现 0%、100% 或口径疑似不一致（黄）；
- 跳变检查：数值列中某值超过列内中位数 3 倍（黄）；
- 空值与解析失败：数值列的空单元格、形似数值但无法解析的值（黄）。

红线：本脚本只读不写，不修改原文件，不自动改数。
"""

import argparse
import csv
import json
import os
import re
import sys
import zipfile
from statistics import median

import xml.etree.ElementTree as ET

NUM_RE = re.compile(r"^-?\d+(\.\d+)?$", re.ASCII)
SUBTOTAL_RE = re.compile("合计|总计|小计")
COUNT_COL_RE = re.compile("人数|件数|个数|数量|金额|户数")
RATE_COL_RE = re.compile("率|比例|占比|百分比")
JUMP_RATIO = 3.0


def col_index(letters):
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n


def load_rows(path, sheet=None):
    if not os.path.isfile(path):
        raise SystemExit("check.py: 文件不存在：%s" % path)
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
            raise SystemExit("check.py: 无法识别编码：%s" % path)
        return [r for r in csv.reader(text.splitlines()) if any(c.strip() for c in r)]
    raise SystemExit("check.py: 暂只支持 xlsx/csv：%s" % path)


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
                raise SystemExit("check.py: 找不到工作表 %r" % sheet)
        else:
            target = sheets[0][1]
        if not target:
            raise SystemExit("check.py: 工作表关系缺失")
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


def to_number(text):
    """返回 (数值或None, 状态 ok/empty/unparsable)。千分位与百分比自动处理。"""
    s = str(text).strip()
    if not s:
        return None, "empty"
    percent = s.endswith("%")
    clean = s.replace(",", "").replace("%", "")
    clean = re.sub(r"[。]+$", "", clean).replace("．", ".")
    if not NUM_RE.match(clean):
        return None, "unparsable"
    try:
        n = float(clean)
    except ValueError:
        return None, "unparsable"
    return (n / 100 if percent else n), "ok"


def check_table(rows, header):
    """rows 为表头之后的数据行。返回 (issues, 数值列数)。"""
    data_cols = [(i, str(v).strip()) for i, v in enumerate(header) if str(v).strip()]
    numeric_cols = {}
    for idx, name in data_cols:
        vals = [(ri, ) + to_number(r[idx] if idx < len(r) else "") for ri, r in enumerate(rows)]
        ok = [(ri, n) for ri, n, s in vals if s == "ok"]
        if ok:
            numeric_cols[idx] = {"name": name, "vals": vals, "ok": ok}
    issues = []
    subtotal_rows = [ri for ri, r in enumerate(rows)
                     if r and SUBTOTAL_RE.search(str(r[0]).strip())]

    # 1. 合计行校验：从上一合计行之后累加到当前合计行
    for idx, info in numeric_cols.items():
        ok_map = dict(info["ok"])
        start = 0
        for ri in subtotal_rows:
            if idx >= len(rows[ri]):
                start = ri + 1
                continue
            total, status = to_number(rows[ri][idx])
            if status != "ok":
                start = ri + 1
                continue
            expect = sum(n for rj, n in ok_map.items() if start <= rj < ri)
            if abs(expect - total) > 0.005:
                issues.append(("红", "合计行校验",
                               "第%d行[%s]「%s」列＝%s，但该组数据行之和＝%s（复核公式：合计单元格 vs 上方数据行求和）"
                               % (ri + 1, rows[ri][0], info["name"], total, round(expect, 4))))
            start = ri + 1

    # 2. 负值
    for idx, info in numeric_cols.items():
        if COUNT_COL_RE.search(info["name"]):
            for ri, n in info["ok"]:
                if n < 0:
                    issues.append(("红", "负值检查",
                                   "第%d行「%s」列＝%s，人数/数量/金额不应为负" % (ri + 1, info["name"], n)))

    # 3. 可疑比率
    for idx, info in numeric_cols.items():
        if not RATE_COL_RE.search(info["name"]):
            continue
        values = [n for _, n in info["ok"]]
        has_fraction = any(0 < v < 1 for v in values)
        for ri, n in info["ok"]:
            if n in (0.0, 1.0, 100.0):
                issues.append(("黄", "可疑比率",
                               "第%d行「%s」列＝%s，0%%/100%% 常见于未落实数据，建议核对分子分母"
                               % (ri + 1, info["name"], n)))
            elif n > 1 and has_fraction and n <= 100:
                issues.append(("黄", "比率口径",
                               "第%d行「%s」列＝%s，同列并存小数制比率，疑似口径不一致"
                               % (ri + 1, info["name"], n)))

    # 4. 跳变
    for idx, info in numeric_cols.items():
        nums = [(ri, n) for ri, n in info["ok"] if n != 0]
        if len(nums) < 4:
            continue
        med = median([abs(n) for _, n in nums])
        if med <= 0:
            continue
        for ri, n in nums:
            if abs(n) > med * JUMP_RATIO:
                issues.append(("黄", "跳变检查",
                               "第%d行「%s」列＝%s，超过列内中位数（%s）的 3 倍，建议核实"
                               % (ri + 1, info["name"], n, round(med, 4))))

    # 5. 空值与解析失败
    for idx, info in numeric_cols.items():
        for ri, n, s in info["vals"]:
            if s == "empty":
                issues.append(("黄", "空值", "第%d行「%s」列为空" % (ri + 1, info["name"])))
            elif s == "unparsable":
                raw = str(rows[ri][idx]) if idx < len(rows[ri]) else ""
                if re.search(r"\d", raw):
                    issues.append(("黄", "解析失败",
                                   "第%d行「%s」列＝%r，形似数值但无法解析（全角符号/混入文字？）"
                                   % (ri + 1, info["name"], raw)))
    return issues, len(numeric_cols)


def render(issues, path, n_cols):
    red = [i for i in issues if i[0] == "红"]
    yellow = [i for i in issues if i[0] == "黄"]
    lines = ["# 报表复核清单", "",
             "来源：%s（识别出 %d 个数值列）" % (path, n_cols),
             "结果：红色 %d 项（确定性不一致），黄色 %d 项（可疑待核）。" % (len(red), len(yellow)),
             ""]
    if red:
        lines.append("## 红色（需更正或核实后才能报送）")
        lines += ["- [%s] %s" % (kind, msg) for _, kind, msg in red]
        lines.append("")
    if yellow:
        lines.append("## 黄色（可疑，建议逐项核对）")
        lines += ["- [%s] %s" % (kind, msg) for _, kind, msg in yellow]
        lines.append("")
    if not issues:
        lines.append("机械检查全部通过（绿）。口径、跨表一致性等语义检查仍需按复核清单进行。")
    lines.append("本清单只读不改原文件；更正值经用户确认后自行回填。")
    return "\n".join(lines) + "\n"


def main(argv=None):
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    parser = argparse.ArgumentParser(prog="check.py", description="报表数值机械复核")
    parser.add_argument("file", help="xlsx/csv 文件")
    parser.add_argument("--sheet", help="工作表名或序号")
    parser.add_argument("--header", type=int, default=0, help="表头行号（从0计）")
    parser.add_argument("--out", help="报告输出路径")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        rows = load_rows(args.file, args.sheet)
        if args.header >= len(rows):
            raise SystemExit("check.py: --header 超出范围（共 %d 行）" % len(rows))
        issues, n_cols = check_table(rows[args.header + 1:], rows[args.header])
    except SystemExit as exc:
        print(str(exc.code) if exc.code not in (0, None) else exc)
        return 2
    if args.json:
        print(json.dumps({"file": args.file, "numeric_cols": n_cols,
                          "issues": [{"level": lv, "kind": k, "msg": m}
                                     for lv, k, m in issues]},
                         ensure_ascii=False, indent=2))
        return 0
    report = render(issues, args.file, n_cols)
    if args.out:
        parent = os.path.dirname(os.path.abspath(args.out))
        os.makedirs(parent, exist_ok=True)
        with open(args.out, "w", encoding="utf-8-sig", newline="\n") as f:
            f.write(report)
        print("复核清单已写入：%s" % args.out)
    else:
        print(report, end="" if report.endswith("\n") else "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
