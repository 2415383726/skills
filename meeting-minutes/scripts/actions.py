#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""督办台账生成与检查：把会议行动项变成可跟踪的台账，缺责任人和时限的标"待确认"。

用法：
  python actions.py build --from 行动项.json --out 督办台账.csv [--meeting 名称] [--date 会议日期]
  python actions.py check 督办台账.csv [--asof 2026-09-13]

行动项 JSON 格式（由 Agent 从纪要/转写中提取，缺的字段留空，不要编造）：
  [{"事项": "...", "责任人": "...", "协办": "...", "截止日期": "...", "优先级": "高/中/低"}]

台账固定列：序号,事项,责任人,协办,截止日期,优先级,状态,来源,备注
规则：
- 责任人或截止日期缺失/为空 → 填"待确认"并计数提醒，绝不编造；
- 日期统一为 YYYY-MM-DD（支持 2025.1.1、2025/1/1、20250101、2025年1月2日）；
- check 模式：缺责任人/日期、日期非法、超过 --asof 仍未完成（逾期）逐条列出。

红线：不生成任何"看起来合理"的责任人或日期。
"""

import argparse
import csv
import datetime
import json
import os
import re
import sys

COLUMNS = ["序号", "事项", "责任人", "协办", "截止日期", "优先级", "状态", "来源", "备注"]
DATE_PATTERNS = [
    (re.compile(r"^\d{4}-\d{1,2}-\d{1,2}$"), "%Y-%m-%d"),
    (re.compile(r"^\d{4}/\d{1,2}/\d{1,2}$"), "%Y/%m/%d"),
    (re.compile(r"^\d{4}\.\d{1,2}\.\d{1,2}$"), "%Y.%m.%d"),
    (re.compile(r"^\d{8}$"), "%Y%m%d"),
    (re.compile(r"^\d{4}年\d{1,2}月\d{1,2}日$"), "%Y年%m月%d日"),
]


def norm_date(text):
    s = str(text or "").strip()
    if not s:
        return "", False
    for pattern, fmt in DATE_PATTERNS:
        if pattern.match(s):
            try:
                return datetime.datetime.strptime(s, fmt).date().isoformat(), True
            except ValueError:
                continue
    return s, False


def read_json(path):
    if not os.path.isfile(path):
        raise SystemExit("actions.py: 文件不存在：%s" % path)
    with open(path, "rb") as f:
        data = f.read()
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return json.loads(data.decode(enc))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    raise SystemExit("actions.py: 无法解析 JSON（编码或格式错误）：%s" % path)


def read_csv_rows(path):
    if not os.path.isfile(path):
        raise SystemExit("actions.py: 文件不存在：%s" % path)
    with open(path, "rb") as f:
        data = f.read()
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise SystemExit("actions.py: 无法识别编码：%s" % path)
    return [r for r in csv.reader(text.splitlines()) if any(c.strip() for c in r)]


def cmd_build(args):
    items = read_json(args.frm)
    if not isinstance(items, list):
        raise SystemExit("actions.py: JSON 顶层应为行动项数组")
    source = args.meeting or ""
    date = norm_date(args.date)[0] if args.date else ""
    rows, warnings = [], []
    for i, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            warnings.append("第 %d 条不是对象，已跳过" % i)
            continue
        task = str(item.get("事项", "")).strip()
        if not task:
            warnings.append("第 %d 条缺「事项」，已跳过（无事项不建台账）" % i)
            continue
        owner = str(item.get("责任人", "")).strip() or "待确认"
        deadline, ok = norm_date(item.get("截止日期"))
        if not str(item.get("截止日期", "")).strip():
            warnings.append("第 %d 条「%s」缺截止日期，已标待确认" % (i, task[:20]))
        elif not ok:
            warnings.append("第 %d 条「%s」截止日期 %r 无法解析，已标待确认" % (i, task[:20], item.get("截止日期")))
            deadline = "待确认"
        if owner == "待确认":
            warnings.append("第 %d 条「%s」缺责任人，已标待确认" % (i, task[:20]))
        rows.append([len(rows) + 1, task, owner, str(item.get("协办", "")).strip(),
                     deadline or "待确认", str(item.get("优先级", "")).strip() or "中",
                     "待办", source or (str(item.get("来源", "")).strip()), ""])
    parent = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(parent, exist_ok=True)
    with open(args.out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        w.writerows(rows)
    print("督办台账已生成：%s（%d 条行动项）" % (args.out, len(rows)))
    for wmsg in warnings:
        print("注意：%s" % wmsg)
    if any("待确认" in r[2] or "待确认" in r[4] for r in rows):
        print("提醒：台账含「待确认」项，请会后核实责任人与时限后再分发。")
    return 0


def cmd_check(args):
    raw = read_csv_rows(args.file)
    if not raw:
        raise SystemExit("actions.py: 台账为空")
    header = [h.strip() for h in raw[0]]
    need = ["事项", "责任人", "截止日期", "状态"]
    missing_cols = [c for c in need if c not in header]
    if missing_cols:
        print("台账缺少必需列：%s" % "、".join(missing_cols))
        return 1
    idx = {c: header.index(c) for c in need}
    asof = datetime.date.fromisoformat(args.asof) if args.asof else datetime.date.today()
    problems, overdue = [], []
    for r in raw[1:]:
        r = list(r) + [""] * (len(header) - len(r))
        no = r[header.index("序号")] if "序号" in header else "?"
        if not r[idx["责任人"]].strip():
            problems.append("第%s条缺责任人" % no)
        dl, ok = norm_date(r[idx["截止日期"]])
        if not r[idx["截止日期"]].strip():
            problems.append("第%s条缺截止日期" % no)
        elif not ok:
            problems.append("第%s条截止日期 %r 非法" % (no, r[idx["截止日期"]]))
        elif r[idx["状态"]].strip() not in ("完成", "已办结", "已销号"):
            try:
                if datetime.date.fromisoformat(dl) < asof:
                    task = r[idx["事项"]].strip() if "事项" in idx else ""
                    overdue.append("第%s条「%s」（截止 %s）" % (no, task, dl))
            except ValueError:
                pass
    print("台账检查：%s（%d 条）" % (args.file, len(raw) - 1))
    if problems:
        print("待补齐 %d 项：" % len(problems))
        for p in problems:
            print("- %s" % p)
    if overdue:
        print("逾期未办结 %d 项（截至 %s）：" % (len(overdue), asof.isoformat()))
        for o in overdue:
            print("- %s" % o)
    if not problems and not overdue:
        print("台账完整，无逾期项。")
        return 0
    return 1


def main(argv=None):
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    parser = argparse.ArgumentParser(prog="actions.py", description="督办台账生成与检查")
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build", help="从行动项 JSON 生成台账")
    p_build.add_argument("--from", dest="frm", required=True)
    p_build.add_argument("--out", required=True)
    p_build.add_argument("--meeting")
    p_build.add_argument("--date")
    p_build.set_defaults(func=cmd_build)

    p_check = sub.add_parser("check", help="检查既有台账")
    p_check.add_argument("file")
    p_check.add_argument("--asof")
    p_check.set_defaults(func=cmd_check)

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
