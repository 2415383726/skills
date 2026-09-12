#!/usr/bin/env python3
"""Bind extracted text to a pre-extraction local source snapshot. No network."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()


def content_digest(document):
    return digest({k: v for k, v in document.items() if k != 'provenance'})


def file_digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def snapshot(path):
    source = Path(path).resolve()
    return {'source_path': str(source), 'source_sha256': file_digest(source),
            'captured_at': datetime.now(timezone.utc).isoformat()}


def check_snapshot(value):
    if not isinstance(value, dict) or not all(isinstance(value.get(k), str) and value[k]
                                            for k in ('source_path', 'source_sha256', 'captured_at')):
        raise ValueError('缺少提取前的源文件快照；请从本次源文件重新提取')
    if not Path(value['source_path']).is_absolute():
        raise ValueError('source_path 必须为绝对路径')
    if file_digest(value['source_path']) != value['source_sha256']:
        raise ValueError('源文件已变化，旧提取内容和校对结果不可复用')


def bind(document, source_snapshot, method):
    check_snapshot(source_snapshot)
    if not isinstance(method, str) or not method.strip():
        raise ValueError('必须记录实际提取方式')
    result = {k: v for k, v in document.items() if k != 'provenance'}
    result['provenance'] = dict(source_snapshot, extraction_method=method,
                                extracted_content_sha256=content_digest(result),
                                bound_at=datetime.now(timezone.utc).isoformat())
    return result


def verify(document):
    value = document.get('provenance')
    check_snapshot(value)
    if value.get('extracted_content_sha256') != content_digest(document):
        raise ValueError('提取内容或范围说明已变化，请重新绑定并重新检查')
    if not isinstance(value.get('extraction_method'), str) or not value['extraction_method'].strip():
        raise ValueError('缺少提取方式记录')
    return value


def main():
    import report
    parser = argparse.ArgumentParser(description='提取前记录来源，提取后绑定；哈希不证明提取完整性。')
    commands = parser.add_subparsers(dest='command', required=True)
    begin = commands.add_parser('begin')
    begin.add_argument('--source', required=True)
    begin.add_argument('--output', required=True)
    binding = commands.add_parser('bind')
    binding.add_argument('--document', required=True)
    binding.add_argument('--source-record', required=True)
    binding.add_argument('--method', required=True)
    binding.add_argument('--output', required=True)
    verifying = commands.add_parser('verify')
    verifying.add_argument('--document', required=True)
    args = parser.parse_args()
    try:
        if args.command == 'begin':
            value, inputs = snapshot(args.source), [args.source]
        else:
            document = report.load_json(args.document)
            report.document_units(document)
            if args.command == 'verify':
                verify(document)
                print('来源文件与提取记录匹配；提取完整性仍以声明范围及限制为准。')
                return 0
            value = bind(document, report.load_json(args.source_record), args.method)
            inputs = [args.document, args.source_record, value['provenance']['source_path']]
        report.write_output(args.output, json.dumps(value, ensure_ascii=False, indent=2) + '\n', False, inputs)
        print('记录已生成：' + str(Path(args.output).resolve()))
    except (ValueError, OSError, UnicodeError) as exc:
        print('错误：' + str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
