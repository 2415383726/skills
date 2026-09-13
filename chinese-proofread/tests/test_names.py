"""Name comparison coverage, compact contexts and isolated supplement behavior."""
from itertools import combinations
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import names
import test_pipeline


class NameTests(unittest.TestCase):
    def test_index_deduplicates_spelling_and_context(self):
        units = {'p1': {'text': '中国共产党。中国共产党。', 'location': '正文'}}
        raw = [{'text': '中国共产党', 'kind': kind, 'block_id': 'p1'} for kind in ('政党名称', '组织名称')]
        indexed = names.index(units, raw)
        self.assertEqual(len(indexed), 1)
        self.assertEqual(len(indexed[0]['occurrences']), 2)
        self.assertNotIn('context', indexed[0]['occurrences'][0])
        self.assertEqual(len(names.blocks(units, indexed)), 1)

    def test_13000_char_document_preserves_cross_batch_pairs(self):
        terms, units = [], {}
        for i in range(7):
            labels = ['机构{:02d}'.format(i * 4 + j) for j in range(4)]
            units['p'+str(i)] = {'text': '；'.join(labels) + '。' + '正文说明。' * 370, 'location': str(i)}
            terms.extend({'text': t, 'kind': '机构', 'block_id': 'p'+str(i)} for t in labels)
        indexed = names.index(units, terms)
        source = {'terms': indexed, 'blocks': names.blocks(units, indexed), 'merged_sha256': 'x'*64}
        packets = names.plan(source, 16000)
        self.assertGreater(len(packets), 1)
        seen = set()
        for packet in packets:
            self.assertLessEqual(len(json.dumps(packet, ensure_ascii=False, indent=2)), 16000)
            seen.update(combinations(sorted(t['text'] for t in packet['terms']), 2))
            for block in packet['blocks']:
                self.assertEqual(block['text'], units[block['id']]['text'])
        self.assertEqual(seen, set(combinations(sorted(t['text'] for t in indexed), 2)))

    def test_coverage_distinguishes_one_missing_pass_from_missing_batch(self):
        coverage, notes = names.coverage(['b1', 'b2'], [{'pass_id':'A','batch_id':'b1','complete':True}])
        self.assertEqual(coverage['collected_batches'], 1)
        self.assertEqual(coverage['missing_batches'], ['b2'])
        self.assertTrue(any('B路' in note for note in notes))

    def test_supplement_reuses_names_without_initial_jobs_or_old_report_changes(self):
        p = test_pipeline.PipelineTests(); p.setUp()
        self.addCleanup(p.doCleanups)
        p.prepare('综合处负责统筹。')
        for task in p.step()['tasks']: p.complete(task)
        for task in p.step()['tasks']: p.complete(task)
        original = p.step()
        self.assertEqual(original['action'], 'deliver')
        old_html = Path(original['report_path']).read_bytes()
        supplement = p.base / 'supplement'
        p.command('recheck_names.py', '--source-work', p.work, '--work', supplement,
                  '--coordinator', 'test-coordinator', '--max-input-chars', '20000')
        original_work = p.work; p.work = supplement
        dispatch = p.step()
        self.assertEqual(len(dispatch['tasks']), 1)
        self.assertEqual(p.metadata(dispatch['tasks'][0])['kind'], 'consistency')
        p.complete(dispatch['tasks'][0])
        delivered = p.step()
        self.assertEqual(delivered['action'], 'deliver')
        state = json.loads((supplement / 'task-state.json').read_text())
        self.assertTrue(all(j['kind'] != 'proofread' for j in state['jobs'].values()))
        self.assertTrue(json.loads((supplement / 'review.json').read_text())['names_only'])
        self.assertIn('本次仅补查名称一致性', Path(delivered['report_path']).read_text())
        self.assertEqual((original_work/'校对报告.html').read_bytes(), old_html)
        self.assertIn('summary', delivered)
        self.assertNotIn('findings', delivered['summary'])
        p.command('recheck_names.py', '--source-work', original_work, '--work', supplement,
                  '--coordinator', 'test-coordinator', ok=False)

    def test_name_candidate_is_reviewed_and_disclosures_have_requested_defaults(self):
        from html.parser import HTMLParser
        p = test_pipeline.PipelineTests(); p.setUp()
        self.addCleanup(p.doCleanups)
        p.prepare('由综合处牵头。由综合科牵头。')
        for task in p.step()['tasks']:
            job, body_path = p.open_body(task)
            body = json.loads(body_path.read_text())
            body['terms'].append({'text':'综合科','kind':'组织名称'})
            body_path.write_text(json.dumps(body))
            p.command('tasks.py','submit','--job',job,'--body',body_path)
        name_task = p.step()['tasks'][0]
        job, body_path = p.open_body(name_task)
        finding = {'severity':'pending','rule_id':'N-CONSISTENCY','category':'名称疑点',
                   'reason':'两处牵头机构名称有差异，请核实是否指同一机构。',
                   'anchors':[{'block_id':'p1','quote':'综合处'},{'block_id':'p1','quote':'综合科'}], 'suggestion':None}
        body_path.write_text(json.dumps({'checked':True,'candidates':[finding],'limitations':[]}))
        p.command('tasks.py','submit','--job',job,'--body',body_path)
        review_task=p.step()['tasks'][0]
        meta=p.metadata(review_task)
        state=json.loads((p.work/'task-state.json').read_text())
        job=state['jobs'][review_task['id']]['job_path']
        p.command('tasks.py','open','--job',job,'--brief')
        payload=json.loads(Path(meta['input_path']).read_text())
        decisions=[{'group_id':g['id'],'replace':[{'candidate_ids':[c['id'] for c in g['candidates']],
                    'reason':'需核实名称','findings':[finding]}]} for g in payload['candidate_groups']]
        body_path=Path(meta['response_path']+'.body')
        body_path.write_text(json.dumps({'group_decisions':decisions,'limitations':[]}))
        p.command('tasks.py','submit','--job',job,'--body',body_path)
        result=p.step()
        self.assertEqual(result['summary']['severity'],{'confirmed':0,'pending':1})
        class Details(HTMLParser):
            def __init__(self): super().__init__(); self.items={}
            def handle_starttag(self, tag, attrs):
                if tag=='details': self.items[dict(attrs).get('class')]=dict(attrs)
        parser=Details();parser.feed(Path(result['report_path']).read_text())
        self.assertIn('open',parser.items['pending'])
        self.assertNotIn('open',parser.items['range-note'])

    def test_multiple_name_workers_aggregate_without_rerunning_initial_checks(self):
        p=test_pipeline.PipelineTests();p.setUp()
        self.addCleanup(p.doCleanups)
        labels=['机构%02d'%i for i in range(28)]
        p.prepare('\n'.join('；'.join(labels[i*4:i*4+4])+'。'+'正文说明。'*370 for i in range(7)))
        name_count=0
        for _ in range(20):
            result=p.step()
            if result['action']=='deliver': break
            self.assertEqual(result['action'],'dispatch')
            for task in result['tasks']:
                metadata=p.metadata(task)
                if metadata['kind']=='proofread':
                    job,body_path=p.open_body(task)
                    payload=json.loads(Path(metadata['input_path']).read_text())
                    body=json.loads(body_path.read_text())
                    body['terms']=[{'text':t,'kind':'机构'} for t in labels if any(t in u['text'] for u in payload['main_units'])]
                    body_path.write_text(json.dumps(body))
                    p.command('tasks.py','submit','--job',job,'--body',body_path)
                else:
                    self.assertEqual(metadata['kind'],'consistency')
                    payload=json.loads(Path(metadata['input_path']).read_text())
                    self.assertLessEqual(len(json.dumps(payload,ensure_ascii=False,indent=2)),16000)
                    name_count+=1
                    p.complete(task)
        else: self.fail('名称任务未正常完成')
        self.assertGreater(name_count,1)
        aggregate=json.loads((p.work/'consistency-result.json').read_text())
        self.assertTrue(aggregate['complete'])
        self.assertEqual(len(aggregate['executions']),name_count)
        self.assertEqual(result['summary']['severity']['pending'],0)

    def test_supplement_rejects_changed_index_before_creating_output(self):
        p=test_pipeline.PipelineTests();p.setUp()
        self.addCleanup(p.doCleanups)
        p.prepare('综合处负责统筹。')
        for task in p.step()['tasks']: p.complete(task)
        for task in p.step()['tasks']: p.complete(task)
        p.step()
        index_path=p.work/'consistency-input.json'
        value=json.loads(index_path.read_text());value['title']='changed'
        index_path.write_text(json.dumps(value))
        target=p.base/'rejected-supplement'
        result=p.command('recheck_names.py','--source-work',p.work,'--work',target,
                         '--coordinator','test-coordinator',ok=False)
        self.assertIn('指纹变化',result.stderr)
        self.assertFalse(target.exists())
