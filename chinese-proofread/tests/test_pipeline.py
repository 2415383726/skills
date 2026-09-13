"""Offline protocol regression tests. Fixtures do not measure model accuracy."""
import concurrent.futures
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SKILL = Path(__file__).resolve().parent.parent


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='gongwen-pipeline-')
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.skill = SKILL
        self.work = self.base / 'work'
        self.work.mkdir()

    def command(self, script, *args, ok=True):
        completed = subprocess.run(
            [sys.executable, str(self.skill / 'scripts' / script), *map(str, args)],
            capture_output=True, text=True,
            env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
        if ok:
            self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        else:
            self.assertNotEqual(completed.returncode, 0)
        return completed

    def prepare(self, text):
        source = self.work / 'source.txt'
        source.write_text(text, encoding='utf-8')
        self.command('report.py', 'prepare', '--input', source,
                     '--output', self.work / 'document.json')

    def step(self, *extra):
        return json.loads(self.command('tasks.py', 'step', '--work', self.work,
                                      '--coordinator', 'test-coordinator', *extra).stdout)

    def metadata(self, task):
        state = json.loads((self.work / 'task-state.json').read_text())
        return json.loads(Path(state['jobs'][task['id']]['job_path']).read_text())

    def body(self, metadata, rule='T-TYPO'):
        payload = json.loads(Path(metadata['input_path']).read_text())
        if metadata['kind'] == 'proofread':
            candidates = [dict(severity='confirmed', rule_id=rule, category='错别字',
                               reason='表示安排工作，应为部署。',
                               anchors=[dict(block_id=unit['id'], quote='部暑')], suggestion='部署')
                          for unit in payload['main_units'] if '部暑' in unit['text']]
            terms = ([{'text': '综合处', 'kind': '机构名称'}]
                     if any('综合处' in u['text'] for u in payload['main_units']) else [])
            return dict(completed=True, candidates=candidates, terms=terms, limitations=[])
        if metadata['kind'] == 'consistency':
            return dict(checked=True, candidates=[], limitations=[])
        return dict(group_decisions=[dict(group_id=g['id'], accept=[c['id'] for c in g['candidates']],
                                         explanations={c['id']: '安排工作应写作“部署”。' for c in g['candidates']})
                                     for g in payload['candidate_groups']], limitations=[])

    def open_body(self, task, rule='T-TYPO'):
        metadata = self.metadata(task)
        job_path = json.loads((self.work / 'task-state.json').read_text())['jobs'][task['id']]['job_path']
        opened = json.loads(self.command('tasks.py', 'open', '--job', job_path, '--brief').stdout)
        self.assertEqual(opened['action'], 'execute')
        self.assertEqual(set(opened), {'action', 'instructions'})
        self.assertIn(metadata['input_path'], opened['instructions'])
        body_path = Path(metadata['response_path'] + '.body')
        body_path.write_text(json.dumps(self.body(metadata, rule), ensure_ascii=False), encoding='utf-8')
        return job_path, body_path

    def complete(self, task, rule='T-TYPO'):
        job_path, body_path = self.open_body(task, rule)
        return json.loads(self.command('tasks.py', 'submit', '--job', job_path, '--body', body_path).stdout)

    def partial(self):
        result = json.loads(self.command('tasks.py', 'partial', '--work', self.work,
                                        '--coordinator', 'test-coordinator').stdout)
        path = Path(result['report_path'])
        self.assertTrue(path.is_file())
        return path, json.loads((path.parent / 'review.json').read_text())

    def test_zero_findings_renders_on_last_submit(self):
        self.prepare('请各单位按时报送材料。')
        dispatch = self.step('--concurrency', '2')
        self.assertEqual(dispatch['action'], 'dispatch')
        self.assertEqual(len(dispatch['tasks']), 2)
        self.complete(dispatch['tasks'][0])
        self.assertFalse((self.work / '校对报告.html').exists())
        result = self.complete(dispatch['tasks'][1])
        self.assertEqual(result['phase'], 'done')
        self.assertTrue(Path(result['report_path']).is_file())
        self.assertEqual(self.step()['action'], 'deliver')
        review = json.loads((self.work / 'review.json').read_text())
        self.assertEqual(review['findings'], [])
        self.assertEqual(review['passes'][0]['checked_block_ids'], ['p1'])

    def test_review_required_and_partial_never_promotes_unreviewed(self):
        self.prepare('请尽快部暑下一阶段工作。')
        for task in self.step()['tasks']:
            self.complete(task)
        self.assertFalse((self.work / '校对报告.html').exists())
        partial, review = self.partial()
        self.assertEqual(review['findings'], [])
        self.assertTrue(any('缺少候选复核结果' in note for note in review['limitations']))
        self.assertTrue(any('部分交付快照' in note for note in review['limitations']))
        self.assertIn('尚未完成复核', partial.read_text())
        dispatch = self.step()
        self.assertEqual(dispatch['phase'], 'review')
        result = self.complete(dispatch['tasks'][0])
        self.assertEqual(result['phase'], 'done')
        review = json.loads((self.work / 'review.json').read_text())
        self.assertEqual(len(review['findings']), 1)
        self.assertEqual(review['findings'][0]['suggestion'], '部署')

    def test_partial_before_any_submission_is_honest(self):
        self.prepare('请尽快部暑下一阶段工作。')
        self.step()
        path, review = self.partial()
        self.assertEqual(review['findings'], [])
        self.assertTrue(all(not p['checked_block_ids'] for p in review['passes']))
        self.assertIn('尚无完成的检查记录', path.read_text())
        self.assertNotEqual(self.step()['action'], 'deliver')

    def test_invalid_anchor_can_be_corrected_without_restarting(self):
        self.prepare('请尽快部暑下一阶段工作。')
        task = self.step()['tasks'][0]
        job, body_path = self.open_body(task)
        valid = body_path.read_text()
        body = json.loads(valid)
        body['candidates'][0]['anchors'][0]['quote'] = '不存在的片段'
        body_path.write_text(json.dumps(body, ensure_ascii=False))
        failed = self.command('tasks.py', 'submit', '--job', job, '--body', body_path, ok=False)
        self.assertIn('不存在于原文', failed.stderr)
        self.assertFalse(Path(self.metadata(task)['response_path']).exists())
        body_path.write_text(valid)
        self.command('tasks.py', 'submit', '--job', job, '--body', body_path)
        state = json.loads((self.work / 'task-state.json').read_text())
        self.assertEqual(state['jobs'][task['id']]['attempt'], 1)
        self.assertEqual(state['jobs'][task['id']]['status'], 'complete')

    def test_eight_parallel_submissions_and_consistency(self):
        self.prepare('\n'.join('综合处负责报送材料。' + '各单位应认真核对相关内容。' * 100 for _ in range(4)))
        dispatch = self.step()
        self.assertEqual(dispatch['concurrency'], 8)
        self.assertEqual(len(dispatch['tasks']), 8)
        calls = [self.open_body(task) for task in dispatch['tasks']]
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(self.command, 'tasks.py', 'submit', '--job', job, '--body', body)
                       for job, body in calls]
            for future in concurrent.futures.as_completed(futures):
                self.assertTrue(json.loads(future.result().stdout)['submitted'])
        next_step = self.step()
        self.assertEqual(next_step['phase'], 'consistency')
        self.assertEqual(len(next_step['tasks']), 1)
        result = self.complete(next_step['tasks'][0])
        self.assertEqual(result['phase'], 'done')
        state = json.loads((self.work / 'task-state.json').read_text())
        self.assertTrue(all(j['status'] == 'complete' for j in state['jobs'].values()))
        self.assertEqual(state['coordinator']['id'], 'test-coordinator')

    def test_refill_does_not_wait_for_pair_and_lowering_limit_is_safe(self):
        self.prepare('\n'.join('各单位应认真核对相关内容。' * 100 for _ in range(4)))
        first = self.step('--concurrency', '2')['tasks']
        self.complete(first[0])
        refill = self.step()
        self.assertEqual(refill['action'], 'dispatch')
        self.assertEqual(len(refill['tasks']), 1)
        self.assertNotEqual(refill['tasks'][0]['id'], first[1]['id'])
        lower = self.step('--concurrency', '1')
        self.assertEqual(lower['action'], 'wait')
        self.assertEqual(len(lower['waiting_for']), 2)
        self.complete(first[1])
        self.assertEqual(self.step()['action'], 'wait')
        self.complete(refill['tasks'][0])
        next_step = self.step()
        self.assertEqual(next_step['concurrency'], 1)
        self.assertEqual(len(next_step['tasks']), 1)

    def test_repeated_open_stops_and_delivery_checks_actual_report(self):
        self.prepare('请各单位按时报送材料。')
        tasks = self.step()['tasks']
        job, body = self.open_body(tasks[0])
        repeated = json.loads(self.command('tasks.py', 'open', '--job', job, '--brief').stdout)
        self.assertEqual(repeated['action'], 'stop_no_work')
        self.command('tasks.py', 'submit', '--job', job, '--body', body)
        self.complete(tasks[1])
        (self.work / '校对报告.html').write_text('broken')
        failed = self.command('tasks.py', 'step', '--work', self.work,
                              '--coordinator', 'test-coordinator', ok=False)
        self.assertIn('报告文件已变化', failed.stderr)

    def test_partial_preserves_completed_review_batches(self):
        self.prepare('\n'.join('第%d项工作需要及时部暑。' % i for i in range(30)))
        for task in self.step()['tasks']:
            self.complete(task)
        tasks = self.step()['tasks']
        self.assertEqual(len(tasks), 2)
        self.complete(tasks[0])
        _, review = self.partial()
        payload = json.loads(Path(self.metadata(tasks[0])['input_path']).read_text())
        expected = {c['anchors'][0]['block_id'] for g in payload['candidate_groups'] for c in g['candidates']}
        self.assertEqual({f['anchors'][0]['block_id'] for f in review['findings']}, expected)
        self.assertFalse((self.work / '校对报告.html').exists())
        self.complete(tasks[1])
        review = json.loads((self.work / 'review.json').read_text())
        self.assertEqual(len(review['findings']), 30)

    def test_new_rule_uses_configuration_without_pipeline_changes(self):
        self.skill = self.base / 'skill-copy'
        shutil.copytree(SKILL, self.skill)
        catalog = self.skill / 'references' / 'rule-catalog.json'
        data = json.loads(catalog.read_text())
        data['T-LOCAL'] = {'requires_necessity': False}
        catalog.write_text(json.dumps(data))
        self.prepare('请尽快部暑下一阶段工作。')
        for task in self.step()['tasks']:
            self.complete(task, rule='T-LOCAL')
        for task in self.step()['tasks']:
            self.complete(task)
        self.assertEqual(self.step()['action'], 'deliver')
        # Changing quality instructions cannot silently resume a completed run.
        rules = self.skill / 'references' / 'rules.md'
        rules.write_text(rules.read_text() + '\n新的规则版本。\n')
        failed = self.command('tasks.py', 'step', '--work', self.work,
                              '--coordinator', 'test-coordinator', ok=False)
        self.assertIn('规则变化', failed.stderr)

    def test_render_failure_preserves_submission_and_step_can_recover(self):
        self.skill = self.base / 'skill-copy'
        shutil.copytree(SKILL, self.skill)
        self.prepare('请各单位按时报送材料。')
        tasks = self.step()['tasks']
        self.complete(tasks[0])
        template = self.skill / 'assets' / 'report.html'
        original = template.read_text()
        template.write_text(original.replace('@@TITLE@@', '@@UNKNOWN@@'))
        result = self.complete(tasks[1])
        self.assertTrue(result['submitted'])
        self.assertEqual(result['action'], 'coordinator_step')
        self.assertFalse((self.work / '校对报告.html').exists())
        template.write_text(original)
        self.assertEqual(self.step()['action'], 'deliver')

    def recover(self, task, command='retry', *extra):
        return json.loads(self.command('tasks.py', command, '--work', self.work,
                         '--coordinator', 'test-coordinator', '--task', task['id'], *extra).stdout)

    def test_retry_exhaustion_skips_and_other_pass_finishes(self):
        self.prepare('请尽快部暑下一阶段工作。')
        first, other = self.step()['tasks']
        self.assertEqual(self.recover(first)['action'], 'retry')
        retried = self.step()['tasks'][0]
        old_job, old_body = self.open_body(retried)
        self.assertEqual(self.recover(retried)['action'], 'skipped')
        self.command('tasks.py', 'submit', '--job', old_job, '--body', old_body, ok=False)
        self.complete(other)
        for task in self.step()['tasks']:
            self.assertEqual(task['launch_mode'], 'spawn_fresh_context')
            self.complete(task)
        self.assertEqual(self.step()['action'], 'deliver')
        review = json.loads((self.work / 'review.json').read_text())
        self.assertEqual(len(review['findings']), 1)
        self.assertEqual(review['passes'][0]['checked_block_ids'], [])
        html = (self.work / '校对报告.html').read_text()
        self.assertIn('部分原文尚未完成检查', html)
        self.assertIn('href="#unit-p1"', html)

    def test_legacy_fallback_skips_all_without_fake_success(self):
        self.prepare('请各单位按时报送材料。')
        for task in self.step()['tasks']:
            self.assertEqual(self.recover(task, 'retry', '--fallback')['action'], 'skipped')
        self.assertEqual(self.step()['action'], 'deliver')
        review = json.loads((self.work / 'review.json').read_text())
        self.assertTrue(all(not p['checked_block_ids'] for p in review['passes']))
        state = json.loads((self.work / 'task-state.json').read_text())
        self.assertTrue(all(j['status'] == 'skipped' and j['executor'] == 'subagent'
                            for j in state['jobs'].values()))

    def test_skipped_review_keeps_other_reviewed_findings(self):
        self.prepare('\n'.join('第%d项工作需要及时部暑。' % i for i in range(30)))
        for task in self.step()['tasks']:
            self.complete(task)
        tasks = self.step()['tasks']
        self.complete(tasks[0])
        self.recover(tasks[1], 'skip')
        self.assertEqual(self.step()['action'], 'deliver')
        review = json.loads((self.work / 'review.json').read_text())
        payload = json.loads(Path(self.metadata(tasks[0])['input_path']).read_text())
        expected = {c['anchors'][0]['block_id'] for g in payload['candidate_groups'] for c in g['candidates']}
        self.assertEqual({f['anchors'][0]['block_id'] for f in review['findings']}, expected)
        self.assertIn('部分修改点尚未完成复核', (self.work / '校对报告.html').read_text())

    def test_skipped_consistency_does_not_block_review(self):
        self.prepare('综合处负责部暑任务。\n综合处负责报送材料。')
        for task in self.step('--target-chars', '8', '--max-chars', '12')['tasks']:
            self.complete(task)
        task = self.step()['tasks'][0]
        self.assertEqual(task['id'], 'consistency')
        self.recover(task, 'skip')
        for task in self.step()['tasks']:
            self.complete(task)
        self.assertEqual(self.step()['action'], 'deliver')
        self.assertIn('全文名称一致性检查尚未完成', (self.work / '校对报告.html').read_text())


    def test_wait_returns_without_treating_timeout_as_failure(self):
        self.prepare('请各单位按时报送材料。')
        tasks = self.step()['tasks']
        result = json.loads(self.command('tasks.py', 'wait', '--work', self.work, '--timeout', '0').stdout)
        self.assertEqual(result['action'], 'wait')
        for task in tasks:
            self.complete(task)
        result = json.loads(self.command('tasks.py', 'wait', '--work', self.work, '--timeout', '20').stdout)
        self.assertEqual(result['action'], 'step')

    def test_report_marks_only_changed_characters_and_uses_source_location(self):
        self.prepare('请尽快部暑下一阶段工作。')
        for task in self.step()['tasks']:
            self.complete(task)
        for task in self.step()['tasks']:
            self.complete(task)
        html = (self.work / '校对报告.html').read_text()
        self.assertIn('部<del>暑</del>', html)
        self.assertIn('部<ins>署</ins>', html)
        self.assertNotIn('复核确认此处', html)
        self.assertIn('title="原文第1行">原文第1行</span>', html)

if __name__ == '__main__':
    unittest.main()
