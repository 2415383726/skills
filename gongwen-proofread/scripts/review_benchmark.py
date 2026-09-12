#!/usr/bin/env python3
"""Isolated offline review challenge. Never calls models or labels predictions."""
import argparse
import json
from pathlib import Path
import sys

import evaluate
import report
import workflow as wf

SKILL = Path(__file__).resolve().parents[1]


def prepare(work, show_reasons=False):
    seed_path = SKILL / 'assets' / 'review-challenge.json'
    seed = report.load_json(seed_path)
    evaluate.prepare(seed_path, work)
    work = Path(work).resolve()
    document = report.load_json(work / 'document.json')
    units = report.document_units(document)
    candidates = []
    for index, case in enumerate(seed['cases'], 1):
        proposal = case['proposal']
        raw = dict(id='c' + str(index), severity='confirmed', rule_id=proposal['rule_id'],
                   category=evaluate.category(proposal), reason=proposal['reason'],
                   anchors=[dict(block_id='p{:03d}'.format(index), quote=proposal['quote'])],
                   suggestion=proposal['suggestion'])
        value, positions = wf.validate_candidate(units, raw, 'challenge')
        candidates.append(dict(value, positions=positions))
    candidates = wf.merge_candidates(candidates, units)
    for candidate in candidates:
        candidate['requires_necessity'] = wf.needs_necessity(candidate)
    groups = wf.candidate_groups(document, candidates)
    visible = wf.review_view(groups)
    if show_reasons:
        for source, target in zip(groups, visible):
            for original, candidate in zip(source['candidates'], target['candidates']):
                candidate['reason'] = original['reason']
    payload = dict(schema_version=wf.SCHEMA, task='review-challenge', document_sha256=wf.sha(document),
                   context_units=wf.ordered_units(document), candidate_groups=visible,
                   instructions='各单元是独立合成情境，不将邻段推断为共同事件。按规则判断提案，允许保留或推翻；不要读取其他文件或标准答案。')
    wf.dump(work / 'challenge-input.json', payload)
    wf.dump(work / 'challenge-binding.json', dict(document_sha256=wf.sha(document),
        input_sha256=wf.sha(payload), rules_sha256=wf.rules_sha(), initial_reasons_visible=show_reasons))
    return dict(input_path=str(work / 'challenge-input.json'), body_path=str(work / 'challenge-decisions.json'),
                rules_path=str(SKILL / 'references/rules.md'), format_path=str(SKILL / 'references/formats/review.md'),
                instructions='这是独立复核测评，不是生产队列。使用全新上下文，只读上述输入、规则、格式；按 group_decisions 格式写 body_path 后结束，不运行 open/submit，不查看 gold 或种子。')


def score(work, body_path):
    work = Path(work).resolve()
    document = report.load_json(work / 'document.json')
    payload = report.load_json(work / 'challenge-input.json')
    binding = report.load_json(work / 'challenge-binding.json')
    report.require(binding.get('document_sha256') == payload.get('document_sha256') == wf.sha(document), '挑战文档版本不匹配')
    report.require(binding.get('input_sha256') == wf.sha(payload), '挑战输入发生变化')
    report.require(binding.get('rules_sha256') == wf.rules_sha(), '挑战使用的判定规则已变化')
    body = report.load_json(body_path)
    findings, notes = wf.review_decisions(document, payload, body)
    report.require(not notes, '复核决定未收齐：' + '；'.join(notes))
    gold = report.load_json(work / 'gold.json')
    final = dict(document_sha256=wf.sha(document), findings=findings)
    result = evaluate.evaluate(document, final, gold)
    proposals = [dict(c, reviewed=True) for g in payload['candidate_groups'] for c in g['candidates']]
    baseline = evaluate.evaluate(document, dict(document_sha256=wf.sha(document), findings=proposals), gold)
    units = report.document_units(document)
    before = {evaluate.effect(units, c['anchors'][0], c['suggestion']) for c in proposals}
    after = {evaluate.effect(units, c['anchors'][0], c['suggestion']) for c in findings if c['severity'] == 'confirmed'}
    expected = set()
    for case in gold['cases']:
        for edit in ([] if case['expected'] == 'no-change' else case['expected']):
            expected.add(evaluate.effect(units, dict(edit['anchor'], block_id=case['block_id']), edit['suggestion']))
    result['challenge'] = dict(initial_reasons_visible=binding['initial_reasons_visible'],
        proposed=baseline['overall'], false_proposals_removed=len((before-after)-expected),
        correct_proposals_removed=len((before-after)&expected),
        new_correct_effects=len((after-before)&expected), new_incorrect_effects=len((after-before)-expected),
        interpretation='仅测本组提案的复核保留/剔除；不是初检召回率。removed 指未作为相同 confirmed 修改交付，含降为 pending 或改写。预期仍需人工审定。')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prep = commands.add_parser('prepare')
    prep.add_argument('--work', required=True)
    prep.add_argument('--show-initial-reasons', action='store_true', help='仅作理由可见的对照实验')
    scoring = commands.add_parser('score')
    scoring.add_argument('--work', required=True)
    scoring.add_argument('--body', required=True)
    scoring.add_argument('--output')
    args = parser.parse_args()
    try:
        value = prepare(args.work, args.show_initial_reasons) if args.command == 'prepare' else score(args.work, args.body)
        text = json.dumps(value, ensure_ascii=False, indent=2) + '\n'
        if getattr(args, 'output', None):
            root = Path(args.work)
            report.write_output(args.output, text, False, [args.body, root/'document.json', root/'gold.json',
                                                         root/'challenge-input.json', root/'challenge-binding.json'])
        else:
            print(text, end='')
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print('错误：' + str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
