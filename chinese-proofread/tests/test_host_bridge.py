"""Host handles, real event deduplication and coordinator identity ownership."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import test_pipeline


class HostBridgeTests(unittest.TestCase):
    def setUp(self):
        self.p=test_pipeline.PipelineTests();self.p.setUp()
        self.addCleanup(self.p.doCleanups)
        self.p.prepare('\n'.join('各单位认真核对材料。'*100 for _ in range(4)))

    def test_identity_file_is_stable_without_impersonating_another_owner(self):
        p=self.p;identity=p.base/'identity.json'
        p.command('host_bridge.py','identity','--output',identity)
        first=json.loads(p.command('tasks.py','step','--work',p.work,'--coordinator-file',identity,'--concurrency','1').stdout)
        self.assertEqual(first['action'],'dispatch')
        self.assertEqual(json.loads(p.command('tasks.py','step','--work',p.work,'--coordinator-file',identity).stdout)['action'],'wait')
        second=p.base/'second.json';p.command('host_bridge.py','identity','--output',second)
        p.command('tasks.py','step','--work',p.work,'--coordinator-file',second,ok=False)
        p.command('host_bridge.py','identity','--output',identity,ok=False)

    def test_bound_unopened_worker_is_not_automatically_replayed(self):
        p=self.p;task=p.step('--concurrency','1')['tasks'][0]
        p.command('host_bridge.py','bind','--work',p.work,'--coordinator','test-coordinator','--event',task['event'],'--handle','host-1')
        self.assertEqual(p.step('--resume-assigned')['action'],'wait')
        snapshot=json.loads(p.command('tasks.py','status','--work',p.work,'--compact').stdout)
        current=next(j for j in snapshot['jobs'] if j['id']==task['id'])
        self.assertEqual(current['host_handle'],'host-1')
        p.command('host_bridge.py','release','--work',p.work,'--coordinator','test-coordinator',
                  '--event',task['event'],'--confirmed-not-running')
        self.assertEqual(p.step('--resume-assigned')['tasks'][0]['id'],task['id'])

    def test_message_and_finished_events_only_allocate_once(self):
        p=self.p;task=p.step('--concurrency','1')['tasks'][0]
        p.command('host_bridge.py','bind','--work',p.work,'--coordinator','test-coordinator','--event',task['event'],'--handle','host-1')
        p.complete(task)
        first=p.step('--event',task['event'])
        self.assertEqual(first['action'],'dispatch')
        before=json.loads((p.work/'task-state.json').read_text())
        duplicate=p.step('--event',task['event'])
        self.assertEqual(duplicate['action'],'ignore_event')
        self.assertEqual(duplicate['reservations'][0]['id'],first['tasks'][0]['id'])
        after=json.loads((p.work/'task-state.json').read_text())
        self.assertEqual(before['jobs'],after['jobs'])
        lookup=json.loads(p.command('host_bridge.py','lookup','--work',p.work,'--handle','host-1').stdout)
        self.assertTrue(lookup['handled'])

    def test_old_attempt_does_not_consume_new_attempt_event(self):
        p=self.p;task=p.step('--concurrency','1')['tasks'][0]
        p.command('tasks.py','retry','--work',p.work,'--coordinator','test-coordinator','--task',task['id'])
        replacement=p.step()['tasks'][0]
        self.assertNotEqual(task['event'],replacement['event'])
        self.assertEqual(p.step('--event',task['event'])['action'],'ignore_event')
        p.complete(replacement)
        self.assertEqual(p.step('--event',replacement['event'])['events'][0]['disposition'],'new')

    def test_end_notification_without_receipt_requests_inspection(self):
        p=self.p;task=p.step('--concurrency','1')['tasks'][0]
        answer=p.step('--event',task['event'])
        self.assertEqual(answer['action'],'repair')
        state=json.loads((p.work/'task-state.json').read_text())
        self.assertNotIn(task['event'],state.get('handled_events',[]))
        self.assertEqual(state['jobs'][task['id']]['status'],'assigned')

    def test_multiple_completed_notifications_are_coalesced(self):
        p=self.p;tasks=p.step('--concurrency','2')['tasks']
        for task in tasks:p.complete(task)
        answer=p.step('--event',tasks[0]['event'],'--event',tasks[1]['event'],'--event',tasks[0]['event'])
        self.assertEqual(len(answer['events']),2)
        self.assertEqual(len(answer['tasks']),2)
        self.assertEqual(p.step('--event',tasks[0]['event'],'--event',tasks[1]['event'])['action'],'ignore_event')

    def test_bound_running_worker_cannot_be_released(self):
        p=self.p;task=p.step('--concurrency','1')['tasks'][0]
        p.command('host_bridge.py','bind','--work',p.work,'--coordinator','test-coordinator','--event',task['event'],'--handle','host-1')
        p.open_body(task)
        p.command('host_bridge.py','release','--work',p.work,'--coordinator','test-coordinator',
                  '--event',task['event'],'--confirmed-not-running',ok=False)
        p.command('host_bridge.py','bind','--work',p.work,'--coordinator','someone-else',
                  '--event',task['event'],'--handle','host-2',ok=False)

    def test_batch_bind_is_atomic_and_accepts_fast_completed_worker(self):
        p=self.p;tasks=p.step('--concurrency','2')['tasks']
        p.complete(tasks[0])
        bindings=p.base/'bindings.json'
        bindings.write_text(json.dumps([{'event':t['event'],'handle':'handle-'+str(i)} for i,t in enumerate(tasks)]))
        p.command('host_bridge.py','bind-many','--work',p.work,'--coordinator','test-coordinator','--bindings',bindings)
        saved=(p.work/'host-tasks.json').read_bytes()
        lookup=json.loads(p.command('host_bridge.py','lookup','--work',p.work,'--handle','handle-0').stdout)
        self.assertEqual(lookup['event'],tasks[0]['event'])
        bindings.write_text(json.dumps([{'event':tasks[0]['event'],'handle':'handle-0'},
                                        {'event':tasks[1]['event'],'handle':'handle-0'}]))
        p.command('host_bridge.py','bind-many','--work',p.work,'--coordinator','test-coordinator','--bindings',bindings,ok=False)
        self.assertEqual((p.work/'host-tasks.json').read_bytes(),saved)

    def test_old_handle_resolves_old_event_after_retry(self):
        p=self.p;task=p.step('--concurrency','1')['tasks'][0]
        p.command('host_bridge.py','bind','--work',p.work,'--coordinator','test-coordinator','--event',task['event'],'--handle','old-handle')
        p.command('tasks.py','retry','--work',p.work,'--coordinator','test-coordinator','--task',task['id'])
        new=p.step()['tasks'][0]
        p.command('host_bridge.py','bind','--work',p.work,'--coordinator','test-coordinator','--event',new['event'],'--handle','new-handle')
        old=json.loads(p.command('host_bridge.py','lookup','--work',p.work,'--handle','old-handle').stdout)
        self.assertEqual(old['event'],task['event'])
        self.assertEqual(p.step('--event',old['event'])['events'][0]['disposition'],'stale')
