#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""制度库全文检索：在本地文件夹中按关键词查找制度条款位置。

用法：
  python search.py <制度库目录> <关键词> [关键词...] [--ext md,txt,docx] [--json] [--context N]

行为：
- 递归遍历目录，对每个文档提取纯文本（txt/md 直读，docx 解包 word/document.xml）；
- 命中任一关键词即输出：文件、行号（或段落号）、命中行内容（截断）；
- 末尾汇总每个文件的命中数；关键词之间是"或"的关系。

说明：
- 仅用 Python 3.8+ 标准库；文本按 utf-8-sig / utf-8 / gbk 依次尝试；
- 输出为检索结果定位，条款含义与答案组装由 Agent 完成，本脚本不做语义判断。
"""

import argparse
import json
import os
import re
import sys
import zipfile

DEFAULT_EXTS = ("md", "txt", "docx")
MAX_LINE_SHOW = 160
W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def read_text_bytes(data):
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return None


def extract_docx_text(path):
    """提取 docx 各段文本，返回 [段落文本]；损坏包抛 ValueError。"""
    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError, OSError) as exc:
        raise ValueError("无法读取 docx：%s（%s）" % (path, exc))
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ValueError("docx 内容损坏：%s（%s）" % (path, exc))
    paragraphs = []
    for p in root.iter(W_NS + "p"):
        text = "".join(t.text or "" for t in p.iter(W_NS + "t"))
        paragraphs.append(text)
    return paragraphs


def load_units(path, ext):
    """把文件切成可检索单元：txt/md 按行，docx 按段落。返回 [(编号, 文本)]。"""
    with open(path, "rb") as f:
        data = f.read()
    if ext == "docx":
        return [(i + 1, t) for i, t in enumerate(extract_docx_text(path))]
    text = read_text_bytes(data)
    if text is None:
        raise ValueError("无法识别编码（已尝试 UTF-8/GBK）：%s" % path)
    return [(i + 1, line) for i, line in enumerate(text.splitlines())]


def search_file(path, keywords):
    """返回 [(编号, 命中关键词, 行文本截断)]。"""
    ext = path.rsplit(".", 1)[-1].lower()
    hits = []
    try:
        units = load_units(path, ext)
    except ValueError as exc:
        return hits, str(exc)
    except OSError as exc:
        return hits, "读取失败：%s" % exc
    for no, text in units:
        for kw in keywords:
            if kw and kw in text:
                show = text.strip()
                if len(show) > MAX_LINE_SHOW:
                    show = show[:MAX_LINE_SHOW] + "…"
                hits.append((no, kw, show))
                break
    return hits, None


def iter_files(root, exts):
    if os.path.isfile(root):
        yield root
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            if name.rsplit(".", 1)[-1].lower() in exts:
                yield os.path.join(dirpath, name)


def main(argv=None):
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    parser = argparse.ArgumentParser(prog="search.py", description="制度库关键词检索")
    parser.add_argument("directory", help="制度库目录或单个文件")
    parser.add_argument("keywords", nargs="+", help="关键词（或关系）")
    parser.add_argument("--ext", default=",".join(DEFAULT_EXTS), help="扩展名过滤，默认 md,txt,docx")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    args = parser.parse_args(argv)

    if not os.path.exists(args.directory):
        print("search.py: 路径不存在：%s" % args.directory)
        return 2
    exts = tuple(e.strip().lower() for e in args.ext.split(",") if e.strip())
    results = []
    errors = []
    file_count = 0
    for path in iter_files(args.directory, exts):
        file_count += 1
        hits, err = search_file(path, args.keywords)
        if err:
            errors.append("%s: %s" % (path, err))
        if hits:
            results.append({"file": path, "count": len(hits),
                            "hits": [{"line": no, "keyword": kw, "text": t} for no, kw, t in hits]})

    total = sum(r["count"] for r in results)
    if args.json:
        print(json.dumps({"root": args.directory, "keywords": args.keywords,
                          "files_scanned": file_count, "files_matched": len(results),
                          "total_hits": total, "results": results, "errors": errors},
                         ensure_ascii=False, indent=2))
        return 0
    print("检索：%s　关键词：%s" % (args.directory, " / ".join(args.keywords)))
    print("扫描 %d 个文件，命中 %d 个文件、%d 处。" % (file_count, len(results), total))
    for r in results:
        print("\n%s（%d 处）" % (r["file"], r["count"]))
        for h in r["hits"]:
            label = "第%d行" if r["file"].lower().endswith(("md", "txt")) else "第%d段"
            print("  %s｜[%s] %s" % (label % h["line"], h["keyword"], h["text"]))
    for err in errors:
        print("提示：%s" % err)
    if not results:
        print("未命中。可尝试同义关键词（如\"休假/带薪年休假\"、\"差旅/出差\"）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
