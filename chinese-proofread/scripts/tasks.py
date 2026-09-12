#!/usr/bin/env python3
"""Offline coordinator. Emits host-agent tasks; never calls models or a network."""
import argparse
from contextlib import contextmanager, redirect_stdout
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile
import time
from types import SimpleNamespace
import uuid

import provenance
import guidance
import report
import workflow as wf

SKILL = Path(__file__).resolve().parent.parent


def now():
    return datetime.now(timezone.utc).isoformat()


def claim_coordinator(work, state, coordinator, takeover=False):
    """Called under the short command lock, before any pipeline mutation."""
    report.require(isinstance(coordinator, str) and coordinator.strip(), '必须提供本协调会话专用、稳定的 --coordinator 标识')
    previous = state.get('coordinator')
    report.require(not previous or previous['id'] == coordinator or takeover,
                   '工作区由其他协调员持有；确认接管后使用 --takeover，不会因等待时间自动释放所有权')
    at = now()
    if previous and previous['id'] != coordinator:
        event = {'event': 'takeover', 'previous_coordinator': previous['id'],
                 'coordinator': coordinator, 'at': at,
                 'jobs_preserved': [{'id': j['id'], 'ticket': j['ticket'], 'status': j['status']}
                                    for j in state['jobs'].values()]}
        save(work / 'coordinator-events' / (str(uuid.uuid4()) + '.json'), event)
    state['coordinator'] = {'id': coordinator, 'claimed_at': previous['claimed_at']
                            if previous and previous['id'] == coordinator else at,
                            'last_activity_at': at}


def save(path, value, overwrite=False):
    wf.dump(path, value, overwrite)


def invoke(function, **kwargs):
    with redirect_stdout(io.StringIO()):
        # Only used for unfinished deterministic stages in this coordinator's
        # reserved work directories. Completed stages are hash-checked instead.
        function(SimpleNamespace(overwrite=True, **kwargs))


@contextmanager
def coordinator_lock(work):
    lock = work / '.coordinator.lock'
    deadline = time.monotonic() + 5
    while True:
        try:
            handle = lock.open('x', encoding='utf-8')
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise report.DataError('调度/领取锁仍被占用；稍后重试同一命令。仅在确认原进程退出后删除 .coordinator.lock；不要因此重查或读取其他结果')
            time.sleep(0.05)
    try:
        handle.close()
        yield
    finally:
        lock.unlink()


def create_job(work, state, task_id, kind, input_path, canonical_path, pass_id=None):
    if task_id in state['jobs']:
        return
    state['jobs'][task_id] = {
        'id': task_id, 'kind': kind, 'input_path': str(input_path.resolve()),
        'input_sha256': wf.sha(wf.load(input_path)), 'canonical_path': str(canonical_path.resolve()),
        'pass_id': pass_id, 'attempt': 1, 'executor': 'subagent', 'status': 'pending',
    }
    prepare_attempt(work, state['jobs'][task_id])


def prepare_attempt(work, job):
    token = str(uuid.uuid4())
    stem = '{}-attempt{}'.format(job['id'], job['attempt'])
    for key in ('assigned_at', 'started_at', 'opened_at', 'context_id', 'context_source'):
        job.pop(key, None)
    job.update(ticket=token, ticket_created_at=now(), job_path=str(work / 'jobs' / (stem + '.json')),
               response_path=str(work / 'responses' / (stem + '.json')))
    Path(job['response_path']).parent.mkdir(parents=True, exist_ok=True)
    job.pop('error', None)
    metadata = {k: job[k] for k in ('id', 'kind', 'input_path', 'input_sha256', 'ticket', 'response_path', 'pass_id', 'executor')}
    text, sources = guidance.compose(job['kind'], wf.load(job['input_path']))
    job['guidance_path'] = str(work / 'jobs' / (stem + '.guidance.md'))
    report.write_output(job['guidance_path'], text, True, [str(SKILL / 'references' / name) for name in sources])
    job['guidance_sha256'] = provenance.file_digest(job['guidance_path'])
    body_path = Path(job['response_path'] + '.body')
    if not body_path.exists():
        save(body_path, guidance.draft(job['kind'], wf.load(job['input_path'])))
    metadata.update(guidance_path=job['guidance_path'], guidance_sources=sources)
    metadata['instructions'] = task_prompt(job)
    save(job['job_path'], metadata, Path(job['job_path']).exists())
    job['job_sha256'] = wf.sha(metadata)


def execution_evidence(job, raw=None):
    """Identity is evidence supplied by the host/agent, never proof of isolation."""
    evidence = {'ticket': job['ticket'], 'context_id': None, 'context_source': 'unavailable',
                'opened_at': None, 'submitted_at': None, 'executor': job['executor']}
    started_path = Path(job['job_path'] + '.started')
    if started_path.is_file():
        started = wf.load(started_path)
        report.require(started.get('ticket') == job['ticket'], '启动票据不匹配')
        source = started.get('context_source', 'unavailable')
        context_id = started.get('context_id')
        report.require(source in ('host-provided', 'agent-declared', 'unavailable'), '启动记录 context-source 无效')
        report.require((source == 'unavailable') == (context_id is None), '启动记录上下文 ID 与来源不匹配')
        if context_id is not None:
            report.string(context_id, 'started.context_id')
        opened_at = report.string(started.get('opened_at', started.get('at')), 'started.opened_at')
        evidence.update(context_id=context_id, context_source=source, opened_at=opened_at)
    if raw is not None:
        submitted = raw.get('_submission', {})
        report.obj(submitted, '_submission')
        if submitted:
            report.require(submitted.get('ticket') == job['ticket'], '提交审计票据不匹配')
            evidence['submitted_at'] = report.string(submitted.get('submitted_at'), 'submitted_at')
    return evidence


def check_job_files(job):
    report.require(provenance.file_digest(job['guidance_path']) == job['guidance_sha256'], '任务指引发生变化：' + job['id'])
    report.require(wf.sha(wf.load(job['job_path'])) == job['job_sha256'], '任务文件发生变化：' + job['id'])
    report.require(wf.sha(wf.load(job['input_path'])) == job['input_sha256'], '任务输入发生变化：' + job['id'])


def normalize_response(document, manifest, job, raw):
    report.obj(raw, 'response')
    report.require(raw.get('ticket') == job['ticket'], '结果票据不匹配，可能来自旧任务或其他输入')
    report.strings(raw.get('limitations'), 'limitations')
    payload = wf.load(job['input_path'])
    base = {'schema_version': wf.SCHEMA, 'document_sha256': wf.sha(document),
            'limitations': list(raw['limitations']), 'execution': execution_evidence(job, raw)}
    if job['kind'] != 'proofread' and job['executor'] == 'main-agent-fallback':
        base['limitations'].append(job['id'] + ' 由主 Agent 补做，独立性降低')
    if job['kind'] == 'proofread':
        batch = find_batch(manifest, payload['batch_id'])
        candidates = raw.get('candidates')
        report.require(isinstance(candidates, list), 'candidates 必须是列表')
        candidates = [dict(report.obj(c, 'candidate'), id='c-' + str(i + 1)) for i, c in enumerate(candidates)]
        completed = raw.get('completed')
        report.require(type(completed) is bool, '必须明确声明 completed 是否为 true')
        checked = batch['main_unit_ids'] if completed else report.strings(raw.get('checked_unit_ids'), 'checked_unit_ids')
        terms = raw.get('terms')
        report.require(isinstance(terms, list), 'terms 必须是列表')
        expanded = []
        for term in terms:
            report.obj(term, 'term')
            text = report.string(term.get('text'), 'term.text')
            kind = report.string(term.get('kind'), 'term.kind')
            matches = [unit['id'] for unit in payload['main_units'] if text in unit['text']]
            report.require(matches, 'terms 中名称 ' + repr(text) + ' 不在本批 main_units 原文中；核对原字或删除错误索引，勿重查整批')
            expanded.extend({'text': text, 'kind': kind, 'block_id': bid} for bid in matches if bid in checked)
        base.update(task='proofread-result', batch_id=batch['id'], pass_id=job['pass_id'], executor=job['executor'],
                    checked_unit_ids=checked, candidates=candidates, terms=expanded,
                    rules_sha256=manifest['rules_sha256'], batch_input_sha256=batch['input_sha256'])
    elif job['kind'] == 'consistency':
        candidates = raw.get('candidates')
        report.require(isinstance(candidates, list), 'candidates 必须是列表')
        base.update(task='consistency-result', checked=raw.get('checked'), merged_sha256=payload['merged_sha256'],
                    candidates=[dict(report.obj(c, 'candidate'), id='name-' + str(i + 1)) for i, c in enumerate(candidates)])
    else:
        base.update(task='review-result', review_batch_id=payload['review_batch_id'],
                    review_input_sha256=job['input_sha256'], group_decisions=raw.get('group_decisions'))
    return base


def validate_canonical(document, manifest, job, value, work):
    if job['kind'] == 'proofread':
        batch = find_batch(manifest, value['batch_id'])
        done, _, _, _, _ = wf.validate_result(document, manifest, batch, job['pass_id'], job['canonical_path'])
        report.require(set(done) == set(batch['main_unit_ids']), '本批检查尚未完整，请补查或使用有范围标注的部分报告流程')
    elif job['kind'] == 'consistency':
        wf.load_consistency(document, wf.sha(document), job['canonical_path'], True,
                            wf.load(job['input_path'])['merged_sha256'])
    else:
        _, notes = wf.review_decisions(document, wf.load(job['input_path']), value)
        report.require(not notes, '；'.join(notes))


def find_batch(manifest, batch_id):
    batch = next((item for item in manifest['batches'] if item['id'] == batch_id), None)
    report.require(batch is not None, '未知 batch_id：' + str(batch_id))
    return batch


def refresh(work, state, document, manifest):
    for job in state['jobs'].values():
        if job['status'] != 'complete' and job['executor'] == 'main-agent-fallback':
            skip_job(job, '旧版主 Agent 补做任务已停用')
        if job['status'] == 'invalid' and job['attempt'] >= 2:
            skip_job(job, '重查次数已用尽')
        check_job_files(job)
        started_path = Path(job['job_path'] + '.started')
        if job['status'] == 'assigned' and started_path.is_file():
            started = wf.load(started_path)
            report.require(started.get('ticket') == job['ticket'], '启动票据不匹配')
            job.update(status='running', started_at=started.get('opened_at', started.get('at')))
        if job['status'] == 'complete':
            report.require(wf.sha(wf.load(job['canonical_path'])) == job['canonical_sha256'],
                           '已接收结果发生变化：' + job['id'])
            continue
        if job['status'] not in ('assigned', 'running') or not Path(job['response_path']).is_file():
            continue
        # Validate via a private staging file before accepting a result into the pipeline.
        stage = work / 'staging' / (job['ticket'] + '.json')
        try:
            raw = wf.load(job['response_path'])
            value = normalize_response(document, manifest, job, raw)
            save(stage, value, stage.exists())
            temporary_job = dict(job, canonical_path=str(stage))
            validate_canonical(document, manifest, temporary_job, value, work)
            target = Path(job['canonical_path'])
            if target.exists():
                report.require(wf.sha(wf.load(target)) == wf.sha(value),
                               '结果提交中断后发现不同内容，不能覆盖：' + job['id'])
            else:
                save(target, value)
            job.update(status='complete', canonical_sha256=wf.sha(value))
        except (ValueError, OSError, KeyError, TypeError) as exc:
            job.update(status='invalid', error=str(exc))
            if job['attempt'] >= 2:
                skip_job(job, '重查次数已用尽')


def skip_job(job, reason):
    # No synthetic result: downstream missing-result handling preserves coverage.
    job.update(status='skipped', skipped_at=now(), skip_reason=reason)
    job.pop('error', None)


def all_complete(state, kind):
    return all(j['status'] in ('complete', 'skipped') for j in state['jobs'].values() if j['kind'] == kind)


def advance(work, state, document, manifest):
    if not all_complete(state, 'proofread'):
        return 'proofread'
    if not state.get('merged'):
        invoke(wf.merge_command, document=str(work / 'document.json'), manifest=str(work / 'batches' / 'manifest.json'),
               results_dir=str(work / 'results'), output=str(work / 'merged.json'),
               consistency_output=str(work / 'consistency-input.json'))
        state['merged'] = wf.sha(wf.load(work / 'merged.json'))
        state['consistency_input'] = wf.sha(wf.load(work / 'consistency-input.json'))
    report.require(state['merged'] == wf.sha(wf.load(work / 'merged.json')), '合并结果已变化')
    consistency = wf.load(work / 'consistency-input.json')
    report.require(state['consistency_input'] == wf.sha(consistency), '名称索引已变化')
    if consistency['required']:
        if consistency['terms']:
            create_job(work, state, 'consistency', 'consistency', work / 'consistency-input.json', work / 'consistency-result.json')
            if consistency.get('budget_exceeded') and state['jobs']['consistency']['status'] == 'pending':
                skip_job(state['jobs']['consistency'], '名称索引超出输入预算，未执行名称一致性检查')
            if not all_complete(state, 'consistency'):
                return 'consistency'
        elif not (work / 'consistency-result.json').exists():
            save(work / 'consistency-result.json', {
                'schema_version': wf.SCHEMA, 'task': 'consistency-result', 'document_sha256': wf.sha(document),
                'merged_sha256': state['merged'], 'checked': True, 'candidates': [], 'limitations': []})
    if not state.get('review_plan'):
        invoke(wf.review_plan_command, document=str(work / 'document.json'), manifest=str(work / 'batches' / 'manifest.json'),
               merged=str(work / 'merged.json'), consistency_result=str(work / 'consistency-result.json') if consistency['required'] and (work / 'consistency-result.json').is_file() else None,
               output_dir=str(work / 'review-input'), max_candidates=25)
        state['review_plan'] = wf.sha(wf.load(work / 'review-input' / 'manifest.json'))
    plan = wf.load(work / 'review-input' / 'manifest.json')
    report.require(state['review_plan'] == wf.sha(plan), '复核清单已变化')
    for batch in plan['batches']:
        create_job(work, state, batch['id'], 'review', work / 'review-input' / batch['file'],
                   work / 'review-results' / (batch['id'] + '.json'))
        if batch.get('budget_exceeded') and state['jobs'][batch['id']]['status'] == 'pending':
            skip_job(state['jobs'][batch['id']], '不可拆分候选组超出复核输入预算')
    if not all_complete(state, 'review'):
        return 'review'
    if not state.get('final'):
        invoke(wf.finalize_command, document=str(work / 'document.json'), merged=str(work / 'merged.json'),
               review_manifest=str(work / 'review-input' / 'manifest.json'), review_results_dir=str(work / 'review-results'),
               output=str(work / 'review.json'))
        state['final'] = wf.sha(wf.load(work / 'review.json'))
    review = wf.load(work / 'review.json')
    report.require(state['final'] == wf.sha(review), '最终结果已变化')
    if not state.get('report_sha256'):
        report.write_output(str(work / '校对报告.html'), report.render(document, review), True,
                            [str(work / 'document.json'), str(work / 'review.json')])
        state['report_sha256'] = provenance.file_digest(work / '校对报告.html')
    report.require(state['report_sha256'] == provenance.file_digest(work / '校对报告.html'), '报告文件已变化')
    return 'done'


def submit_argv(job):
    return [sys.executable, str(SKILL / 'scripts' / 'tasks.py'), 'submit',
            '--job', job['job_path'], '--body', job['response_path'] + '.body']


def shell_command(argv):
    if os.name == 'nt':
        return 'PowerShell', '& ' + ' '.join("'" + arg.replace("'", "''") + "'" for arg in argv)
    return 'POSIX sh', ' '.join(shlex.quote(arg) for arg in argv)


def submission_command(job):
    return shell_command(submit_argv(job))


def handoff_prompt(job):
    shell, command = shell_command([sys.executable, str(SKILL / 'scripts' / 'tasks.py'), 'open', '--job', job['job_path'], '--brief'])
    return '在独立新上下文执行 {} 命令，按返回指令完成；stop_no_work 即结束：\n{}'.format(shell, command)


def task_prompt(job):
    role = {'proofread': '中文文字初检 ' + str(job['pass_id']), 'consistency': '名称一致性检查',
            'review': '候选复核'}[job['kind']]
    shell, command = submission_command(job)
    return ('角色：{}。只完成本角色任务。\n任务指引：{}\n原文输入：{}\n结果草稿（已预填结构，按实际检查填写）：{}\n'
            '只读任务指引、原文输入及自己的结果草稿；指引已包含本角色所需规则与格式，无需寻找其他参考文件。'
            '不读取其他检查结果、测评答案或整个工作目录，不改原文。'
            '按指引写结果后用 {} 提交：{}\n'
            '定位或字段错误在本任务局部修正，最多连续3次；不猜定位、不删除真实发现凑通过。'
            '提交成功只回“{} submitted”；无法继续只回“{} blocked 简短类别”。不调度、不写报告。').format(
                role, job['guidance_path'], job['input_path'], job['response_path'] + '.body',
                shell, command, job['id'], job['id'])


def publish_response(target, raw):
    target = Path(target)
    report.require(not target.exists(), '结果已提交，不重复覆盖；失败重试应使用新任务文件')
    target.parent.mkdir(parents=True, exist_ok=True)
    lock = target.with_name(target.name + '.publish-lock')
    try:
        lock.mkdir()
    except FileExistsError:
        raise report.DataError('此结果正在提交；若原执行已确认退出且结果尚未发布，可删除对应 .publish-lock 空目录后原票据重新 submit')
    temporary = None
    try:
        report.require(not target.exists(), '结果已提交，不重复覆盖')
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=target.parent,
                                         prefix='.submit-', delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(raw, handle, ensure_ascii=False)
            handle.write('\n')
        # Publishing a complete JSON atomically avoids another finished worker's
        # next() observing this worker's partially written response.
        # The exclusive directory serializes publishers. Atomic same-directory
        # replacement then works without requiring hard-link support.
        os.replace(str(temporary), str(target))
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
        lock.rmdir()


def submission_event(work, job, status, message=''):
    event = {'task_id': job['id'], 'ticket': job['ticket'], 'attempt': job['attempt'],
             'status': status, 'message': message, 'at': datetime.now(timezone.utc).isoformat()}
    try:
        save(work / 'submission-events' / (str(uuid.uuid4()) + '.json'), event)
    except OSError as exc:
        print('提示：提交统计未能落盘：' + str(exc), file=sys.stderr)


def job_context(job_path):
    metadata = wf.load(job_path)
    work = Path(job_path).resolve().parent.parent
    state = wf.load(work / 'task-state.json')
    report.require(metadata['id'] in state['jobs'], '未知任务')
    job = state['jobs'][metadata['id']]
    report.require(Path(job['job_path']).resolve() == Path(job_path).resolve()
                   and job['ticket'] == metadata['ticket'], '旧任务票据，不能提交到当前任务')
    report.require(job['status'] in ('assigned', 'running'), '本任务尚未分配或已经结束')
    report.require(job['executor'] != 'main-agent-fallback', '主 Agent 补做已停用；执行 step 跳过旧任务')
    check_job_files(job)
    document = wf.load(work / 'document.json')
    manifest = wf.load(work / 'batches' / 'manifest.json')
    wf.validate_manifest(document, manifest)
    report.require(state['document_sha256'] == wf.sha(document)
                   and state['rules_sha256'] == wf.rules_sha()
                   and state['manifest_sha256'] == wf.sha(manifest), '来源、规则或批次版本已变化')
    return work, job, metadata, document, manifest


def stop_no_work(task_id, status):
    return {'action': 'stop_no_work', 'id': task_id, 'status': status}


def open_job(job_path, context_id=None, context_source=None):
    # Cheap exits deliberately do not load document, rules, inputs or responses.
    metadata = wf.load(job_path)
    task_id = report.string(metadata.get('id'), 'job.id')
    ticket = report.string(metadata.get('ticket'), 'job.ticket')
    work = Path(job_path).resolve().parent.parent
    with coordinator_lock(work):
        state = wf.load(work / 'task-state.json')
        report.require(task_id in state['jobs'], '未知任务')
        job = state['jobs'][task_id]
        if ticket != job['ticket'] or Path(job_path).resolve() != Path(job['job_path']).resolve():
            return stop_no_work(task_id, 'stale')
        if job['executor'] == 'main-agent-fallback':
            return stop_no_work(task_id, 'fallback_disabled')
        if job['status'] not in ('assigned', 'running'):
            return stop_no_work(task_id, job['status'])
        started_path = Path(job['job_path'] + '.started')
        if started_path.exists():
            execution_evidence(job)
            return stop_no_work(task_id, 'already_opened')
        if Path(job['response_path']).exists():
            return stop_no_work(task_id, 'response_pending')
        if context_id is not None:
            report.require(isinstance(context_id, str) and context_id.strip(), 'context-id 不能为空')
        source = context_source or ('agent-declared' if context_id is not None else 'unavailable')
        report.require(source in ('host-provided', 'agent-declared', 'unavailable'), '未知 context-source')
        report.require((source == 'unavailable') == (context_id is None),
                       '有 context-id 必须声明来源；没有真实 ID 时必须使用 unavailable')
        work, job, metadata, _, _ = job_context(job_path)
        if context_id is not None:
            for receipt_path in (work / 'jobs').glob('*.json.started'):
                receipt = wf.load(receipt_path)
                if receipt.get('context_id') == context_id:
                    raise report.DataError('不同任务不能复用 context-id；初检、名称检查和复核均需新上下文')
        at = now()
        publish_response(started_path, {'ticket': ticket, 'at': at, 'opened_at': at,
                                       'context_id': context_id, 'context_source': source})
        return dict(metadata, action='execute', execution=execution_evidence(job))


def submit_body(job_path, body_path):
    work, job, _, document, manifest = job_context(job_path)
    report.require(not Path(job['response_path']).exists(), '结果已提交，不重复覆盖')
    stage = None
    try:
        body = wf.load(body_path)
        report.obj(body, 'result body')
        report.require(not any(key in body for key in ('ticket', '_submission', 'execution')),
                       '结果正文不要手写 ticket、execution 或 _submission，提交时由脚本绑定')
        raw = dict(body, ticket=job['ticket'], _submission={'ticket': job['ticket'], 'submitted_at': now()})
        value = normalize_response(document, manifest, job, raw)
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=work,
                                         prefix='.validate-', delete=False) as handle:
            stage = Path(handle.name)
            json.dump(value, handle, ensure_ascii=False)
        validate_canonical(document, manifest, dict(job, canonical_path=str(stage)), value, work)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        submission_event(work, job, 'invalid', str(exc))
        raise report.DataError('本次结果尚未提交：' + str(exc) + '。请原检查员只修正对应字段后重新 submit；不消耗重查次数。') from exc
    finally:
        if stage is not None and stage.exists():
            stage.unlink()
    publish_response(job['response_path'], raw)
    submission_event(work, job, 'accepted')
    return work, job, document, manifest


def reconcile(work, state, document, manifest):
    previously_complete = {j['id'] for j in state['jobs'].values() if j['status'] == 'complete'}
    refresh(work, state, document, manifest)
    newly_complete = [j['id'] for j in state['jobs'].values()
                      if j['status'] == 'complete' and j['id'] not in previously_complete]
    state['last_reconciliation'] = {'at': now(), 'accepted_count': len(newly_complete), 'task_ids': newly_complete}
    return newly_complete


def submit(job_path, body_path):
    # Serialize publication with next/retry. Workers advance only deterministic
    # stages; they never claim coordinator ownership or reserve new worker slots.
    work = Path(job_path).resolve().parent.parent
    with coordinator_lock(work):
        work, job, document, manifest = submit_body(job_path, body_path)
        state_path = work / 'task-state.json'
        state = wf.load(state_path)
        response = {'submitted': True, 'result_path': job['response_path']}
        try:
            reconcile(work, state, document, manifest)
            phase = advance(work, state, document, manifest)
            response['phase'] = phase
            if phase == 'done':
                response['report_path'] = str(work / '校对报告.html')
        except (ValueError, OSError, KeyError, TypeError) as exc:
            # The body was already published. Do not tell the worker to resubmit
            # or discard a valid language decision when only rendering failed.
            response.update(action='coordinator_step', message='结果已提交，自动推进未完成：' + str(exc))
        finally:
            save(state_path, state, True)
    print(json.dumps(response, ensure_ascii=False))


def simple_step(result):
    """Small coordinator interface; detailed state remains available via status."""
    action = {'dispatch_ready': 'dispatch', 'resolve_errors': 'repair',
              'deliver_report': 'deliver', 'wait_for_workers': 'wait'}[result['next_action']]
    answer = {'action': action, 'phase': result['phase'], 'concurrency': result['concurrency']}
    if action == 'dispatch':
        answer['tasks'] = result['ready']
        occupied = len(result['running']) + len(result['assigned'])
        answer['capacity'] = {'limit': result['concurrency'], 'occupied': occupied,
                              'available': max(0, result['concurrency'] - occupied)}
        answer['instruction'] = '本次交接 {} 个任务；含本次预留共占用 {}/{} 槽位。返回一个也正常，只补空位；原样派发 prompt，不另写包装。'.format(len(result['ready']), occupied, result['concurrency'])
    elif action == 'repair':
        answer['errors'] = result['errors']
        answer['instruction'] = '按 references/recovery.md 处理；不要重新校对整篇。'
    elif action == 'deliver':
        answer['report_path'] = result['report_path']
    else:
        answer['wait_command'] = result['wait_command']
        answer['waiting_for'] = result['running'] + result['assigned']
        answer['instruction'] = '等待任意一个子任务完成即 step，不等全部完成、不自行长时间 sleep。无宿主完成通知时执行 wait_command；未派发任务用 --resume-assigned。'
    return answer


def partial_report(work, state, document, manifest):
    """Render a separate snapshot; never publish unreviewed candidates as errors."""
    reconcile(work, state, document, manifest)
    output = Path(tempfile.mkdtemp(prefix='partial-', dir=str(work)))
    if state.get('merged'):
        merged = work / 'merged.json'
        report.require(state['merged'] == wf.sha(wf.load(merged)), '合并结果已变化')
    else:
        merged = output / 'merged.json'
        invoke(wf.merge_command, document=str(work / 'document.json'),
               manifest=str(work / 'batches' / 'manifest.json'), results_dir=str(work / 'results'),
               output=str(merged), consistency_output=str(output / 'consistency-input.json'))
    if state.get('review_plan'):
        plan = work / 'review-input' / 'manifest.json'
        report.require(state['review_plan'] == wf.sha(wf.load(plan)), '复核计划已变化')
        results = work / 'review-results'
    else:
        review_input = output / 'review-input'
        consistency = work / 'consistency-result.json'
        invoke(wf.review_plan_command, document=str(work / 'document.json'),
               manifest=str(work / 'batches' / 'manifest.json'), merged=str(merged),
               consistency_result=str(consistency) if state.get('merged') and consistency.is_file() else None,
               output_dir=str(review_input), max_candidates=25)
        plan, results = review_input / 'manifest.json', output / 'review-results'
    invoke(wf.finalize_command, document=str(work / 'document.json'), merged=str(merged),
           review_manifest=str(plan), review_results_dir=str(results), output=str(output / 'review.json'))
    review = wf.load(output / 'review.json')
    review['limitations'].insert(0, '这是部分交付快照，仅展示已完成复核的意见；未完成范围不能视为没有错误。')
    save(output / 'review.json', review, True)
    target = output / '校对报告-部分.html'
    report.write_output(str(target), report.render(document, review), False,
                        [str(work / 'document.json'), str(output / 'review.json')])
    return {'action': 'deliver_partial', 'report_path': str(target),
            'instruction': '明确说明这是部分报告；本命令不停止仍在执行的子任务。'}


def next_tasks(work, state, phase, compact=False, resume_assigned=False):
    running = [j['id'] for j in state['jobs'].values() if j['status'] == 'running']
    assigned = [j['id'] for j in state['jobs'].values() if j['status'] == 'assigned']
    slots = max(0, state['concurrency'] - len(running) - len(assigned))
    ready = []
    for job in state['jobs'].values():
        replay = resume_assigned and job['status'] == 'assigned'
        if (job['status'] == 'pending' and slots > 0) or replay:
            job['status'] = 'assigned'
            if not replay:
                job['assigned_at'] = now()
            if compact:
                ready.append({'id': job['id'], 'executor': job['executor'],
                              'action': 'spawn_fresh_context',
                              'prompt': handoff_prompt(job)})
            else:
                ready.append({'id': job['id'], 'job_path': job['job_path'], 'executor': job['executor'],
                              'action': 'spawn_fresh_context',
                              'submit_argv': submit_argv(job), 'prompt': handoff_prompt(job)})
            if not replay:
                assigned.append(job['id'])
                slots -= 1
    return {'phase': phase, 'concurrency': state['concurrency'], 'ready': ready, 'running': running, 'assigned': assigned,
            'skipped': sum(j['status'] == 'skipped' for j in state['jobs'].values()),
            'complete': sum(j['status'] == 'complete' for j in state['jobs'].values()),
            'total': len(state['jobs']),
            'wait_command': shell_command([sys.executable, str(SKILL / 'scripts' / 'tasks.py'), 'wait', '--work', str(work), '--timeout', '60'])[1],
            'errors': [{'id': j['id'], 'error': j['error'], 'attempt': j['attempt']} for j in state['jobs'].values() if j['status'] == 'invalid'],
            **({'report_path': str(work / '校对报告.html')} if phase == 'done' else {})}


def age_seconds(value, observed_at):
    if value is None:
        return None
    try:
        return max(0, round((observed_at - datetime.fromisoformat(value)).total_seconds(), 1))
    except (ValueError, TypeError):
        return None


def status_snapshot(work):
    """Observe receipts without reconciliation, allocation, locks, or writes."""
    state_path = work / 'task-state.json'
    if not state_path.exists():
        return {'initialized': False, 'phase': 'uninitialized', 'concurrency': None, 'jobs': [],
                'phases': [{'phase': k, 'status': 'not_planned', 'total': None, 'complete': None}
                           for k in ('proofread', 'consistency', 'review', 'report')]}
    state = wf.load(state_path)
    observed_at = datetime.now(timezone.utc)
    jobs = []
    for job in state['jobs'].values():
        evidence = execution_evidence(job)
        effective = job['status']
        response_exists = Path(job['response_path']).is_file()
        if effective in ('assigned', 'running'):
            if response_exists:
                effective = 'response_pending'
            elif evidence['opened_at'] is not None:
                effective = 'running'
        jobs.append({'id': job['id'], 'kind': job['kind'], 'pass_id': job.get('pass_id'),
                     'attempt': job['attempt'], 'executor': job['executor'], 'ticket': job['ticket'],
                     'saved_status': job['status'], 'status': effective,
                     'context_id': evidence['context_id'], 'context_source': evidence['context_source'],
                     'ticket_created_at': job.get('ticket_created_at'), 'assigned_at': job.get('assigned_at'),
                     'opened_at': evidence['opened_at'],
                     'ticket_age_seconds': age_seconds(job.get('ticket_created_at'), observed_at),
                     'assigned_age_seconds': age_seconds(job.get('assigned_at'), observed_at),
                     'open_age_seconds': age_seconds(evidence['opened_at'], observed_at),
                     **({'error': job['error']} if job.get('error') else {})})
    phase = ('done' if state.get('report_sha256') else 'review' if state.get('review_plan')
             else 'consistency' if state.get('merged') else 'proofread')
    phases = []
    for kind in ('proofread', 'consistency', 'review'):
        subset = [j for j in jobs if j['kind'] == kind]
        planned = (kind == 'proofread' and 'manifest_sha256' in state
                   or kind == 'consistency' and 'merged' in state
                   or kind == 'review' and 'review_plan' in state)
        total = None
        if planned:
            if kind == 'proofread':
                total = 2 * len(wf.load(work / 'batches' / 'manifest.json')['batches'])
            elif kind == 'consistency':
                payload = wf.load(work / 'consistency-input.json')
                total = int(bool(payload['required'] and payload['terms']))
            else:
                total = len(wf.load(work / 'review-input' / 'manifest.json')['batches'])
        complete = sum(j['status'] == 'complete' for j in subset) if planned else None
        skipped = sum(j['status'] == 'skipped' for j in subset) if planned else 0
        stage_status = ('finished_with_skips' if planned and skipped and total == complete + skipped else 'not_planned' if not planned else 'complete' if total == complete else 'in_progress')
        phases.append({'phase': kind, 'status': stage_status, 'total': total, 'complete': complete, 'skipped': skipped})
    phases.append({'phase': 'report', 'status': 'complete' if phase == 'done' else 'pending',
                   'total': 1, 'complete': int(phase == 'done')})
    return {'initialized': True, 'observed_at': observed_at.isoformat(), 'phase': phase,
            'concurrency': state['concurrency'], 'coordinator': state.get('coordinator'),
            'last_reconciliation': state.get('last_reconciliation'),
            'jobs': jobs, 'phases': phases, 'reconciliation_required': any(
                j['status'] != j['saved_status'] or j['status'] == 'response_pending' for j in jobs),
            'action': 'inspect_errors' if any(j['status'] == 'invalid' for j in jobs)
                      else 'coordinator_next' if any(j['status'] in ('pending', 'response_pending') for j in jobs)
                      else 'done' if phase == 'done'
                      else 'wait_or_confirm_interruption' if any(j['status'] in ('assigned', 'running') for j in jobs)
                      else 'coordinator_next',
            **({'report_path': str(work / '校对报告.html')} if phase == 'done' else {})}


def wait_for_change(work, timeout):
    """Read receipts only, never hold a coordinator lock while waiting."""
    report.require(0 <= timeout <= 60, 'timeout 须在 0 到 60 秒之间')
    deadline = time.monotonic() + timeout
    initial = None
    while True:
        snapshot = status_snapshot(work)
        # Starting a reserved worker consumes no new slot and needs no coordinator action.
        signature = [(j['id'], j['ticket'], 'active' if j['status'] in ('assigned', 'running') else j['status'])
                     for j in snapshot['jobs']]
        if snapshot.get('action') != 'wait_or_confirm_interruption' or (initial is not None and signature != initial):
            return {'action': 'step', 'instruction': '立即执行 step 接收结果并补充空闲槽位。'}
        initial = signature
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return {'action': 'wait', 'instruction': '仍在执行；继续等待任意完成事件或再次运行本命令，不把超时当作失败。'}
        time.sleep(min(0.5, remaining))


def main():
    parser = argparse.ArgumentParser(description='本地任务清单：脚本组织数据，宿主 Agent 调用子代理。next 会预留返回的任务。')
    commands = parser.add_subparsers(dest='command', required=True)
    nxt = commands.add_parser('next', aliases=['step'], help='step 提供主 Agent 的精简动作接口')
    nxt.add_argument('--work', required=True)
    nxt.add_argument('--coordinator', required=True, help='本协调会话的稳定真实标识')
    nxt.add_argument('--takeover', action='store_true', help='显式接管其他协调员，保留已分配/运行任务')
    nxt.add_argument('--concurrency', type=int)
    nxt.add_argument('--target-chars', type=int)
    nxt.add_argument('--max-chars', type=int)
    nxt.add_argument('--compact', action='store_true', help='精简待办输出，完整指令保存在任务文件')
    nxt.add_argument('--resume-assigned', action='store_true', help='重新交接已分配但尚未启动的任务，不消耗重查次数')
    retry = commands.add_parser('retry')
    retry.add_argument('--work', required=True)
    retry.add_argument('--coordinator', required=True)
    retry.add_argument('--takeover', action='store_true')
    retry.add_argument('--task', required=True)
    retry.add_argument('--fallback', action='store_true', help='旧参数兼容：跳过任务，不再由主 Agent 补做')
    skip = commands.add_parser('skip', help='确认任务已结束后跳过，不读取或补做内容')
    skip.add_argument('--work', required=True)
    skip.add_argument('--coordinator', required=True)
    skip.add_argument('--takeover', action='store_true')
    skip.add_argument('--task', required=True)
    partial = commands.add_parser('partial', help='一步生成标明未完成范围的 HTML 快照，不停止现有任务')
    partial.add_argument('--work', required=True)
    partial.add_argument('--coordinator', required=True)
    partial.add_argument('--takeover', action='store_true')
    submission = commands.add_parser('submit')
    submission.add_argument('--job', required=True)
    submission.add_argument('--body', required=True)
    opening = commands.add_parser('open', help='检查员领取任务；过期/重复任务立即返回 stop_no_work')
    opening.add_argument('--job', required=True)
    opening.add_argument('--context-id')
    opening.add_argument('--context-source', choices=('host-provided', 'agent-declared', 'unavailable'))
    opening.add_argument('--brief', action='store_true', help='只返回本角色的执行指令，不返回内部票据和审计字段')
    waiting = commands.add_parser('wait', help='最多等待 60 秒，任意任务状态可推进时提前返回；不分配任务')
    waiting.add_argument('--work', required=True)
    waiting.add_argument('--timeout', type=float, default=60)
    status = commands.add_parser('status', help='只读状态，不领取任务、不推进阶段、不校验原始来源')
    status.add_argument('--work', required=True)
    status.add_argument('--compact', action='store_true')
    args = parser.parse_args()
    simple = args.command == 'step'
    if simple:
        args.command = 'next'
        args.compact = True
    try:
        if args.command == 'open':
            opened = open_job(args.job, args.context_id, args.context_source)
            if args.brief and opened['action'] == 'execute':
                opened = {'action': 'execute', 'instructions': opened['instructions']}
            print(json.dumps(opened, ensure_ascii=False, indent=2))
            return 0
        if args.command == 'submit':
            submit(args.job, args.body)
            return 0
        if args.command == 'wait':
            print(json.dumps(wait_for_change(Path(args.work).resolve(), args.timeout), ensure_ascii=False))
            return 0
        if args.command == 'status':
            print(json.dumps(status_snapshot(Path(args.work).resolve()), ensure_ascii=False,
                             indent=None if args.compact else 2))
            return 0
        if args.command == 'next' and args.concurrency is not None:
            report.require(args.concurrency > 0, 'concurrency 必须为正整数')
        work = Path(args.work).resolve()
        report.require(work != SKILL and SKILL not in work.parents, '工作目录不能位于技能包内')
        document = wf.load(work / 'document.json')
        report.document_units(document)
        provenance.verify(document)
        with coordinator_lock(work):
            state_path = work / 'task-state.json'
            if state_path.exists():
                state = wf.load(state_path)
                # Reject another owner before writes, even when an unfinished
                # initialization or retry needs deterministic recovery.
                claim_coordinator(work, state, args.coordinator, args.takeover)
                save(state_path, state, True)
                report.require(state['document_sha256'] == wf.sha(document), '原文版本变化，请使用新工作目录')
                report.require(state['rules_sha256'] == wf.rules_sha(), '判定规则变化，请使用新工作目录')
                if args.command == 'next':
                    for option in ('target_chars', 'max_chars'):
                        requested = getattr(args, option)
                        report.require(requested is None or requested == state[option], '已启动工作区不能修改批次大小，请新建工作目录')
            else:
                report.require(args.command == 'next', '任务尚未初始化')
                reserved = ('batches', 'jobs', 'responses', 'staging', 'results', 'merged.json',
                            'consistency-input.json', 'consistency-result.json', 'review-input',
                            'review-results', 'review.json', '校对报告.html')
                report.require(not any((work / name).exists() for name in reserved),
                               '工作目录已有其他流程产物；请使用仅含本次来源与 document.json 的新工作目录')
                target_chars = args.target_chars if args.target_chars is not None else 1600
                max_chars = args.max_chars if args.max_chars is not None else 2000
                report.require(0 < target_chars <= max_chars, '字符阈值须满足 0 < target-chars <= max-chars')
                state = {'document_sha256': wf.sha(document), 'rules_sha256': wf.rules_sha(), 'jobs': {},
                         'concurrency': 4, 'target_chars': target_chars, 'max_chars': max_chars}
                claim_coordinator(work, state, args.coordinator, args.takeover)
                save(state_path, state)
            if 'manifest_sha256' not in state:
                invoke(wf.batch_command, document=str(work / 'document.json'), output_dir=str(work / 'batches'),
                       target_chars=state['target_chars'], max_chars=state['max_chars'], context_units=1)
                state['manifest_sha256'] = wf.sha(wf.load(work / 'batches' / 'manifest.json'))
                save(state_path, state, True)
            manifest = wf.load(work / 'batches' / 'manifest.json')
            wf.validate_manifest(document, manifest)
            report.require(state['manifest_sha256'] == wf.sha(manifest), '批次清单发生变化')
            for batch in manifest['batches']:
                for pid in ('A', 'B'):
                    create_job(work, state, pid + '-' + batch['id'], 'proofread', work / 'batches' / batch['file'],
                               work / 'results' / pid / (batch['id'] + '.json'), pid)
            if args.command == 'partial':
                try:
                    result = partial_report(work, state, document, manifest)
                finally:
                    save(state_path, state, True)
                print(json.dumps(result, ensure_ascii=False))
                return 0
            if args.command in ('retry', 'skip'):
                report.require(args.task in state['jobs'], '未知任务')
                job = state['jobs'][args.task]
                # Accept an already-published valid result before considering retry/skip.
                reconcile(work, state, document, manifest)
                report.require(job['status'] in ('invalid', 'running', 'assigned', 'skipped', 'complete'),
                               '只允许恢复失败或被中断的任务')
                if job['status'] == 'complete':
                    result = {'action': 'already_complete', 'task': args.task}
                elif job['status'] == 'skipped' or args.command == 'skip' or args.fallback or job['attempt'] >= 2:
                    if job['status'] != 'skipped':
                        skip_job(job, '执行失败，已跳过' if args.command == 'skip' or args.fallback else '重查次数已用尽')
                    result = {'action': 'skipped', 'task': args.task,
                              'instruction': '执行 step 继续调度；主 Agent 不读取或补做本任务内容。'}
                else:
                    job.update(status='pending', attempt=job['attempt'] + 1)
                    prepare_attempt(work, job)
                    result = {'action': 'retry', 'retry': args.task, 'executor': job['executor']}
                save(state_path, state, True)
                print(json.dumps(result, ensure_ascii=False))
                return 0
            if args.concurrency is not None:
                report.require(args.concurrency > 0, 'concurrency 必须为正整数')
                state['concurrency'] = args.concurrency
            try:
                newly_complete = reconcile(work, state, document, manifest)
                phase = advance(work, state, document, manifest)
                result = next_tasks(work, state, phase, args.compact, args.resume_assigned)
            finally:
                save(state_path, state, state_path.exists())
            snapshot = status_snapshot(work)
            result.update(pipeline=snapshot['phases'], coordinator=state['coordinator']['id'],
                          accepted_this_step=len(newly_complete),
                          next_action='dispatch_ready' if result['ready'] else 'resolve_errors' if result['errors']
                          else 'deliver_report' if phase == 'done' else 'wait_for_workers')
            print(json.dumps(simple_step(result) if simple else result,
                             ensure_ascii=False, indent=None if args.compact else 2))
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print('错误：' + str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
