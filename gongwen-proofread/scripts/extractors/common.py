import io
import posixpath
import zipfile
from pathlib import Path

import extract_docx
import report

SKILL = Path(__file__).resolve().parents[2]
MAX_FILE = 128 * 1024 * 1024


def package_xml(raw):
    roots = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        report.require(len(entries) <= 10000, '文件包部件过多')
        report.require(len({i.filename for i in entries}) == len(entries), '文件包包含重复部件')
        report.require(not any(i.flag_bits & 1 for i in entries), '文件包已加密')
        xml = [i for i in entries if i.filename.endswith(('.xml', '.rels'))]
        report.require(sum(i.file_size for i in xml) <= 64 * 1024 * 1024, 'XML 超过提取容量限制')
        for item in xml:
            roots[item.filename] = extract_docx.parse_xml(archive.read(item), item.filename)
    return roots


def local(node):
    return node.tag.rsplit('}', 1)[-1]


def relations(roots, part):
    folder, filename = posixpath.split(part)
    root = roots.get(posixpath.join(folder, '_rels', filename + '.rels'))
    result = {}
    if root is not None:
        for rel in root:
            if rel.get('TargetMode') == 'External':
                continue
            target = rel.get('Target', '')
            resolved = posixpath.normpath(target.lstrip('/') if target.startswith('/') else posixpath.join(folder, target))
            report.require(not resolved.startswith('../'), '部件关系越出文件包')
            result[rel.get('Id')] = (resolved, rel.get('Type', '').rsplit('/', 1)[-1])
    return result


def relation_id(node):
    return next((v for k, v in node.attrib.items() if k.endswith('}id')), None)


def paragraph(blocks, text, location, max_chars=1800, kind='paragraph'):
    if not text or not text.strip():
        return
    pieces = report.split_text_unit(text, max_chars)
    for i, piece in enumerate(pieces, 1):
        blocks.append({'id': 'p' + str(len(blocks) + 1), 'kind': kind, 'text': piece,
                       'location': location + ('（分片%d/%d）' % (i, len(pieces)) if len(pieces) > 1 else '')})
