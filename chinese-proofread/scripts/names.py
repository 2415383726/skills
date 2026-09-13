#!/usr/bin/env python3
"""Compact name index and budgeted tasks preserving all name-pair comparisons."""
from itertools import combinations
import json


def index(units, terms):
    names = {}
    for term in terms:
        text = term['text']
        item = names.setdefault(text, {'text': text, 'kind': '名称', 'occurrences': []})
        unit = units[term['block_id']]
        position, number = 0, 0
        while True:
            position = unit['text'].find(text, position)
            if position < 0:
                break
            number += 1
            occurrence = {'block_id': term['block_id'], 'occurrence': number}
            if occurrence not in item['occurrences']:
                item['occurrences'].append(occurrence)
            position += 1
    return [names[key] for key in sorted(names)]


def blocks(units, terms):
    wanted = {o['block_id'] for term in terms for o in term['occurrences']}
    return [dict(id=bid, text=unit['text'], location=unit['location'])
            for bid, unit in units.items() if bid in wanted]


def plan(source, budget):
    """Each pair is co-visible at least once, or explicitly marked over budget.

    Names are never partitioned by guessed kind or lexical similarity. Context
    is stored once per block per task. No source text is truncated.
    """
    terms = source['terms']
    def payload(indices):
        chosen = [terms[i] for i in sorted(indices)]
        wanted = {o['block_id'] for t in chosen for o in t['occurrences']}
        return {**{k: v for k, v in source.items() if k not in ('terms', 'blocks', 'budget_exceeded')},
                'terms': chosen, 'blocks': [b for b in source['blocks'] if b['id'] in wanted],
                'max_input_chars': budget}
    def fits(indices):
        return len(json.dumps(payload(indices), ensure_ascii=False, indent=2)) <= budget
    if not terms:
        return []
    if fits(set(range(len(terms)))):
        return [payload(set(range(len(terms))))]
    packs, current = [], set()
    pairs = combinations(range(len(terms)), 2) if len(terms) > 1 else [(0,)]
    for pair in pairs:
        pair = set(pair)
        if pair <= current:
            continue
        combined = current | pair
        if current and not fits(combined):
            packs.append(payload(current))
            current = set()
        current |= pair
        if not fits(current):
            packs.append(payload(current))
            current = set()
    if current:
        packs.append(payload(current))
    return packs


def coverage(expected, executions):
    completed = {pid: sorted({e['batch_id'] for e in executions if e['pass_id'] == pid and e['complete']}) for pid in ('A', 'B')}
    collected = sorted(set(completed['A']) | set(completed['B']))
    missing = [bid for bid in expected if bid not in collected]
    notes = ['名称采集覆盖 {}/{} 批（至少一路完整提交）；名称由模型采集，不保证收齐所有专名。'.format(len(collected), len(expected))]
    if not expected:
        notes.append('原任务没有可用的预期批次记录，名称采集覆盖度未知。')
    for pid in ('A', 'B'):
        absent = [bid for bid in expected if bid not in completed[pid]]
        if absent:
            notes.append(pid + '路名称采集未完整提交：' + '、'.join(absent))
    if missing:
        notes.append('名称采集缺批（两路均未完整提交）：' + '、'.join(missing))
    return {'expected_batches': len(expected), 'collected_batches': len(collected), 'missing_batches': missing,
            'complete_by_pass': completed}, notes
