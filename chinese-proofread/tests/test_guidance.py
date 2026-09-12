"""Role routing and isolation invariants; no model quality claims."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import guidance
import workflow as wf
import review_benchmark
import test_pipeline


class GuidanceTests(unittest.TestCase):
    def setUp(self):
        self.pipeline = test_pipeline.PipelineTests()
        self.pipeline.setUp()
        self.addCleanup(self.pipeline.doCleanups)

    def payload(self, rule, before='部暑', after='部署'):
        return {'candidate_groups': [{'id': 'group-1', 'candidates': [
            {'id': 'candidate-1', 'rule_id': rule, 'anchors': [{'block_id':'p1','quote':before}], 'suggestion':after}]}]}

    def test_consistency_does_not_receive_other_roles_or_text_rules(self):
        text, files = guidance.compose('consistency')
        self.assertIn('checks/names.md', files)
        self.assertNotIn('checks/text.md', files)
        self.assertNotIn('checks/punctuation.md', files)
        self.assertNotIn('roles/review.md', files)
        self.assertNotIn('accept', text)

    def test_initial_checks_all_language_without_review_instructions(self):
        _, files = guidance.compose('proofread')
        self.assertIn('checks/text.md', files)
        self.assertIn('checks/punctuation.md', files)
        self.assertNotIn('roles/review.md', files)
        self.assertNotIn('checks/names.md', files)

    def test_review_uses_actual_edit_as_well_as_declared_rule(self):
        _, files = guidance.compose('review', self.payload('T-TYPO','?','？'))
        self.assertIn('checks/punctuation.md', files)
        _, files = guidance.compose('review', self.payload('P-CN'))
        self.assertIn('checks/text.md', files)
        _, files = guidance.compose('review', self.payload('LOCAL-NEW'))
        self.assertTrue(all('checks/'+d+'.md' in files for d in guidance.DOMAINS))

    def test_plain_typo_review_excludes_name_and_punctuation_domains(self):
        _, files = guidance.compose('review', self.payload('T-TYPO'))
        self.assertIn('checks/text.md', files)
        self.assertNotIn('checks/punctuation.md', files)
        self.assertNotIn('checks/names.md', files)

    def test_chat_packet_omits_file_result_schema(self):
        _, files = guidance.compose('proofread', chat=True)
        self.assertNotIn('formats/proofread.md', files)
        self.assertIn('roles/chat.md', files)

    def test_task_packet_tampering_is_rejected(self):
        p=self.pipeline
        p.prepare('请按时报送。')
        task=p.step()['tasks'][0]
        meta=p.metadata(task)
        path=Path(meta['guidance_path'])
        path.write_text(path.read_text()+'\nchanged')
        state=json.loads((p.work/'task-state.json').read_text())
        result=p.command('tasks.py','open','--job',state['jobs'][task['id']]['job_path'],'--brief',ok=False)
        self.assertIn('任务指引发生变化',result.stderr)

    def test_prefilled_initial_draft_cannot_claim_completion(self):
        p=self.pipeline
        p.prepare('请部暑。')
        task=p.step()['tasks'][0]
        meta=p.metadata(task)
        state=json.loads((p.work/'task-state.json').read_text())
        result=p.command('tasks.py','submit','--job',state['jobs'][task['id']]['job_path'],
                         '--body',meta['response_path']+'.body',ok=False)
        self.assertIn('完整',result.stderr)

    def test_review_draft_does_not_silently_reject_candidates(self):
        body=guidance.draft('review',self.payload('T-TYPO'))
        doc={'title':'test','source_name':'test','scope':'all','limitations':[],
             'blocks':[{'id':'p1','kind':'paragraph','location':'1','text':'部暑'}]}
        _,notes=wf.review_decisions(doc,self.payload('T-TYPO'),body)
        self.assertTrue(notes)

    def test_review_cannot_reuse_initial_context_identity(self):
        p=self.pipeline
        p.prepare('请部暑。')
        tasks=p.step()['tasks']
        state=json.loads((p.work/'task-state.json').read_text())
        meta=p.metadata(tasks[0]); job=state['jobs'][tasks[0]['id']]['job_path']
        p.command('tasks.py','open','--job',job,'--context-id','host-initial','--context-source','host-provided')
        Path(meta['response_path']+'.body').write_text(json.dumps(p.body(meta)))
        p.command('tasks.py','submit','--job',job,'--body',meta['response_path']+'.body')
        p.complete(tasks[1])
        review=p.step()['tasks'][0]
        state=json.loads((p.work/'task-state.json').read_text())
        result=p.command('tasks.py','open','--job',state['jobs'][review['id']]['job_path'],
                         '--context-id','host-initial','--context-source','host-provided',ok=False)
        self.assertIn('不能复用 context-id',result.stderr)
        p.complete(review)
        self.assertEqual(p.step()['action'],'deliver')

    def test_challenge_uses_same_role_router(self):
        work=self.pipeline.base/'challenge'
        result=review_benchmark.prepare(work)
        self.assertIn('guidance_path',result)
        self.assertNotIn('rules_path',result)
        packet=Path(result['guidance_path']).read_text()
        self.assertIn('复核者',packet)
        self.assertNotIn('校对者：发现候选',packet)
