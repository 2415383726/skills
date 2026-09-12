#!/usr/bin/env python3
"""Limited offline DOCX body extractor, Python 3.8+ standard library only."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
from xml.parsers import expat
import zipfile

import provenance
import report

W_NAMESPACES = {'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
                'http://purl.oclc.org/ooxml/wordprocessingml/main'}
MAX_PACKAGE = 128 * 1024 * 1024
MAX_XML = 64 * 1024 * 1024


def word(node):
    if node.tag.startswith('{'):
        ns, local = node.tag[1:].split('}', 1)
        if ns in W_NAMESPACES:
            return local
    return ''


def local(node):
    return node.tag.rsplit('}', 1)[-1]


def attr(node, name):
    return next((node.get('{%s}%s' % (ns, name)) for ns in W_NAMESPACES
                 if node.get('{%s}%s' % (ns, name)) is not None), None)


def parse_xml(raw, name):
    # Expat recognizes declarations even in UTF-16; never resolve external entities.
    parser = expat.ParserCreate()
    def reject(*args):
        raise ValueError('XML 含 DTD 或实体声明，拒绝读取：' + name)
    parser.StartDoctypeDeclHandler = reject
    parser.EntityDeclHandler = reject
    parser.ExternalEntityRefHandler = reject
    try:
        parser.Parse(raw, True)
        return ET.fromstring(raw)
    except (expat.ExpatError, ET.ParseError) as exc:
        raise ValueError('XML 无法解析：' + name + '；' + str(exc))


CATEGORIES = {
    'tables': ({'tbl'}, '正文表格按 XML 顺序展平为带表、行、格坐标的段落；其他部件未提取'),
    'revisions': ({'ins', 'del', 'moveFrom', 'moveTo', 'pPrChange', 'rPrChange', 'tblPrChange', 'trPrChange', 'tcPrChange', 'sectPrChange', 'cellIns', 'cellDel', 'cellMerge'}, '仅采用文字级最终视图；包含 ins/moveTo，排除 del/moveFrom；结构/格式修订未还原'),
    'textboxes': ({'txbxContent'}, '未提取、未检查'),
    'footnotes': ({'footnote', 'footnoteReference'}, '未提取、未检查；计数包括注释定义及引用'),
    'endnotes': ({'endnote', 'endnoteReference'}, '未提取、未检查；计数包括注释定义及引用'),
    'headers': ({'hdr', 'headerReference'}, '未提取、未检查；计数包括部件根及引用'),
    'footers': ({'ftr', 'footerReference'}, '未提取、未检查；计数包括部件根及引用'),
    'comments': ({'comment', 'commentReference', 'commentRangeStart', 'commentRangeEnd'}, '未提取、未检查；定义及标记分别计数'),
    'drawings_images': ({'drawing', 'pict'}, '未提取、未检查；按绘图容器计数，不等于图片数量'),
    'embedded_objects': ({'object'}, '未提取、未检查；按对象容器计数'),
    'fields': ({'fldChar', 'fldSimple', 'instrText'}, '不计算字段；普通缓存结果文字可能保留，不保证最新'),
    'altchunks': ({'altChunk'}, '未提取、未检查'),
    'symbols': ({'sym'}, '字体映射符号未提取、未检查'),
    'ruby': ({'ruby'}, '只提取 rubyBase 正文；注音未提取、未检查'),
    'ruby_annotations': ({'rt'}, '注音未提取、未检查；按 rt 容器计数'),
    'math': (set(), '公式未提取、未检查'),
    'alternate_content': (set(), '兼容分支全部跳过，未提取、未检查'),
    'external_relationships': (set(), '仅清点关系声明；不打开目标、不访问网络'),
}


def inventory(roots):
    result = {key: {'count': 0, 'parts': [], 'handling': desc}
              for key, (_, desc) in CATEGORIES.items()}
    for name, root in roots.items():
        for node in root.iter():
            keys = [key for key, (tags, _) in CATEGORIES.items() if word(node) in tags]
            if local(node) == 'AlternateContent':
                keys.append('alternate_content')
            if local(node) in ('oMath', 'oMathPara'):
                keys.append('math')
            if local(node) == 'Relationship' and node.get('TargetMode') == 'External':
                keys.append('external_relationships')
            for key in keys:
                result[key]['count'] += 1
                if name not in result[key]['parts']:
                    result[key]['parts'].append(name)
    return result


SKIP = {'del', 'moveFrom', 'txbxContent', 'drawing', 'pict', 'object', 'altChunk',
        'pPr', 'rPr', 'tblPr', 'trPr', 'tcPr', 'sectPr'}


def skipped(node):
    return word(node) in SKIP or local(node) in ('AlternateContent', 'oMath', 'oMathPara')


def paragraph_text(node):
    if skipped(node):
        return ''
    tag = word(node)
    if tag == 't':
        return node.text or ''
    if tag == 'ruby':
        return ''.join(paragraph_text(child) for child in node if word(child) == 'rubyBase')
    if tag == 'rt':
        return ''
    if tag in ('tab', 'ptab'):
        return '\t'
    if tag in ('br', 'cr'):
        return '\n'
    if tag == 'noBreakHyphen':
        return '\u2011'
    if tag == 'softHyphen':
        return '\u00ad'
    return ''.join(paragraph_text(child) for child in node)


def extract(path, title='材料校对', max_chars=1800, check_suffix=True):
    path = Path(path)
    report.require(not check_suffix or path.suffix.lower() == '.docx', '仅支持 .docx；不支持 DOC、DOCM、PDF 或加密文档')
    report.require(max_chars > 0, 'max-unit-chars 必须大于 0')
    report.require(path.stat().st_size <= MAX_PACKAGE, 'DOCX 超过 128 MiB 读取上限')
    record = provenance.snapshot(path)
    raw = path.read_bytes()
    report.require(hashlib.sha256(raw).hexdigest() == record['source_sha256'], '读取期间源文件发生变化')
    report.require(not raw.startswith(bytes.fromhex('d0cf11e0a1b11ae1')), '不是可读取 DOCX ZIP：可能为加密文档或旧版 DOC')
    roots = {}
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            report.require(len(entries) <= 10000, 'DOCX 部件过多')
            report.require(len({i.filename for i in entries}) == len(entries), 'DOCX 存在重复部件名')
            report.require(not any(i.flag_bits & 1 for i in entries), '不支持加密 DOCX ZIP 部件')
            xml_entries = [i for i in entries if i.filename.endswith(('.xml', '.rels'))]
            report.require(sum(i.file_size for i in xml_entries) <= MAX_XML, 'DOCX XML 超过 64 MiB 解压上限')
            for info in xml_entries:
                roots[info.filename] = parse_xml(archive.read(info), info.filename)
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
        raise ValueError('不是可读取 DOCX ZIP：' + str(exc))
    types = roots.get('[Content_Types].xml')
    report.require(types is not None and any(n.get('PartName') == '/word/document.xml' and
                   n.get('ContentType') == 'application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml'
                   for n in types), '不是受支持的 DOCX 正文包（需 word/document.xml 内容类型）')
    root = roots.get('word/document.xml')
    report.require(root is not None and word(root) == 'document', 'DOCX 缺少有效正文 document')
    body = next((n for n in root if word(n) == 'body'), None)
    report.require(body is not None, 'DOCX 缺少正文 body')
    counts = inventory(roots)
    blocks = []
    counter = {'p': 0, 'tbl': 0}

    def walk(node, location='正文'):
        if skipped(node):
            return
        tag = word(node)
        if tag == 'p':
            counter['p'] += 1
            text = paragraph_text(node)
            if not text.strip():
                return
            props = next((c for c in node if word(c) == 'pPr'), None)
            heading = props is not None and any(
                (word(c) == 'outlineLvl' and attr(c, 'val') in tuple(str(i) for i in range(9))) or
                (word(c) == 'pStyle' and (attr(c, 'val') or '').lower().startswith(('heading', '标题')))
                for c in props)
            pieces = report.split_text_unit(text, max_chars)
            for index, piece in enumerate(pieces, 1):
                label = location + '／段落' + str(counter['p'])
                if len(pieces) > 1:
                    label += '（分片{}/{}）'.format(index, len(pieces))
                blocks.append({'id': 'p' + str(len(blocks) + 1), 'kind': 'heading' if heading else 'paragraph',
                               'text': piece, 'location': label})
            return
        if tag == 'tbl':
            counter['tbl'] += 1
            location += '／表' + str(counter['tbl'])
        # Child indices are physical XML indices within each parent, not visual page coordinates.
        row, cell = 0, 0
        for child in node:
            child_location = location
            if word(child) == 'tr':
                row += 1
                child_location += '／行' + str(row)
            if word(child) == 'tc':
                cell += 1
                child_location += '／格' + str(cell)
            walk(child, child_location)

    walk(body)
    limitations = [
        '仅检查实际提取后的正文和表格文字，不代表整份 DOCX 或完整 Office 兼容；不恢复分页、浮动布局、合并单元格外观或阅读顺序。',
        '默认文字级最终修订视图：包含插入及移入，排除删除及移出；格式和表格结构修订、隐藏文字、样式继承未完整解释，隐藏文字可能包含。',
        '文本框、脚注尾注、页眉页脚、批注、绘图图片、对象、公式、字体符号、altChunk 和兼容分支不在检查范围；字段仅可能保留缓存结果，不计算或更新。',
        '清点针对包内实际解析的 XML 元素，含未引用或删除区域；次数不是可见对象数，零次不证明不存在所有扩展形式。',
    ]
    for key, entry in counts.items():
        if entry['count']:
            limitations.append('{}：识别 {} 个相关 XML 元素；{}'.format(key, entry['count'], entry['handling']))
    doc = {'title': title, 'source_name': path.name,
           'scope': 'word/document.xml 正文及嵌套表格中可读取段落的文字级最终修订视图；按 XML 顺序，超长段落无损分片；其他结构仅清点、未检查',
           'limitations': limitations, 'extraction_inventory': counts,
           'extraction_xml_parts': sorted(roots), 'source_sha256': record['source_sha256'], 'blocks': blocks}
    report.require(bool(blocks), 'DOCX 正文未读取到可检查文字（可能仅包含未支持的结构）')
    report.document_units(doc)
    return provenance.bind(doc, record, 'extract_docx.py；标准库 OOXML 正文/表格有限提取；文字级最终修订视图')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--title', default='材料校对')
    parser.add_argument('--max-unit-chars', type=int, default=1800)
    parser.add_argument('--overwrite', action='store_true')
    args = parser.parse_args()
    try:
        target = Path(args.output).resolve()
        skill_root = Path(__file__).resolve().parent.parent
        report.require(target != skill_root and skill_root not in target.parents,
                       '输出不能写入技能包目录，请使用任务输出目录')
        doc = extract(args.input, args.title, args.max_unit_chars)
        output = report.write_output(args.output, json.dumps(doc, ensure_ascii=False, indent=2) + '\n', args.overwrite, [args.input])
        print('DOCX 有限范围提取完成：' + str(output) + '；请阅读 scope、limitations 和 extraction_inventory。')
    except (ValueError, OSError, UnicodeError, LookupError, RecursionError) as exc:
        print('错误：' + str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
