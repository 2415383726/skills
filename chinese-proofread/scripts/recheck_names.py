#!/usr/bin/env python3
"""Prepare a separate names-only supplement from a completed, fingerprinted run."""
import argparse
from pathlib import Path
import sys

import names
import policy
import provenance
import report
import tasks
import workflow as wf


def prepare(source, work, coordinator, budget):
    source, work = Path(source).resolve(), Path(work).resolve()
    report.require(work != tasks.SKILL and tasks.SKILL not in work.parents, '工作目录不能位于技能包内')
    report.require(work != source and source not in work.parents, '补查目录必须独立于原工作目录')
    report.require(not work.exists(), '补查目录已存在，请指定新的独立目录')
    report.string(coordinator, 'coordinator')
    report.require(budget > 0, '输入预算必须为正整数')
    # This is reuse of collected source spellings, never reuse of old judgments.
    with tasks.coordinator_lock(source):
        state = wf.load(source / 'task-state.json')
        report.require(state.get('report_sha256') and all(j['status'] in ('complete', 'skipped') for j in state['jobs'].values()),
                       '先完成原任务；不从仍在运行的队列创建补查')
        document = wf.load(source / 'document.json')
        provenance.verify(document)
        report.require(wf.sha(document) == state['document_sha256'], '原文指纹变化')
        old = wf.load(source / 'merged.json')
        index = wf.load(source / 'consistency-input.json')
        report.require(wf.sha(old) == state['merged'] and wf.sha(index) == state['consistency_input'], '原名称采集数据指纹变化')
        report.require(index['document_sha256'] == wf.sha(document) and index['merged_sha256'] == wf.sha(old), '原名称索引绑定不匹配')
    units = report.document_units(document)
    raw = []
    for term in index['terms']:
        for occurrence in term['occurrences']:
            bid = occurrence['block_id']
            report.require(bid in units and term['text'] in units[bid]['text'], '旧索引名称不在原文中')
            raw.append({'text': term['text'], 'kind': '名称', 'block_id': bid})
    compact = names.index(units, raw)
    coverage, coverage_notes = names.coverage(old.get('expected_batch_ids', []), old.get('executions', []))
    note = '这是独立名称补查报告，仅复用原任务的名称采集数据；不重做文字初检，不包含原报告的其他修改。'
    work.mkdir(parents=True)
    tasks.save(work / 'document.json', document)
    tasks.invoke(wf.batch_command, document=str(work / 'document.json'), output_dir=str(work / 'batches'),
                 target_chars=1600, max_chars=2000, context_units=1)
    manifest = wf.load(work / 'batches' / 'manifest.json')
    merged = {'schema_version': wf.SCHEMA, 'task': 'merged-candidates', 'document_sha256': wf.sha(document),
              'rules_sha256': wf.rules_sha(), 'consistency_required': True, 'names_only': True,
              'executions': [], 'expected_batch_ids': [], 'passes': [{'id': p, 'checked_block_ids': []} for p in ('A', 'B')],
              'limitations': [note] + coverage_notes, 'candidates': []}
    packet = {'schema_version': wf.SCHEMA, 'task': 'consistency-input', 'document_sha256': wf.sha(document),
              'merged_sha256': wf.sha(merged), 'required': True, 'title': document['title'], 'source_name': document['source_name'],
              'terms': compact, 'blocks': names.blocks(units, compact), 'coverage': coverage,
              'coverage_notes': coverage_notes, 'max_input_chars': budget,
              'instructions': '只检查名称指代差异，不做全文文字重查。'}
    tasks.save(work / 'merged.json', merged)
    tasks.save(work / 'consistency-input.json', packet)
    fresh = {'document_sha256': wf.sha(document), 'rules_sha256': wf.rules_sha(), 'jobs': {}, 'concurrency': 8,
             'target_chars': 1600, 'max_chars': 2000, 'manifest_sha256': wf.sha(manifest),
             'merged': wf.sha(merged), 'consistency_input': wf.sha(packet), 'consistency_budget': budget,
             'names_only': True, 'reused_from': str(source)}
    tasks.claim_coordinator(work, fresh, coordinator)
    tasks.save(work / 'task-state.json', fresh)
    return {'work': str(work), 'coordinator': coordinator, 'instruction': '在此补查目录执行 tasks.py step；只派发名称检查和候选复核，交付独立补查报告。'}


def main():
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-work', required=True)
    parser.add_argument('--work', required=True)
    parser.add_argument('--coordinator', required=True)
    parser.add_argument('--max-input-chars', type=int, default=policy.CONSISTENCY_INPUT_CHARS)
    args = parser.parse_args()
    try:
        print(json.dumps(prepare(args.source_work, args.work, args.coordinator, args.max_input_chars), ensure_ascii=False))
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print('错误：' + str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
