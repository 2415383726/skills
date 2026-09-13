"""Coordinator waits should wake for useful work, not worker startup."""
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))
import tasks


class WaitTests(unittest.TestCase):
    def test_start_does_not_wake_but_completion_does(self):
        def snapshot(status):
            return {'action': 'wait_or_confirm_interruption',
                    'jobs': [{'id': 'A-1', 'ticket': 'ticket', 'status': status}]}
        with patch.object(tasks, 'status_snapshot', side_effect=[snapshot('assigned'), snapshot('running'), snapshot('complete')]) as read:
            with patch.object(tasks.time, 'sleep'):
                result = tasks.wait_for_change(Path('/unused'), 60)
        self.assertEqual(result['action'], 'step')
        self.assertEqual(read.call_count, 3)

    def test_reserved_slots_are_not_reported_as_free(self):
        result = tasks.simple_step({'next_action': 'dispatch_ready', 'phase': 'proofread',
            'concurrency': 4, 'ready': [{'id': 'new'}],
            'running': ['one', 'two', 'three'], 'assigned': ['new']})
        self.assertEqual(result['capacity'], {'limit': 4, 'occupied': 4, 'available': 0})
        self.assertEqual(len(result['tasks']), 1)


class WaitIntegrationTests(unittest.TestCase):
    def setUp(self):
        import test_pipeline
        self.p = test_pipeline.PipelineTests()
        self.p.setUp()
        self.addCleanup(self.p.doCleanups)
        self.p.prepare('\n'.join('各单位应认真核对相关内容。' * 100 for _ in range(6)))

    def test_full_slots_with_queued_work_really_waits_then_refills(self):
        import time
        first = self.p.step('--concurrency', '2')
        started = time.monotonic()
        answer = tasks.wait_for_change(self.p.work, 0.02)
        self.assertEqual(answer['action'], 'wait')
        self.assertGreaterEqual(time.monotonic() - started, 0.015)
        self.p.complete(first['tasks'][0])
        self.assertEqual(tasks.wait_for_change(self.p.work, 0)['action'], 'step')
        refill = self.p.step()
        self.assertEqual(len(refill['tasks']), 1)
        self.assertEqual(refill['tasks'][0]['launch_mode'], 'spawn_fresh_context')
        self.assertNotIn('action', refill['tasks'][0])
        self.assertTrue(refill['progress'])

    def test_unopened_reservation_is_visible_and_recoverable(self):
        import json
        from datetime import datetime, timedelta, timezone
        first = self.p.step('--concurrency', '2')
        path = self.p.work / 'task-state.json'
        state = json.loads(path.read_text())
        job = state['jobs'][first['tasks'][0]['id']]
        job['assigned_at'] = (datetime.now(timezone.utc) - timedelta(seconds=100)).isoformat()
        path.write_text(json.dumps(state))
        answer = tasks.wait_for_change(self.p.work, 0)
        self.assertEqual(answer['action'], 'repair')
        self.assertEqual(answer['stalled'][0]['id'], job['id'])
        self.assertEqual(self.p.step()['action'], 'repair')
        # Open the other worker: recovery must not hand it out again.
        other = state['jobs'][first['tasks'][1]['id']]
        self.p.command('tasks.py', 'open', '--job', other['job_path'], '--brief')
        recovered = self.p.step('--resume-assigned')
        self.assertEqual([t['id'] for t in recovered['tasks']], [job['id']])
        self.p.complete(recovered['tasks'][0])
        self.assertFalse(self.p.step()['stalled'])

    def test_skip_notes_survive_compact_delivery(self):
        result = tasks.simple_step({'next_action': 'deliver_report', 'phase': 'done',
            'concurrency': 8, 'report_path': '/unused/report.html',
            'notes': ['consistency：名称索引超出输入预算'], 'pipeline': []})
        self.assertIn('名称索引超出输入预算', result['notes'][0])

    def test_step_help_uses_public_command(self):
        result = self.p.command('tasks.py', 'step', '--help')
        self.assertIn('tasks.py step', result.stdout)

    def test_real_skip_is_visible_during_dispatch_and_wait(self):
        first = self.p.step('--concurrency', '1')
        self.p.command('tasks.py', 'skip', '--work', self.p.work,
                       '--coordinator', 'test-coordinator', '--task', first['tasks'][0]['id'])
        dispatch = self.p.step()
        self.assertTrue(any(first['tasks'][0]['id'] in note for note in dispatch['notes']))
        waiting = tasks.wait_for_change(self.p.work, 0)
        self.assertEqual(waiting['action'], 'wait')
        self.assertEqual(waiting['notes'], dispatch['notes'])
