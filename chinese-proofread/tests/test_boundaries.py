"""Input budget, routing and extraction-scope regressions."""
import json
from pathlib import Path
import shutil
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import workflow as wf
import report
import test_pipeline


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.pipeline=test_pipeline.PipelineTests()
        self.pipeline.setUp()
        self.addCleanup(self.pipeline.doCleanups)

    def test_dispersed_review_context_is_budgeted_and_not_lost(self):
        blocks=[{'id':'p'+str(i),'kind':'paragraph','location':str(i),'text':'甲'*1800} for i in range(75)]
        doc={'title':'预算测试','source_name':'test.txt','scope':'all','limitations':[],'blocks':blocks}
        candidates=[{'id':'c'+str(i),'anchors':[{'block_id':'p'+str(i),'quote':'甲'}], 'conflict_group':[]} for i in range(1,75,3)]
        groups=wf.candidate_groups(doc,candidates)
        units=report.document_units(doc)
        def measure(selected):
            ids={bid for group in selected for bid in group['context_unit_ids']}
            return sum(len(units[bid]['text']) for bid in ids)+len(json.dumps(selected))
        packs=wf.pack_groups(groups,25,12000,measure)
        self.assertGreater(len(packs),1)
        self.assertTrue(all(measure(p)<=12000 for p in packs))
        self.assertEqual([g['id'] for p in packs for g in p],[g['id'] for g in groups])

    def test_actual_review_files_obey_recorded_budget(self):
        p=self.pipeline
        p.prepare('\n'.join('第%d项需要部暑。' % i for i in range(30)))
        for task in p.step()['tasks']: p.complete(task)
        plan=json.loads((p.work/'review-input/manifest.json').read_text())
        self.assertGreater(len(plan['batches']),1)
        for batch in plan['batches']:
            text=(p.work/'review-input'/batch['file']).read_text(encoding='utf-8')
            self.assertEqual(len(text),batch['input_chars'])
            self.assertLessEqual(len(text),plan['max_input_chars'])

    def test_indivisible_oversized_group_is_preserved(self):
        group={'id':'group','candidates':[{}]*30}
        packs=wf.pack_groups([group],25,10,lambda selection:100)
        self.assertEqual(packs,[[group]])

    def test_single_batch_still_checks_names(self):
        p=self.pipeline
        p.prepare('综合处牵头。'+'请各单位按时报送材料。'*65)
        for task in p.step()['tasks']: p.complete(task)
        tasks=p.step()['tasks']
        self.assertEqual([t['id'] for t in tasks],['consistency'])
        manifest=json.loads((p.work/'batches/manifest.json').read_text())
        self.assertFalse(manifest['long_document'])
        self.assertTrue(manifest['consistency_required'])

    def test_scope_warning_is_visible_and_no_green_success(self):
        doc={'title':'测试','source_name':'test.docx','scope':'仅正文','limitations':['页眉未提取。','文本框未提取。'],
             'blocks':[{'id':'p1','kind':'paragraph','location':'正文','text':'正文正确。'}]}
        review={'method':'test','limitations':[],'passes':[{'id':pid,'checked_block_ids':['p1']} for pid in ('A','B')],'findings':[]}
        html=report.render(doc,review)
        self.assertIn('已提取并检查的文字中',html)
        self.assertIn('<details class="range-note" open>',html)
        self.assertNotIn('aria-hidden="true">✓',html)
        self.assertIn('页眉未提取',html)

    def test_budget_overflow_delivers_without_unreviewed_findings(self):
        p=self.pipeline
        p.skill=p.base/'skill-copy'
        shutil.copytree(test_pipeline.SKILL,p.skill)
        policy=p.skill/'scripts/policy.py'
        policy.write_text(policy.read_text().replace('REVIEW_INPUT_CHARS = 12000','REVIEW_INPUT_CHARS = 10').replace('CONSISTENCY_INPUT_CHARS = 16000','CONSISTENCY_INPUT_CHARS = 10'))
        p.prepare('综合处及时部暑工作。')
        for task in p.step()['tasks']: p.complete(task)
        self.assertEqual(p.step()['action'],'deliver')
        review=json.loads((p.work/'review.json').read_text())
        self.assertEqual(review['findings'],[])
        self.assertTrue(any('超出预算' in note for note in review['limitations']))
        state=json.loads((p.work/'task-state.json').read_text())
        self.assertEqual(state['jobs']['consistency']['status'],'skipped')
        self.assertTrue(any(j['kind']=='review' and j['status']=='skipped' for j in state['jobs'].values()))
