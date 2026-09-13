#!/usr/bin/env python3
"""Explicit offline evaluation; never runs a model or upgrades annotation status."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
import provenance
import policy
import report
import workflow as wf

CATEGORIES = ('错别字', '多漏字', '标点', '其他')
STATUSES = ('human-reviewed', 'seed-unreviewed')


def category(item):
    rule = item.get('rule_id', '')
    if rule == 'T-TYPO' or rule.startswith('W-'):
        return '错别字'
    if rule in ('T-MISSING', 'T-EXTRA'):
        return '多漏字'
    if rule.startswith('P-'):
        return '标点'
    value = item.get('category')
    return {'标点符号':'标点', '漏字':'多漏字', '多字':'多漏字'}.get(value, value) if value in CATEGORIES + ('标点符号','漏字','多字') else '其他'


def effect(units, anchor, suggestion):
    report.obj(anchor, 'anchor')
    bid = anchor.get('block_id')
    report.require(bid in units, '锚点指向未知文字单元')
    original = units[bid]['text']
    start, end = report.locate(original, anchor, '评分锚点')
    report.string(suggestion, 'suggestion', nonempty=False)
    changed = original[:start] + suggestion + original[end:]
    report.require(changed != original, 'confirmed/expected 必须产生实际修改')
    return bid, changed


def metrics(tp, fp, fn):
    return dict(tp=tp, fp=fp, fn=fn,
                precision=tp / (tp + fp) if tp + fp else None,
                recall=tp / (tp + fn) if tp + fn else None)


def evaluate(document, review, gold, work=None):
    units = report.document_units(document)
    provenance.verify(document)
    fingerprint = provenance.digest(document)
    for label, value in (('review', review), ('gold', gold)):
        report.obj(value, label)
        report.require(value.get('document_sha256') == fingerprint, label + ' 与文档版本不匹配')
    report.require(gold.get('annotation_status') in STATUSES, 'gold.annotation_status 无效')
    cases = gold.get('cases')
    report.require(isinstance(cases, list), 'gold.cases 必须是列表')
    expected, seen, unchanged = {}, set(), set()
    statuses = [gold['annotation_status']]
    for case in cases:
        report.obj(case, 'gold.case')
        bid = case.get('block_id')
        report.require(bid in units and bid not in seen, 'gold 单元缺失、重复或未知')
        seen.add(bid)
        report.require(case.get('text') == units[bid]['text'], 'gold 文本与文档不匹配')
        report.require(case.get('annotation_status') in STATUSES, '每条 gold 必须声明 annotation_status')
        statuses.append(case['annotation_status'])
        edits = case.get('expected')
        if edits == 'no-change':
            edits = []
        report.require(isinstance(edits, list), 'expected 必须为列表或 no-change')
        if not edits:
            unchanged.add(bid)
        for edit in edits:
            report.obj(edit, 'gold.expected')
            report.require(edit.get('category') in CATEGORIES[:3], 'gold category 必须为错别字/多漏字/标点')
            anchor = dict(report.obj(edit.get('anchor'), 'gold.anchor'))
            report.require(anchor.get('block_id', bid) == bid, 'gold 锚点越出 case')
            anchor['block_id'] = bid
            key = effect(units, anchor, edit.get('suggestion'))
            report.require(key not in expected, 'gold 有重复修改效果')
            expected[key] = edit['category']
    report.require(seen == set(units), 'gold 必须完整覆盖文档所有非空文字单元；正确单元使用空 expected')
    findings = review.get('findings')
    report.require(isinstance(findings, list), 'review.findings 必须是列表')
    predictions, pending, duplicates = {}, 0, 0
    for finding in findings:
        report.obj(finding, 'finding')
        report.require(finding.get('reviewed') is True, '只能评估最终复核意见')
        severity = finding.get('severity')
        report.require(severity in ('confirmed', 'pending'), 'severity 无效')
        anchors = finding.get('anchors')
        report.require(isinstance(anchors, list) and anchors, '缺少 anchors')
        for anchor in anchors:
            report.obj(anchor, 'anchor')
            report.require(anchor.get('block_id') in units, '未知锚点单元')
            report.locate(units[anchor['block_id']]['text'], anchor, 'finding')
        if severity == 'pending':
            report.require(finding.get('suggestion') is None, 'pending 不能包含替换')
            pending += 1
            continue
        report.require(len(anchors) == 1, 'confirmed 只能包含一个锚点')
        key = effect(units, anchors[0], finding.get('suggestion'))
        if key in predictions:
            duplicates += 1
        else:
            predictions[key] = category(finding)
    hits = set(expected) & set(predictions)
    false = set(predictions) - set(expected)
    missed = set(expected) - set(predictions)
    by_category = {}
    for name in CATEGORIES:
        by_category[name] = metrics(sum(expected[k] == name for k in hits),
                                    sum(predictions[k] == name for k in false),
                                    sum(expected[k] == name for k in missed))
    status = 'human-reviewed' if all(s == 'human-reviewed' for s in statuses) else 'seed-unreviewed'
    stage_result, phase_timings = stage_metrics(document, review, expected, predictions, pending, work)
    process = process_metrics(work, fingerprint)
    process.update(stage_result['stage_comparisons'])
    process['phase_timings'] = phase_timings
    return dict(stage_result, **{'annotation_status':status,
            'interpretation':'人工审定标注集上的修改效果指标；不代表其他材料表现。' if status == 'human-reviewed' else '仅为未经人工审定的开发基准，不是人工准确率，也不证明模型效果提升。',
            'document_sha256': fingerprint, 'gold_sha256': provenance.digest(gold),
            'overall':metrics(len(hits),len(false),len(missed)), 'by_category':by_category,
            'pending':pending, 'duplicate_confirmed':duplicates,
            'no_change_units':len(unchanged),
            'no_change_false_positives':sum(k[0] in unchanged for k in false),
            'process':process})


# Comparison is by effects on the original unit, never by candidate IDs or votes.
COMPARISONS = ('a_unique_correct', 'b_unique_correct', 'shared_correct',
               'review_removed_correct', 'review_removed_incorrect',
               'review_added_correct', 'review_added_incorrect')


def candidate_effects(units, candidates):
    predictions = {}
    pending = 0
    for index, candidate in enumerate(candidates):
        item, _ = wf.validate_candidate(units, candidate, 'stage candidate ' + str(index))
        if item['severity'] == 'confirmed':
            predictions[effect(units, item['anchors'][0], item['suggestion'])] = category(item)
        else:
            pending += 1
    return predictions, pending


def stage_score(predictions, expected, pending=0):
    keys, gold = set(predictions), set(expected)
    result = metrics(len(keys & gold), len(keys - gold), len(gold - keys))
    result['pending'] = pending
    result['by_category'] = {
        name: metrics(sum(expected[k] == name for k in keys & gold),
                      sum(predictions[k] == name for k in keys - gold),
                      sum(expected[k] == name for k in gold - keys))
        for name in CATEGORIES}
    return result


def candidate_signatures(units, candidates):
    """Ignore reason, source, vote and IDs while verifying stage membership."""
    signatures = []
    for item in candidates:
        if item['severity'] == 'confirmed':
            signatures.append(('confirmed', effect(units, item['anchors'][0], item['suggestion'])))
        else:
            signatures.append(('pending', tuple((a['block_id'], a['quote'], a.get('occurrence', 1))
                                                for a in item['anchors'])))
    return set(signatures)


def execution_timing(value):
    record = value.get('execution')
    if record is None:
        return None
    report.obj(record, 'execution')
    keys = ('ticket', 'context_id', 'context_source', 'opened_at', 'submitted_at', 'executor')
    # Partial or old records cannot supply complete task timing evidence.
    if any(record.get(key) is None for key in ('ticket', 'opened_at', 'submitted_at', 'executor')):
        return None
    for key in ('ticket', 'opened_at', 'submitted_at', 'executor'):
        report.string(record[key], 'execution.' + key)
    report.require(record.get('context_source') in ('host-provided', 'agent-declared', 'unavailable'), 'execution.context_source 无效')
    if record.get('context_id') is not None:
        report.string(record['context_id'], 'execution.context_id')
    report.require(record['executor'] in ('subagent', 'main-agent-fallback'), 'execution.executor 无效')
    timestamps = []
    for key in ('opened_at', 'submitted_at'):
        stamp = datetime.fromisoformat(record[key].replace('Z', '+00:00'))
        report.require(stamp.tzinfo is not None, 'execution 时间必须包含时区')
        timestamps.append(stamp.timestamp())
    report.require(timestamps[1] >= timestamps[0], 'execution 提交时间早于打开时间')
    return dict({key: record.get(key) for key in keys}, wall_elapsed_seconds=timestamps[1]-timestamps[0],
                _start=timestamps[0], _end=timestamps[1])


def stage_metrics(document, review, expected, predictions, pending, work):
    units = report.document_units(document)
    fingerprint = wf.sha(document)
    stages = {key: None for key in ('A', 'B', 'union', 'merged', 'consistency', 'pre_review')}
    stages['final'] = stage_score(predictions, expected, pending)
    comparisons = dict.fromkeys(COMPARISONS)
    phases = dict.fromkeys(('A', 'B', 'consistency', 'review'))
    result = dict(stages=stages, stage_comparisons=comparisons,
                  stage_evidence=dict(final_linked_to_work=None, limitations=[]))
    evidence = result['stage_evidence']
    if work is None:
        evidence['limitations'].append('未提供 WORK，只有所给最终意见的修改效果；各中间阶段未知。')
        return result, phases
    root = Path(work).resolve()
    state_path = root / 'task-state.json'
    state = report.load_json(state_path) if state_path.is_file() else {}
    if state:
        report.require(state.get('document_sha256') == fingerprint, 'WORK 状态与文档版本不匹配')
    jobs = state.get('jobs', {})
    jobs = list(jobs.values()) if isinstance(jobs, dict) else jobs
    report.require(isinstance(jobs, list), 'WORK jobs 无效')

    def read(relative, state_key=None):
        path = root / relative
        if not path.is_file():
            return None
        value = report.load_json(path)
        report.obj(value, relative)
        if 'document_sha256' in value:
            report.require(value['document_sha256'] == fingerprint, relative + ' 文档指纹不匹配')
        if state_key and state.get(state_key) is not None:
            report.require(wf.sha(value) == state[state_key], relative + ' 与 WORK 记录哈希不匹配')
        for job in jobs:
            if job.get('canonical_path') and Path(job['canonical_path']).resolve() == path.resolve():
                if job.get('canonical_sha256') is not None:
                    report.require(wf.sha(value) == job['canonical_sha256'], relative + ' 规范结果已变化')
                if job.get('status') != 'complete' or not job.get('canonical_sha256'):
                    return None
                input_path = Path(job['input_path'])
                if not input_path.is_file():
                    return None
                report.require(wf.sha(report.load_json(input_path)) == job.get('input_sha256'), relative + ' 任务输入已变化')
        return value

    saved_document = read('document.json')
    if saved_document is not None:
        report.require(wf.sha(saved_document) == fingerprint, 'WORK document.json 与评分文档不匹配')
    saved_review = read('review.json', 'final')
    if saved_review is not None:
        report.require(wf.sha(saved_review) == wf.sha(review), '评分 review 与 WORK 最终结果不匹配')
    manifest = read('batches/manifest.json')
    if manifest is None:
        evidence['limitations'].append('缺少批次清单，不能核实 A/B 全文覆盖及阶段来源。')
        return result, phases
    batches = wf.validate_manifest(document, manifest)
    complete = {}
    raw_candidates = []
    timing_records = {key: [] for key in phases}

    def finish_timing(phase, records, is_complete):
        if not is_complete or not records or any(item is None for item in records):
            return
        phases[phase] = dict(wall_elapsed_seconds=max(r['_end'] for r in records)-min(r['_start'] for r in records),
                             sum_job_wall_seconds=sum(r['wall_elapsed_seconds'] for r in records),
                             jobs=[{k:v for k,v in r.items() if not k.startswith('_')} for r in records])

    for pid in ('A', 'B'):
        found, checked, all_present = [], set(), True
        for batch in batches:
            input_path = root / 'batches' / batch['file']
            if not input_path.is_file():
                all_present = False
                continue
            payload = report.load_json(input_path)
            report.require(wf.sha(payload) == batch['input_sha256'], 'A/B 批次输入哈希不匹配')
            report.require(payload.get('document_sha256') == fingerprint, 'A/B 输入文档指纹不匹配')
            report.require(payload.get('main_units') == [u for u in wf.ordered_units(document) if u['id'] in batch['main_unit_ids']],
                           'A/B 输入原文与文档不匹配')
            relative = 'results/{}/{}.json'.format(pid, batch['id'])
            value = read(relative)
            if value is None:
                all_present = False
                continue
            done, _, candidates, _, _ = wf.validate_result(document, manifest, batch, pid, root / relative)
            timing_records[pid].append(execution_timing(value))
            checked.update(done)
            found.extend(candidates)
        complete[pid] = all_present and checked == set(units)
        if complete[pid]:
            effects, count = candidate_effects(units, found)
            stages[pid] = stage_score(effects, expected, count)
        else:
            effects = None
            evidence['limitations'].append(pid + ' 原始结果或全文覆盖不完整，该路和依赖它的比较为 null。')
        complete[pid + '_effects'] = effects
        raw_candidates.extend(found)
        finish_timing(pid, timing_records[pid], complete[pid])
    both = complete['A'] and complete['B']
    if both:
        a, b, gold = set(complete['A_effects']), set(complete['B_effects']), set(expected)
        union_effects, union_pending = candidate_effects(units, wf.merge_candidates(raw_candidates, units))
        stages['union'] = stage_score(union_effects, expected, union_pending)
        comparisons.update(a_unique_correct=len((a-b)&gold), b_unique_correct=len((b-a)&gold), shared_correct=len(a&b&gold))
    merged = read('merged.json', 'merged')
    if merged is None:
        evidence['limitations'].append('缺少 merged.json，复核前后比较未知。')
        return result, phases
    report.require(merged.get('schema_version') == wf.SCHEMA and merged.get('task') == 'merged-candidates', 'merged 类型无效')
    report.require(merged.get('document_sha256') == fingerprint and merged.get('rules_sha256') == manifest['rules_sha256'], 'merged 文档或规则指纹不匹配')
    report.require(isinstance(merged.get('candidates'), list), 'merged.candidates 无效')
    local = merged['candidates']
    local_effects, local_pending = candidate_effects(units, local)
    if both:
        report.require(candidate_signatures(units, local) == candidate_signatures(units, raw_candidates), 'merged 与原始 A/B 候选修改效果不匹配')
        stages['merged'] = stage_score(local_effects, expected, local_pending)
    required = policy.consistency_required(manifest)
    consistency = read('consistency-result.json')
    consistency_complete = not required
    consistency_candidates = []
    if consistency is not None:
        if consistency.get('checked') is True:
            consistency_candidates, _ = wf.load_consistency(document, fingerprint, root/'consistency-result.json', required, wf.sha(merged))
            consistency_complete = consistency.get('complete', True) is True
            records = consistency.get('executions')
            if records is None:
                timing_records['consistency'].append(execution_timing(consistency))
            else:
                timing_records['consistency'].extend(execution_timing({'execution': record}) for record in records)
            effects, count = candidate_effects(units, consistency_candidates)
            if consistency_complete:
                stages['consistency'] = stage_score(effects, expected, count)
        else:
            consistency_complete = False
    finish_timing('consistency', timing_records['consistency'], consistency_complete)
    evidence['consistency_required'] = required
    if not consistency_complete:
        evidence['limitations'].append('跨批次一致性阶段不完整，复核前整体及复核变化未知。')
    pre_complete = both and consistency_complete
    normalized_local = []
    for item in local:
        normalized, positions = wf.validate_candidate(units, item, 'merged candidate')
        normalized.update(positions=positions)
        normalized_local.append(normalized)
    pre_candidates = wf.merge_candidates(normalized_local + consistency_candidates, units)
    pre_effects, pre_pending = candidate_effects(units, pre_candidates)
    if pre_complete:
        stages['pre_review'] = stage_score(pre_effects, expected, pre_pending)
    plan = read('review-input/manifest.json', 'review_plan')
    if plan is None:
        evidence['limitations'].append('缺少复核计划，不能连接所给最终意见与复核前候选。')
        return result, phases
    report.require(plan.get('schema_version') == wf.SCHEMA and plan.get('task') == 'review-manifest', '复核计划类型无效')
    report.require(plan.get('document_sha256') == fingerprint and plan.get('merged_sha256') == wf.sha(merged), '复核计划文档或合并哈希不匹配')
    report.require(plan.get('rules_sha256') == manifest['rules_sha256'], '复核计划规则不匹配')
    report.require(isinstance(plan.get('batches'), list), '复核批次列表无效')
    selected, plan_candidates, review_complete = [], [], True
    seen_batches = set()
    for batch in plan['batches']:
        report.require(batch['id'] not in seen_batches, '复核批次重复')
        seen_batches.add(batch['id'])
        payload = read('review-input/' + batch['file'])
        if payload is None:
            review_complete = False
            continue
        report.require(wf.sha(payload) == batch['input_sha256'], '复核输入哈希不匹配')
        for group in payload['candidate_groups']:
            plan_candidates.extend(group['candidates'])
        value = read('review-results/' + batch['id'] + '.json')
        if value is None:
            review_complete = False
            continue
        report.require(value.get('schema_version') == wf.SCHEMA and value.get('task') == 'review-result', '复核规范结果类型无效')
        report.require(value.get('document_sha256') == fingerprint and value.get('review_batch_id') == batch['id'], '复核结果标识不匹配')
        report.require(value.get('review_input_sha256') == batch['input_sha256'], '复核结果输入哈希不匹配')
        findings, notes = wf.review_decisions(document, payload, value)
        if notes:
            review_complete = False
        selected.extend(findings)
        timing_records['review'].append(execution_timing(value))
    finish_timing('review', timing_records['review'], review_complete)
    if review_complete and consistency_complete:
        report.require(candidate_signatures(units, pre_candidates) == candidate_signatures(units, plan_candidates), '复核计划与完整复核前候选不匹配')
    if review_complete:
        report.require(candidate_signatures(units, selected) == candidate_signatures(units, review['findings']), '最终意见与规范复核结果不匹配')
        evidence['final_linked_to_work'] = True
    else:
        evidence['limitations'].append('复核原始结果不完整，最终意见与完整复核阶段的连接未知。')
    if pre_complete and review_complete:
        before, after, gold = set(pre_effects), set(predictions), set(expected)
        removed, added = before-after, after-before
        comparisons.update(review_removed_correct=len(removed&gold), review_removed_incorrect=len(removed-gold),
                           review_added_correct=len(added&gold), review_added_incorrect=len(added-gold))
    return result, phases


def process_metrics(work, fingerprint):
    result = {'first_submission_pass_rate':None,'local_corrections':None,'fallback_jobs':None,
              'model_elapsed_seconds':None,'a_unique_correct':None,'b_unique_correct':None,
              'review_removed_correct':None,'review_removed_incorrect':None,
              'limitations':['阶段修改效果须对照当前标注解释；流程统计不能代替准确率。',
                             'wall_elapsed_seconds 是打开到提交的墙钟跨度，包含排队、工具和人工等待；不是模型计算时间。',
                             '执行身份由宿主提供或声明，哈希与上下文 ID 不能证明信息隔离。']}
    if work is None:
        return result
    root = Path(work)
    state_path = root / 'task-state.json'
    if not state_path.is_file():
        result['limitations'].append('缺少 task-state.json，流程统计无数据。')
        return result
    state = report.load_json(state_path)
    report.require(state.get('document_sha256') == fingerprint, 'WORK 状态与文档版本不匹配')
    jobs = state.get('jobs')
    if isinstance(jobs, dict):
        jobs = list(jobs.values())
    if isinstance(jobs, list):
        result['fallback_jobs'] = sum(j.get('executor') == 'main-agent-fallback' for j in jobs)
    events = [report.load_json(p) for p in sorted((root / 'submission-events').glob('*.json'))]
    if events:
        first = {}
        grouped = {}
        for event in events:
            report.require(event.get('status') in ('invalid','accepted') and type(event.get('attempt')) is int,
                           '提交事件无效')
            report.require(isinstance(event.get('task_id'),str) and isinstance(event.get('at'),str)
                           and isinstance(event.get('ticket'), str) and bool(event['ticket']), '提交事件缺少标识/票据/时间')
            key = event['task_id']
            if key not in first or (event['attempt'],event['at']) < (first[key]['attempt'],first[key]['at']):
                first[key] = event
            grouped.setdefault((key, event['attempt'], event['ticket']), []).append(event)
        result['first_submission_pass_rate'] = sum(e['status'] == 'accepted' for e in first.values()) / len(first)
        result['local_corrections'] = sum(
            any(accepted['status'] == 'accepted' and event['at'] < accepted['at'] for accepted in group)
            for group in grouped.values() for event in group if event['status'] == 'invalid')
    return result


def prepare(seed_path, work):
    seed = report.load_json(seed_path)
    report.require(seed.get('annotation_status') == 'seed-unreviewed', 'prepare 只接受未审定开发种子')
    cases = seed.get('cases')
    report.require(isinstance(cases,list) and cases, 'seed.cases 必须非空')
    blocks, gold_cases = [], []
    for index, case in enumerate(cases,1):
        report.require(case.get('annotation_status') == 'seed-unreviewed', 'prepare 不修改标注等级')
        bid = 'p{:03d}'.format(index)
        text = report.string(case.get('text'), 'seed.text')
        blocks.append(dict(id=bid,kind='paragraph',location='第{}段'.format(index),text=text))
        gold_cases.append(dict(block_id=bid,text=text,annotation_status='seed-unreviewed',expected=case['expected']))
    root = Path(work).resolve()
    skill = Path(__file__).resolve().parents[1]
    report.require(root != skill and skill not in root.parents, '测评工作目录必须在技能包外')
    report.require(not root.exists(), 'prepare 要求新的独立 WORK 目录，不能覆盖已有任务')
    root.mkdir(parents=True)
    source = root / 'source.txt'
    source.write_text('\n'.join(b['text'] for b in blocks) + '\n',encoding='utf-8')
    document = provenance.bind(dict(title='合成开发校对基准',source_name='source.txt',scope='全部合成段落',limitations=[],blocks=blocks), provenance.snapshot(source), '离线种子逐条转为段落')
    gold = dict(document_sha256=provenance.digest(document),annotation_status='seed-unreviewed',cases=gold_cases)
    for name, value in (('document.json',document),('gold.json',gold)):
        (root / name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def annotation_template(document_path):
    document = report.load_json(document_path)
    provenance.verify(document)
    units = report.document_units(document)
    return {'document_sha256': provenance.digest(document),
            'annotation_status': 'unannotated',
            'review_record': {'annotators': [], 'date': None, 'basis': None, 'disagreements': None},
            'cases': [{'block_id': bid, 'text': unit['text'],
                       'annotation_status': 'unannotated', 'expected': None}
                      for bid, unit in units.items()]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command',required=True)
    prep = sub.add_parser('prepare')
    prep.add_argument('--seed',default=str(Path(__file__).resolve().parents[1] / 'assets/evaluation-seed.json'))
    prep.add_argument('--work',required=True)
    annotation = sub.add_parser('annotation-template')
    annotation.add_argument('--document', required=True)
    annotation.add_argument('--output', required=True)
    score = sub.add_parser('score')
    for name in ('document','review','gold'):
        score.add_argument('--'+name,required=True)
    score.add_argument('--work')
    score.add_argument('--output')
    args = parser.parse_args()
    try:
        if args.command == 'annotation-template':
            value = annotation_template(args.document)
            report.write_output(args.output, json.dumps(value, ensure_ascii=False, indent=2)+'\n', False, [args.document])
            print('已生成未标注模板；人工逐条完成前不能评分，不向检查员提供该文件。')
        elif args.command == 'prepare':
            prepare(args.seed,args.work)
            print('已生成开发基准。gold.json 仅交评分器/人工标注者，禁止提供给初检或复核代理。')
        else:
            result = evaluate(report.load_json(args.document),report.load_json(args.review),report.load_json(args.gold),args.work)
            rendered = json.dumps(result,ensure_ascii=False,indent=2)+'\n'
            if args.output:
                report.write_output(args.output,rendered,False,(args.document,args.review,args.gold))
            else:
                print(rendered,end='')
    except (ValueError,OSError,UnicodeError,KeyError,TypeError) as exc:
        print('错误：'+str(exc),file=sys.stderr)
        return 2
    return 0

if __name__ == '__main__':
    sys.exit(main())
