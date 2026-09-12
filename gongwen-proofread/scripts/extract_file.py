#!/usr/bin/env python3
"""One offline extraction entry point, with an explicit host-tool handoff."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import sys
import uuid
import zipfile

import extract_docx
import provenance
import report
from extractors.common import SKILL, MAX_FILE, package_xml, paragraph

TEXT_EXTENSIONS = {'.txt', '.text', '.md', '.markdown'}
# Package names are installation hints, not runtime version constraints.
DEPENDENCIES = {'xlrd': 'xlrd'}


def detect(raw, suffix):
    if raw.startswith(b'PK'):
        roots = package_xml(raw)
        types = roots.get('[Content_Types].xml')
        report.require(types is not None, 'ZIP 文件不是可识别的 Office 文档')
        mapping = {
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml': 'docx',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml': 'xlsx',
            'application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml': 'pptx',
        }
        found = {mapping[n.get('ContentType')] for n in types if n.get('ContentType') in mapping}
        report.require(len(found) == 1, '不是当前内置解析器支持的 Office 主文档类型')
        return found.pop(), roots
    if raw.startswith(bytes.fromhex('d0cf11e0a1b11ae1')):
        if suffix in ('.xls', '.et'):
            # xlrd verifies the actual workbook structure; the suffix alone
            # never establishes success. Other compound formats go to the host.
            return 'xls', None
        raise ValueError('旧版二进制或加密办公文件需使用宿主读取工具')
    if suffix in TEXT_EXTENSIONS:
        return ('markdown' if suffix in ('.md', '.markdown') else 'text'), None
    if suffix == '.xls':
        # xlrd also supports early, non-compound BIFF files; it validates them.
        return 'xls', None
    raise ValueError('当前内置提取器不支持此格式（包括未识别的 WPS 原生格式）')


def decode_text(raw, encoding=None):
    if encoding:
        return raw.decode(encoding), encoding
    if raw.startswith((b'\xff\xfe\x00\x00', b'\x00\x00\xfe\xff')):
        return raw.decode('utf-32'), 'utf-32'
    if raw.startswith((b'\xff\xfe', b'\xfe\xff')):
        return raw.decode('utf-16'), 'utf-16'
    try:
        return raw.decode('utf-8-sig'), 'utf-8-sig'
    except UnicodeDecodeError as exc:
        raise ValueError('文本不是 UTF-8 或带 BOM 的 Unicode 编码；可指定 --encoding gb18030 等实际编码') from exc


def text_blocks(raw, max_chars, encoding=None):
    text, actual_encoding = decode_text(raw, encoding)
    report.require('\0' not in text, '文本包含 NUL，可能是二进制或编码不匹配')
    blocks = []
    for index, line in enumerate(re.split(r'\r\n|\r|\n', text), 1):
        paragraph(blocks, line, '提取文本第%d行' % index, max_chars)
    return blocks, actual_encoding


def validate_output(target, source, overwrite):
    target = Path(target).resolve()
    report.require(target != SKILL and SKILL not in target.parents, '输出目录不能位于技能包内')
    report.require(target != Path(source).resolve(), '输出不能覆盖源文件')
    if target.exists():
        report.require(not os.path.samefile(str(target), str(source)), '输出与源文件指向同一文件')
    report.require(overwrite or not target.exists(), '输出已存在；请换工作目录或明确使用 --overwrite')
    return target


def write_document(document, target, record, method, overwrite=False, extra_inputs=()):
    report.document_units(document)
    document = provenance.bind(document, record, method)
    inputs = [record['source_path'], *map(str, extra_inputs)]
    report.write_output(str(target), json.dumps(document, ensure_ascii=False, indent=2) + '\n', overwrite, inputs)
    units = report.document_units(document)
    chars = sum(len(u['text']) for u in units.values())
    return {'action': 'ready', 'document_path': str(target), 'characters': chars,
            'suggested_delivery': 'chat' if chars <= 500 and not any(b['kind'] == 'table' for b in document['blocks']) else 'html'}


def command_string(argv):
    if os.name == 'nt':
        return '& ' + ' '.join("'" + arg.replace("'", "''") + "'" for arg in argv)
    return ' '.join(shlex.quote(arg) for arg in argv)


def handoff(record, target, title, max_chars, reason, overwrite):
    provenance.check_snapshot(record)
    token = uuid.uuid4().hex[:12]
    request_path = target.with_name(target.stem + '.extract-' + token + '.json')
    host_path = target.with_name(target.stem + '.host-' + token + '.txt')
    request = {'schema': 'gongwen-extraction-request/1', 'source_record': record,
               'output_path': str(target), 'host_output_path': str(host_path), 'title': title,
               'max_chars': max_chars, 'reason': reason, 'overwrite': overwrite}
    report.write_output(str(request_path), json.dumps(request, ensure_ascii=False, indent=2), False, [record['source_path']])
    resume = command_string([sys.executable, str(Path(__file__).resolve()), '--resume', str(request_path)])
    instruction = ('请用宿主已有文件读取工具读取“{}”，将完整原文以 UTF-8 写入“{}”，'
                   '保留段落、工作表和幻灯片分隔，不总结、不校对；写入成功后执行：{}。'
                   '若宿主也无法读取，向用户说明原因并请求可读取的转换件，不重复尝试本入口。').format(record['source_path'], host_path, resume)
    return {'action': 'host_extract', 'reason': reason, 'instruction': instruction,
            'source_path': record['source_path'], 'host_output_path': str(host_path),
            'request_path': str(request_path), 'resume_command': resume}


def retry_arguments(args):
    command = [sys.executable, str(Path(__file__).resolve()), '--input', str(Path(args.input).resolve()),
               '--output', str(Path(args.output).resolve()), '--max-unit-chars', str(args.max_unit_chars)]
    for name in ('title', 'encoding'):
        if getattr(args, name):
            command.extend(['--' + name, getattr(args, name)])
    if args.overwrite:
        command.append('--overwrite')
    return command


def office_text(kind, raw, roots, max_chars):
    """At most one library attempt and one existing stdlib fallback."""
    from extractors import libraries, sheets, presentation
    try:
        result = getattr(libraries, kind)(raw, roots, max_chars)
        report.require(bool(result[0]), '库未返回可检查文字')
        return result, kind + ' library', []
    except Exception as exc:
        # The error is retained as technical metadata, not passed off as a
        # successful library extraction. The fallback has its own scope.
        attempt = {'backend': kind + ' library', 'error': type(exc).__name__ + ': ' + str(exc)}
        result = (sheets.extract_xlsx(raw, roots, max_chars) if kind == 'xlsx'
                  else presentation.extract(raw, roots, max_chars))
        return result, kind + ' stdlib', [attempt]


def missing_dependency(exc, args):
    module = (exc.name or '').split('.')[0]
    requirement = DEPENDENCIES.get(module)
    if requirement is None:
        raise exc
    retry = retry_arguments(args)
    return {'action': 'install_dependency', 'missing_module': module, 'requirement': requirement,
            'python': sys.executable, 'retry_command': command_string(retry),
            'fallback_command': command_string(retry + ['--host-fallback']),
            'instruction': '缺少依赖 {}。请主 Agent 使用内网包源或离线安装包为当前 Python 选择兼容版本安装后重试；不要强制升级或降级已有库；'
                           '无法安装或安装后仍失败时，执行 fallback_command 转交宿主读取工具。脚本不自行安装或联网。'.format(requirement)}


def extract_file(args):
    source = Path(args.input).resolve()
    report.require(source.is_file(), '输入路径不是本地文件')
    target = validate_output(args.output, source, args.overwrite)
    report.require(args.max_unit_chars > 0, 'max-unit-chars 必须为正整数')
    record = provenance.snapshot(source)
    title = args.title or source.stem
    if args.host_fallback:
        return handoff(record, target, title, args.max_unit_chars, '主 Agent 选择使用宿主文件读取工具', args.overwrite)
    try:
        report.require(source.stat().st_size <= MAX_FILE, '文件超过 128 MiB 内置提取上限')
        raw = source.read_bytes()
        report.require(hashlib.sha256(raw).hexdigest() == record['source_sha256'], '提取期间源文件发生变化')
        kind, roots = detect(raw, source.suffix.lower())
        backend, attempts = kind, []
        if kind == 'docx':
            document = extract_docx.extract(source, title, args.max_unit_chars, check_suffix=False)
        else:
            if kind in ('text', 'markdown'):
                blocks, encoding = text_blocks(raw, args.max_unit_chars, args.encoding)
                notes = []
                scope = '全部非空原始行；保留 Markdown/文本语法；编码 ' + encoding
            elif kind == 'xls':
                from extractors import sheets
                blocks, notes, scope = sheets.extract_xls(raw, args.max_unit_chars)
            elif kind in ('xlsx', 'pptx'):
                (blocks, notes, scope), backend, attempts = office_text(kind, raw, roots, args.max_unit_chars)
            else:
                raise ValueError(kind.upper() + ' 旧版格式需使用宿主读取工具')
            document = {'title': title, 'source_name': source.name, 'scope': scope,
                        'limitations': notes, 'blocks': blocks}
        document['extraction_backend'] = backend
        document['extraction_attempts'] = attempts
        report.document_units(document)
        provenance.check_snapshot(record)
    except ModuleNotFoundError as exc:
        if (exc.name or '').split('.')[0] in DEPENDENCIES:
            return missing_dependency(exc, args)
        return handoff(record, target, title, args.max_unit_chars, str(exc), args.overwrite)
    except Exception as exc:
        # Extraction is optional. Only this boundary converts parser failures to
        # an explicit handoff. Source/output/resume errors remain blocked.
        return handoff(record, target, title, args.max_unit_chars,
                       type(exc).__name__ + ': ' + str(exc), args.overwrite)
    result = write_document(document, target, record, 'extract_file.py；' + backend + ' 提取器', args.overwrite)
    result['detected_format'] = kind
    return result


def resume(args):
    request_path = Path(args.resume).resolve()
    request = report.load_json(request_path)
    report.require(request.get('schema') == 'gongwen-extraction-request/1', '不是本入口生成的提取请求')
    record = request['source_record']
    provenance.check_snapshot(record)
    target = validate_output(request['output_path'], record['source_path'], request['overwrite'])
    host_path = Path(args.host_document or request['host_output_path']).resolve()
    report.require(host_path.is_file(), '宿主提取结果尚未写入：' + str(host_path))
    report.require(host_path.stat().st_size <= MAX_FILE, '宿主提取结果超过处理上限')
    if args.host_document:
        document = report.load_json(host_path)
        report.document_units(document)
        document['title'] = request['title']
        document['source_name'] = Path(record['source_path']).name
        document.pop('provenance', None)
    else:
        blocks, _ = text_blocks(host_path.read_bytes(), request['max_chars'], 'utf-8-sig')
        document = {'title': request['title'], 'source_name': Path(record['source_path']).name,
                    'scope': args.scope or '宿主读取工具返回的文本；原文件覆盖范围未提供',
                    'limitations': [] if args.scope else ['宿主提取未提供原文件覆盖范围。'], 'blocks': blocks}
    if args.scope:
        document['scope'] = args.scope
    return write_document(document, target, record, '宿主工具辅助提取，经 extract_file.py --resume 接收；输出 ' + host_path.name,
                          request['overwrite'], [host_path, request_path])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument('--input')
    selection.add_argument('--resume')
    parser.add_argument('--output')
    parser.add_argument('--title')
    parser.add_argument('--encoding')
    parser.add_argument('--max-unit-chars', type=int, default=1800)
    parser.add_argument('--overwrite', action='store_true')
    parser.add_argument('--host-fallback', action='store_true', help='跳过内置提取，生成宿主工具接手指令')
    parser.add_argument('--host-document', help='恢复时可改用带位置和范围的 document.json')
    parser.add_argument('--scope', help='宿主实际返回的内容范围，不要声明未读取区域')
    args = parser.parse_args()
    try:
        report.require(bool(args.resume) or bool(args.output), '--input 必须同时指定 --output')
        result = resume(args) if args.resume else extract_file(args)
    except Exception as exc:
        result = {'action': 'blocked', 'reason': str(exc),
                  'instruction': '修正上述来源、输出或宿主结果问题后重试；未生成 document.json 时不启动校对。'}
        print(json.dumps(result, ensure_ascii=True))
        return 2
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
