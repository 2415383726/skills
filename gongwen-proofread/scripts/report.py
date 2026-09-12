#!/usr/bin/env python3
"""Offline source validation and HTML rendering. Python 3.8+, standard library only."""

import argparse
import difflib
import hashlib
import html
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import provenance


class DataError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise DataError(message)


def obj(value, path):
    require(isinstance(value, dict), path + " 必须是对象")
    return value


def string(value, path, nonempty=True):
    require(isinstance(value, str), path + " 必须是字符串")
    require(not nonempty or bool(value.strip()), path + " 不能为空")
    require(not any(ord(c) == 0 or 0xD800 <= ord(c) <= 0xDFFF for c in value),
            path + " 含有无法安全显示的字符")
    return value


def strings(value, path):
    require(isinstance(value, list), path + " 必须是列表")
    for item in value:
        string(item, path)
    return value


def identifier(value, path):
    string(value, path)
    require(bool(re.fullmatch(r"[A-Za-z0-9_-]+", value)), path + " 仅允许字母、数字、下划线和连字符")
    return value


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "JSON 存在重复字段：" + key)
        result[key] = value
    return result


def load_json(path):
    with Path(path).open(encoding="utf-8-sig") as handle:
        return json.load(handle, object_pairs_hook=unique_object)


def document_units(document):
    obj(document, "document")
    for name in ("title", "source_name", "scope"):
        string(document.get(name), "document." + name)
    strings(document.get("limitations"), "document.limitations")
    blocks = document.get("blocks")
    require(isinstance(blocks, list) and bool(blocks), "document.blocks 必须是非空列表")
    ids, units = set(), {}

    def register(item, is_text):
        obj(item, "文字单元")
        bid = identifier(item.get("id"), "单元 id")
        require(bid not in ids, "重复单元 id：" + bid)
        ids.add(bid)
        string(item.get("location"), bid + ".location")
        if is_text:
            text = string(item.get("text"), bid + ".text", nonempty=False)
            if text.strip():
                units[bid] = item

    for block in blocks:
        obj(block, "block")
        kind = block.get("kind")
        require(kind in ("paragraph", "heading", "table"), "未知 block.kind：" + str(kind))
        register(block, kind != "table")
        if kind == "table":
            rows = block.get("rows")
            require(isinstance(rows, list) and bool(rows), "表格 rows 必须非空")
            require(isinstance(rows[0], list) and bool(rows[0]), "表格首行必须非空")
            width = len(rows[0])
            header_rows = block.get("header_rows", 0)
            require(type(header_rows) is int and 0 <= header_rows <= len(rows), "header_rows 超出范围")
            for row in rows:
                require(isinstance(row, list) and len(row) == width, "表格各行必须具有相同列数")
                for cell in row:
                    register(cell, True)
    require(bool(units), "未读取到可检查文字，不能生成校对报告")
    return units


def locate(text, anchor, label):
    quote = string(anchor.get("quote"), label + ".quote")
    starts, pos = [], 0
    while True:
        pos = text.find(quote, pos)
        if pos < 0:
            break
        starts.append(pos)
        pos += 1
    require(bool(starts), label + " 的 quote " + repr(quote) + " 不存在于原文；请核对 block_id 和原字，不作模糊匹配")
    occurrence = anchor.get("occurrence")
    if occurrence is None:
        require(len(starts) == 1, label + " 的 quote " + repr(quote) + " 出现 " + str(len(starts)) + " 次，必须核对目标并填写 occurrence（从1起算），不能默认选第一次")
        occurrence = 1
    require(type(occurrence) is int and 1 <= occurrence <= len(starts), label + " 的 occurrence 超出范围")
    start = starts[occurrence - 1]
    return start, start + len(quote)


def validate(document, review):
    units = document_units(document)
    obj(review, "review")
    if "document_sha256" in review:
        require(review["document_sha256"] == provenance.digest(document), "报告结果与原文版本不匹配")
        provenance.verify(document)
    string(review.get("method"), "review.method")
    strings(review.get("limitations"), "review.limitations")
    passes = review.get("passes")
    require(isinstance(passes, list) and len(passes) == 2, "passes 必须包含 A、B 两路记录，未完成时使用空列表")
    checked = {}
    for entry in passes:
        obj(entry, "pass")
        pid = entry.get("id")
        require(pid in ("A", "B") and pid not in checked, "pass id 必须分别为 A、B")
        members = strings(entry.get("checked_block_ids"), "checked_block_ids")
        require(len(members) == len(set(members)), "检查记录有重复 id：" + pid)
        require(set(members) <= set(units), "检查记录包含未知或空文字单元：" + pid)
        checked[pid] = set(members)
    findings = review.get("findings")
    require(isinstance(findings, list), "findings 必须是列表")
    finding_ids, ranges = set(), {bid: [] for bid in units}
    resolved = []
    checked_once = checked["A"] | checked["B"]
    for finding in findings:
        obj(finding, "finding")
        fid = identifier(finding.get("id"), "finding.id")
        require(fid not in finding_ids, "重复 finding.id：" + fid)
        finding_ids.add(fid)
        severity = finding.get("severity")
        require(severity in ("confirmed", "pending"), fid + " 的 severity 无效")
        for name in ("category", "reason"):
            string(finding.get(name), fid + "." + name)
        require(finding.get("reviewed") is True, fid + " 尚未标记为复核完成")
        anchors = finding.get("anchors")
        require(isinstance(anchors, list) and bool(anchors), fid + " 缺少 anchors")
        require("suggestion" in finding, fid + " 缺少 suggestion")
        if severity == "confirmed":
            require(len(anchors) == 1, fid + " 的明确错误必须只有一个锚点")
            string(finding["suggestion"], fid + ".suggestion", nonempty=False)
        else:
            require(finding["suggestion"] is None, fid + " 待核实项不能给出猜测替换")
        resolved_anchors = []
        for index, anchor in enumerate(anchors):
            obj(anchor, fid + ".anchor")
            bid = identifier(anchor.get("block_id"), fid + ".block_id")
            require(bid in units, fid + " 引用了未知或空文字单元：" + bid)
            require(bid in checked_once, fid + " 引用了尚未检查的单元：" + bid)
            start, end = locate(units[bid]["text"], anchor, fid + "/" + bid)
            if severity == "confirmed":
                require(finding["suggestion"] != anchor["quote"], fid + " 的修改前后相同")
            for previous in ranges[bid]:
                require(end <= previous["start"] or start >= previous["end"],
                        fid + " 与 " + previous["finding_id"] + " 的定位重叠，请复核合并")
            entry = dict(anchor, start=start, end=end, finding_id=fid,
                         marker="mark-" + fid + "-" + str(index), severity=severity)
            ranges[bid].append(entry)
            resolved_anchors.append(entry)
        resolved.append(dict(finding, anchors=resolved_anchors))
    order = {bid: number for number, bid in enumerate(units)}
    resolved.sort(key=lambda f: min((order[a["block_id"]], a["start"]) for a in f["anchors"]))
    for spans in ranges.values():
        spans.sort(key=lambda s: s["start"])
    return units, checked, resolved, ranges


def esc(value):
    return html.escape(str(value), quote=True)


def highlighted(unit, spans):
    text, parts, cursor = unit["text"], [], 0
    for span in spans:
        parts.append(esc(text[cursor:span["start"]]))
        css = "error" if span["severity"] == "confirmed" else "question"
        label = span["quote"] + ("，查看修改意见" if css == "error" else "，查看待核实事项")
        parts.append('<button type="button" class="{}" id="{}" data-issue="{}" aria-label="{}">{}</button>'.format(
            css, span["marker"], span["finding_id"], esc(label), esc(span["quote"])))
        cursor = span["end"]
    parts.append(esc(text[cursor:]))
    return "".join(parts)


def render_document(document, ranges):
    parts = []
    for number, block in enumerate(document["blocks"], 1):
        bid = block["id"]
        if block["kind"] == "table":
            body = '<div><div class="table-caption">{}</div><div class="table-wrap"><table class="doc-table">'.format(esc(block["location"]))
            headers = block.get("header_rows", 0)
            body += "<tbody>"
            for row_index, row in enumerate(block["rows"]):
                body += "<tr>"
                for cell in row:
                    tag = "th" if row_index < headers else "td"
                    body += '<{0} id="unit-{1}" class="source-text" title="{2}">{3}</{0}>'.format(
                        tag, cell["id"], esc(cell["location"]), highlighted(cell, ranges.get(cell["id"], [])))
                body += "</tr>"
            body += "</tbody></table></div></div>"
        else:
            tag = "h3" if block["kind"] == "heading" else "p"
            body = '<{0} class="source-text">{1}</{0}>'.format(tag, highlighted(block, ranges.get(bid, [])))
        parts.append('<div class="block" id="unit-{}"><span class="number" title="{}">{}</span>{}</div>'.format(
            bid, esc(block["location"]), esc(block["location"]), body))
    return "\n".join(parts)


def change_markup(before, after):
    """Highlight only changed characters; preserve the full anchor context."""
    left, right, pairs = [], [], []
    for op, a, b, c, d in difflib.SequenceMatcher(None, before, after, autojunk=False).get_opcodes():
        x, y = before[a:b], after[c:d]
        left.append(esc(x) if op == 'equal' else '<del>' + esc(x) + '</del>')
        right.append(esc(y) if op == 'equal' else '<ins>' + esc(y) + '</ins>')
        if op != 'equal':
            pairs.append((x, y))
    punctuation = dict(zip('?!,:;()', '？！，：；（）'))
    width_only = bool(pairs) and all(x and ''.join(punctuation.get(ch, ch) for ch in x) == y
                                   and all(ch in punctuation for ch in x) for x, y in pairs)
    note = '中文标点应使用全角符号。' if width_only else ''
    return ''.join(left), ''.join(right) if after else '<span class="delete-label">删除</span>', note


def issue_card(finding, number, units):
    anchors = finding["anchors"]
    reason = finding["reason"]
    if finding["severity"] == "confirmed":
        before, replacement, note = change_markup(anchors[0]["quote"], finding["suggestion"])
        generic = '复核确认此处“{}”应为“{}”。'.format(anchors[0]["quote"], finding["suggestion"])
        if reason == generic:
            reason = note
        elif note:
            reason = note
        change = '<span class="before">{}</span><span class="arrow" aria-hidden="true">→</span><span class="sr-only">改为</span><span class="after">{}</span>'.format(before, replacement)
    else:
        change = " / ".join(esc(a["quote"]) for a in anchors)
    links = []
    for anchor in anchors:
        source = units[anchor["block_id"]]
        links.append('<a class="locate" href="#{0}" data-target="{0}" aria-label="定位：{1}">{1} ↗</a>'.format(
            anchor["marker"], esc(source["location"])))
    return ('<section class="issue" id="issue-{id}" data-severity="{severity}" tabindex="0" role="group" aria-label="修改点 {number}，按回车定位原文">'
            '<div class="change">{change}</div>{reason}'
            '<div class="issue-meta"><span class="badge"><span class="issue-number">{number:02d}</span>{category}</span>'
            '<div class="location-links">{links}</div></div></section>').format(
                id=finding["id"], severity=finding["severity"], number=number,
                category=esc(finding["category"]), change=change,
                reason=("<p>" + esc(reason) + "</p>") if reason else "", links="<br>".join(links))


def result_scope(document, review, units, checked):
    """Show actual omissions only. Execution evidence stays in review.json."""
    notes = list(document['limitations'])
    both = checked['A'] & checked['B']
    if len(both) < len(units):
        notes.append('部分原文尚未完成检查。')
    for note in review['limitations']:
        # These are known machine-generated audit messages, not missing content.
        if re.search(r'由主 Agent 补做，独立性降低$', note):
            continue
        if re.fullmatch(r'发现 \d+ 个批次的 A/B 执行上下文标识相同，不满足隔离双检要求。', note):
            continue
        if note.startswith('缺少检查结果：'):
            continue  # Actual uncovered locations are listed below.
        if note.startswith(('缺少候选复核结果：', '缺少候选组复核：')):
            notes.append('部分修改点尚未完成复核。')
        elif note.startswith('这是部分交付快照，'):
            notes.append('当前为部分结果。')
        elif note == '长文名称一致性检查未完成':
            notes.append('全文名称一致性检查尚未完成。')
        else:
            notes.append(note)
    notes = list(dict.fromkeys(notes))
    if not notes:
        return ''
    content = '<ul>' + ''.join('<li>{}</li>'.format(esc(note)) for note in notes) + '</ul>'
    if len(both) < len(units):
        content += '<ul>' + ''.join('<li><a href="#unit-{}">{}</a></li>'.format(bid, esc(unit['location']))
                                   for bid, unit in units.items() if bid not in both) + '</ul>'
    if len(notes) == 1 and len(both) == len(units):
        return '<div class="range-note"><p>{}</p></div>'.format(esc(notes[0]))
    return '<details class="range-note"><summary>部分内容未完成</summary>{}</details>'.format(content)


def render(document, review):
    units, checked, findings, ranges = validate(document, review)
    confirmed = [f for f in findings if f["severity"] == "confirmed"]
    pending = [f for f in findings if f["severity"] == "pending"]
    definite_html = "".join(issue_card(f, n, units) for n, f in enumerate(confirmed, 1))
    if not confirmed:
        if not checked['A'] | checked['B']:
            message = '尚无完成的检查记录。'
        elif review['limitations'] or len(checked['A'] & checked['B']) != len(units):
            message = '当前没有已确认的修改点。'
        else:
            message = '未发现明确的文字或标点错误。'
        symbol = '—' if not checked['A'] | checked['B'] or review['limitations'] or len(checked['A'] & checked['B']) != len(units) else '✓'
        definite_html = '<div class="empty-state"><span class="empty-symbol" aria-hidden="true">{}</span>{}</div>'.format(symbol, message)
    pending_html = ""
    if pending:
        pending_html = '<details class="pending" id="pending"><summary>待核实 <span>{} 项</span></summary>{}</details>'.format(
            len(pending), "".join(issue_card(f, n, units) for n, f in enumerate(pending, len(confirmed) + 1)))
    fingerprint = hashlib.sha256(json.dumps(document, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    summary = '<span><strong>{}</strong>处修改</span>'.format(len(confirmed))
    if pending:
        summary += '<span class="pending-total"><strong>{}</strong>项待核实</span>'.format(len(pending))
    first = document['blocks'][0]
    document_title = '' if (first['kind'] == 'heading' and first['text'].strip() == document['title'].strip()) else '<h2>{}</h2>'.format(esc(document['title']))
    values = {
        "TITLE": esc(document["title"]), "SOURCE": esc(document["source_name"]),
        "SUMMARY": summary, "CONFIRMED_COUNT": str(len(confirmed)),
        "DOCUMENT_TITLE": document_title, "DOCUMENT": render_document(document, ranges),
        "FINDINGS": definite_html, "PENDING": pending_html, "FINGERPRINT": fingerprint,
        "RANGE_NOTE": result_scope(document, review, units, checked),
    }
    template_path = Path(__file__).resolve().parent.parent / "assets" / "report.html"
    template = template_path.read_text(encoding="utf-8")
    found = set(re.findall(r"@@([A-Z_]+)@@", template))
    require(found == set(values), "模板字段不完整或出现未知字段")
    return re.sub(r"@@([A-Z_]+)@@", lambda match: values[match.group(1)], template)


def write_output(path, content, overwrite, inputs):
    inputs = list(inputs)
    for input_path in tuple(inputs):
        try:
            value = load_json(input_path)
        except (ValueError, OSError, UnicodeError):
            continue
        if isinstance(value, dict) and 'blocks' in value and isinstance(value.get('provenance'), dict):
            source_path = value['provenance'].get('source_path')
            if isinstance(source_path, str):
                inputs.append(source_path)
    target = Path(path).resolve()
    require(all(target != Path(p).resolve() for p in inputs), "输出路径不能与输入路径相同")
    skill_root = Path(__file__).resolve().parent.parent
    require(target != skill_root and skill_root not in target.parents, "输出不能写入技能包目录，请使用任务输出目录")
    for source in inputs:
        if target.exists():
            require(not os.path.samefile(str(target), str(source)), "输出不能与输入指向同一个文件")
    require(not target.exists() or overwrite, "输出已存在；换一个文件名，或明确使用 --overwrite")
    target.parent.mkdir(parents=True, exist_ok=True)
    if not overwrite:
        with target.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
    else:
        temp_name = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=str(target.parent), delete=False) as handle:
                temp_name = handle.name
                handle.write(content)
            os.replace(temp_name, str(target))
        finally:
            if temp_name and os.path.exists(temp_name):
                os.unlink(temp_name)
    return target


def split_text_unit(text, max_chars):
    if len(text) <= max_chars:
        return [text]
    pieces, start = [], 0
    sentence_ends = "。！？!?；;"
    closers = "”’）》】」』"
    while len(text) - start > max_chars:
        limit = start + max_chars
        floor = start + max(1, max_chars // 2)
        cut = -1
        for position in range(limit - 1, floor - 1, -1):
            if text[position] in sentence_ends:
                cut = position + 1
                while cut < limit and text[cut] in closers:
                    cut += 1
                break
        if cut <= start:
            cut = limit
        pieces.append(text[start:cut])
        start = cut
    if start < len(text):
        pieces.append(text[start:])
    return pieces


def main():
    parser = argparse.ArgumentParser(description="公文校对数据校验与离线 HTML 生成，不调用模型或网络。")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="把纯文本按原始行号编号")
    prepare.add_argument("--input", required=True)
    prepare.add_argument("--output", required=True)
    prepare.add_argument("--title", default="材料校对")
    prepare.add_argument("--encoding", default="utf-8-sig")
    prepare.add_argument("--max-unit-chars", type=int, default=1800,
                         help="超长物理行的最大分片字符数，默认 1800")
    prepare.add_argument("--overwrite", action="store_true")
    for command in ("validate", "render"):
        child = commands.add_parser(command)
        child.add_argument("--document", required=True)
        child.add_argument("--review", required=True)
        if command == "render":
            child.add_argument("--output", required=True)
            child.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            require(args.max_unit_chars > 0, "max-unit-chars 必须大于 0")
            source_record = provenance.snapshot(args.input)
            raw = Path(args.input).read_bytes()
            require(hashlib.sha256(raw).hexdigest() == source_record['source_sha256'], "读取期间源文件发生变化")
            source = raw.decode(args.encoding)
            blocks = []
            for line_number, line in enumerate(re.split(r"\r\n|\n|\r", source), 1):
                if not line.strip():
                    continue
                pieces = split_text_unit(line, args.max_unit_chars)
                for piece_number, piece in enumerate(pieces, 1):
                    location = "原文第{}行".format(line_number)
                    if len(pieces) > 1:
                        location += "（分片{}）".format(piece_number)
                    blocks.append({"id": "p" + str(len(blocks) + 1), "kind": "paragraph",
                                   "text": piece, "location": location})
            document = {"title": args.title, "source_name": Path(args.input).name,
                        "scope": "所提供纯文本的全部非空行；空白行不单独编号；超长行按原文顺序分片",
                        "limitations": [], "source_sha256": hashlib.sha256(raw).hexdigest(), "blocks": blocks}
            document_units(document)
            document = provenance.bind(document, source_record, 'report.py prepare；编码 ' + args.encoding + '；非空行与无损分片')
            output = write_output(args.output, json.dumps(document, ensure_ascii=False, indent=2) + "\n", args.overwrite, [args.input])
            print("原文编号完成：" + str(output))
        else:
            document, review = load_json(args.document), load_json(args.review)
            units, checked, findings, _ = validate(document, review)
            if args.command == "render":
                output = write_output(args.output, render(document, review), args.overwrite, [args.document, args.review])
                print("报告已生成：" + str(output))
            print("结构与定位校验通过（不代表语言判断正确）：{} 个提取后文字单元，两轮均已检查 {} 个，{} 条最终意见。".format(
                len(units), len(checked["A"] & checked["B"]), len(findings)))
            if set(units) != checked["A"] & checked["B"] or document["limitations"] or review["limitations"]:
                print("存在覆盖不足或范围限制，报告顶部将明确提示。")
    except (ValueError, OSError, UnicodeError, LookupError) as exc:
        print("错误：" + str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
