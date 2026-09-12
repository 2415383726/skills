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
