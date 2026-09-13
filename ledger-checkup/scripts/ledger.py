#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""人员台账体检：导入/上报前对花名册类 Excel/CSV 做字段级质量检查。

用法：
  python ledger.py check <文件> [--key 列名 --key 列名...] [--required 列名...]
                          [--asof 2025-12-31] [--sheet 名称] [--header 行号] [--json]
  python ledger.py clean <文件> <输出.csv> [--sheet ...] [--header ...]
                          （可选：生成清洗副本——去首尾空格、日期规范化；原文件不动）

确定性检查项：
- 身份证：18 位校验码（GB 11643）、出生段有效性、与出生日期列/性别列的交叉一致（红）；
- 唯一键：--key 指定列（如 身份证号/工号）重复行（红）；
- 必填缺失：--required 指定列的空值（红）；
- 日期格式：同列多种格式混用、未来日期、年龄与出生日期不符（黄）；
- 枚举漂移：低基数列中的近似重复值（空格/全角差异）与孤立取值（黄）；
- 占位值：N/A、TBD、test、未知、xxx 等（黄）。

红线：只读原文件；clean 生成的副本不覆盖输入。
"""

import argparse
import csv
import datetime
import json
import os
import re
import sys
import zipfile
from collections import Counter

import xml.etree.ElementTree as ET

ID_WEIGHTS = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
ID_MAP = "10X98765432"
PLACEHOLDER_RE = re.compile(r"^(n/?a|tbd|test|xxx|未知|无|待定|暂缺)$", re.I)
DATE_PATTERNS = [
    (re.compile(r"^\d{4}-\d{1,2}-\d{1,2}$"), "%Y-%m-%d"),
    (re.compile(r"^\d{4}/\d{1,2}/\d{1,2}$"), "%Y/%m/%d"),
    (re.compile(r"^\d{4}\.\d{1,2}\.\d{1,2}$"), "%Y.%m.%d"),
    (re.compile(r"^\d{8}$"), "%Y%m%d"),
    (re.compile(r"^\d{4}年\d{1,2}月\d{1,2}日$"), "%Y年%m月%d日"),
]
KEY_HEADERS = {"身份证": ("身份证号", "身份证号码", "证件号码", "身份证件号"),
               "工号": ("工号", "职工号", "人员编号", "编号"),
               "出生": ("出生日期", "出生年月", "出生"),
               "性别": ("性别",),
               "年龄": ("年龄",)}


def find_col(headers, key):
    names = KEY_HEADERS[key]
    for h in headers:
        hs = str(h).strip()
        if hs in names:
            return hs
    for h in headers:
        hs = str(h).strip()
        if any(n in hs for n in names):
            return hs
    return None


def load_rows(path, sheet=None):
    if not os.path.isfile(path):
        raise SystemExit("ledger.py: 文件不存在：%s" % path)
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
            raise SystemExit("ledger.py: 无法识别编码：%s" % path)
        return [r for r in csv.reader(text.splitlines()) if any(c.strip() for c in r)]
    raise SystemExit("ledger.py: 暂只支持 xlsx/csv：%s" % path)


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
                raise SystemExit("ledger.py: 找不到工作表 %r" % sheet)
        else:
            target = sheets[0][1]
        if not target:
            raise SystemExit("ledger.py: 工作表关系缺失")
        target = target if target.startswith("xl/") else "xl/" + target.lstrip("/")
        root = ET.fromstring(z.read(target))
        rows = []
        for row in root.iter(ns + "row"):
            cells = {}
            for c in row.iter(ns + "c"):
                ref = c.get("r", "")
                m = re.match(r"[A-Z]+", ref)
                col = (col_index(m.group(0)) if m else len(cells) + 1)
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


def col_index(letters):
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n


def parse_date(text):
    s = str(text).strip()
    for pattern, fmt in DATE_PATTERNS:
        if pattern.match(s):
            try:
                return datetime.datetime.strptime(s, fmt).date(), fmt
            except ValueError:
                continue
    return None, None


def id_checksum_ok(idnum):
    total = sum(int(idnum[i]) * ID_WEIGHTS[i] for i in range(17))
    return ID_MAP[total % 11] == idnum[-1].upper()


def parse_id(idnum):
    """返回 (问题列表, 出生抽检 dict)；仅处理 18 位。"""
    problems = []
    info = {}
    if not re.fullmatch(r"\d{17}[\dXx]", idnum):
        problems.append("不是标准18位格式")
        return problems, info
    if not id_checksum_ok(idnum):
        problems.append("校验码不符")
    try:
        birth = datetime.date(int(idnum[6:10]), int(idnum[10:12]), int(idnum[12:14]))
        info["birth"] = birth
        if birth > datetime.date.today():
            problems.append("出生段在未来")
    except ValueError:
        problems.append("出生段不是有效日期")
    info["gender"] = "男" if int(idnum[16]) % 2 == 1 else "女"
    return problems, info


def check_ledger(headers, rows, keys, required, asof):
    issues = []

    def red(kind, msg):
        issues.append(("红", kind, msg))

    def yellow(kind, msg):
        issues.append(("黄", kind, msg))

    # 唯一键重复
    for key in keys:
        idx = None
        for i, h in enumerate(headers):
            if str(h).strip() == key:
                idx = i
                break
        if idx is None:
            yellow("唯一键", "未找到列 %r，跳过该键查重" % key)
            continue
        seen = {}
        for ri, r in enumerate(rows):
            v = str(r[idx]).strip() if idx < len(r) else ""
            if v:
                seen.setdefault(v, []).append(ri + 1)
        for v, rlist in seen.items():
            if len(rlist) > 1:
                red("唯一键重复", "「%s」列 值 %r 重复于行 %s" % (key, v, "、".join(map(str, rlist))))

    # 必填缺失
    for key in required:
        idx = None
        for i, h in enumerate(headers):
            if str(h).strip() == key:
                idx = i
                break
        if idx is None:
            yellow("必填", "未找到列 %r，无法检查必填" % key)
            continue
        missing = [ri + 1 for ri, r in enumerate(rows)
                   if idx >= len(r) or not str(r[idx]).strip()]
        if missing:
            red("必填缺失", "「%s」列缺失 %d 行：%s" % (key, len(missing),
                                                "、".join(map(str, missing[:20])) + ("…" if len(missing) > 20 else "")))

    # 身份证交叉检查
    id_idx = id_h = None
    for i, h in enumerate(headers):
        if str(h).strip() in KEY_HEADERS["身份证"]:
            id_idx, id_h = i, str(h).strip()
            break
    birth_idx = find_col(headers, "出生")
    gender_idx = find_col(headers, "性别")
    age_idx = find_col(headers, "年龄")
    if id_idx is not None:
        birth_i = next((i for i, h in enumerate(headers) if str(h).strip() == birth_idx), None) if birth_idx else None
        gender_i = next((i for i, h in enumerate(headers) if str(h).strip() == gender_idx), None) if gender_idx else None
        age_i = next((i for i, h in enumerate(headers) if str(h).strip() == age_idx), None) if age_idx else None
        for ri, r in enumerate(rows):
            raw = str(r[id_idx]).strip() if id_idx < len(r) else ""
            if not raw or PLACEHOLDER_RE.match(raw):
                continue
            rowno = ri + 1
            problems, info = parse_id(raw)
            for p in problems:
                red("身份证", "第%d行「%s」＝%r：%s" % (rowno, id_h, raw, p))
            if "birth" not in info:
                continue
            if birth_i is not None and birth_i < len(r):
                d, _ = parse_date(r[birth_i])
                if d and d != info["birth"]:
                    yellow("出生不符", "第%d行 出生日期列（%s）与身份证出生段（%s）不一致"
                           % (rowno, d, info["birth"].isoformat()))
            if gender_i is not None and gender_i < len(r):
                g = str(r[gender_i]).strip()
                if g and g != info["gender"]:
                    yellow("性别不符", "第%d行 性别列（%s）与身份证第17位推算（%s）不一致"
                           % (rowno, g, info["gender"]))
            if age_i is not None and age_i < len(r):
                ref = asof or datetime.date.today()
                expect = ref.year - info["birth"].year - ((ref.month, ref.day) < (info["birth"].month, info["birth"].day))
                try:
                    got = int(str(r[age_i]).strip())
                except ValueError:
                    got = None
                if got is not None and abs(got - expect) > 1:
                    yellow("年龄不符", "第%d行 年龄列（%d）与出生日期推算（%d，截至%s）不一致"
                           % (rowno, got, expect, ref.isoformat()))

    # 日期列格式混用与未来日期
    for i, h in enumerate(headers):
        hs = str(h).strip()
        if "日期" not in hs and "年月" not in hs and "date" not in hs.lower():
            continue
        formats = Counter()
        future = []
        for ri, r in enumerate(rows):
            v = str(r[i]).strip() if i < len(r) else ""
            if not v:
                continue
            d, fmt = parse_date(v)
            if fmt:
                formats[fmt] += 1
                if d and d > (asof or datetime.date.today()):
                    future.append(ri + 1)
            else:
                formats["无法解析"] += 1
        if len(formats) > 1:
            yellow("日期格式", "「%s」列混用 %d 种格式：%s，导入前需统一"
                   % (hs, len(formats), "、".join(sorted(formats))))
        if future:
            yellow("未来日期", "「%s」列存在晚于 %s 的日期：%s" % (hs, (asof or datetime.date.today()).isoformat(),
                                                      "、".join(map(str, future[:10]))))

    # 枚举漂移与占位值（低基数文本列）
    for i, h in enumerate(headers):
        hs = str(h).strip()
        # 漂移检测用原始值（保留空格/全角差异），占位检测用去空格值
        values = [(ri, str(r[i])) for ri, r in enumerate(rows)
                  if i < len(r) and str(r[i]).strip()]
        if not values:
            continue
        distinct = {v for _, v in values}
        if 1 < len(distinct) <= 30:
            norm = {}
            for ri, v in values:
                norm.setdefault(re.sub(r"\s+", "", v), []).append((ri, v))
            for nv, items in norm.items():
                raws = {v for _, v in items}
                if len(raws) > 1:
                    yellow("枚举漂移", "「%s」列疑似同一取值的多种写法：%s（行 %s）"
                           % (hs, " / ".join(sorted(raws)), "、".join(str(ri) for ri, _ in items[:8])))
        for ri, v in values:
            if PLACEHOLDER_RE.match(v.strip()):
                yellow("占位值", "第%d行「%s」列＝%r，疑似未落实数据" % (ri + 1, hs, v.strip()))
    return issues


def completeness(headers, rows):
    stats = []
    for i, h in enumerate(headers):
        hs = str(h).strip()
        if not hs:
            continue
        vals = [str(r[i]).strip() for r in rows if i < len(r) and str(r[i]).strip()]
        rate = len(vals) / len(rows) if rows else 1
        grade = "绿" if rate > 0.99 else "黄" if rate > 0.95 else "橙" if rate > 0.8 else "红"
        stats.append((hs, len(vals), rate, grade, len({vals})))
    return stats


def do_clean(headers, rows, out_path):
    parent = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(parent, exist_ok=True)
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(headers)
        for r in rows:
            r = list(r) + [""] * (len(headers) - len(r)) if len(r) < len(headers) else r[:len(headers)]
            w.writerow([re.sub(r"\s+", "", str(v)) if v else "" for v in r])
    print("清洗副本已生成：%s（去首尾空格；原文件未改动）" % out_path)


def main(argv=None):
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    parser = argparse.ArgumentParser(prog="ledger.py", description="人员台账体检")
    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check", help="质量检查")
    p_check.add_argument("file")
    p_check.add_argument("--key", action="append", default=[], help="唯一键列名，可多次")
    p_check.add_argument("--required", action="append", default=[], help="必填列名，可多次")
    p_check.add_argument("--asof", help="年龄/未来日期的基准日，默认今天")
    p_check.add_argument("--sheet")
    p_check.add_argument("--header", type=int, default=0)
    p_check.add_argument("--json", action="store_true")
    p_check.set_defaults(func=cmd_check)

    p_clean = sub.add_parser("clean", help="生成清洗副本")
    p_clean.add_argument("file")
    p_clean.add_argument("out")
    p_clean.add_argument("--sheet")
    p_clean.add_argument("--header", type=int, default=0)
    p_clean.set_defaults(func=cmd_clean)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except SystemExit as exc:
        if exc.code and str(exc.code) not in ("0", "None"):
            print(str(exc.code))
            return 2
        raise


def _load(args):
    rows = load_rows(args.file, getattr(args, "sheet", None))
    if args.header >= len(rows):
        raise SystemExit("ledger.py: --header 超出范围（共 %d 行）" % len(rows))
    return rows[args.header], rows[args.header + 1:]


def cmd_check(args):
    headers, rows = _load(args)
    asof = datetime.date.fromisoformat(args.asof) if getattr(args, "asof", None) else None
    issues = check_ledger(headers, rows, args.key, args.required, asof)
    if args.json:
        payload = {"file": args.file, "rows": len(rows), "cols": len(headers),
                   "issues": [{"level": lv, "kind": k, "msg": m} for lv, k, m in issues]}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    red = [i for i in issues if i[0] == "红"]
    yellow = [i for i in issues if i[0] == "黄"]
    print("台账体检：%s（%d 行 × %d 列）" % (args.file, len(rows), len(headers)))
    print("结果：红色 %d 项，黄色 %d 项。" % (len(red), len(yellow)))
    if red:
        print("\n## 红色（导入/上报前必须处理）")
        for _, k, m in red:
            print("- [%s] %s" % (k, m))
    if yellow:
        print("\n## 黄色（建议核对）")
        for _, k, m in yellow:
            print("- [%s] %s" % (k, m))
    if not issues:
        print("机械检查未发现问题。字段口径（部门名称映射、枚举标准值）仍建议人工确认。")
    print("\n字段完整性：")
    for hs, n, rate, grade, _ in completeness(headers, rows):
        print("- [%s] %s：非空 %d/%d（%.0f%%）" % (grade, hs, n, len(rows), rate * 100))
    return 0


def cmd_clean(args):
    headers, rows = _load(args)
    do_clean(headers, rows, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
