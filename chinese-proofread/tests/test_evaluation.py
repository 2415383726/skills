"""Scoring correctness, not evidence of model language accuracy."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import evaluate
import compare_evaluations
import provenance
import report


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        source = self.root/'source.txt'
        source.write_text('请部暑。\n认真学习。', encoding='utf-8')
        self.doc = provenance.bind({'title':'测试','source_name':source.name,'scope':'全部','limitations':[],
            'blocks':[{'id':'p1','kind':'paragraph','text':'请部暑。','location':'1'},
                      {'id':'p2','kind':'paragraph','text':'认真学习。','location':'2'}]}, provenance.snapshot(source), 'test')
        self.gold = {'document_sha256':provenance.digest(self.doc),'annotation_status':'seed-unreviewed','cases':[
            {'block_id':'p1','text':'请部暑。','annotation_status':'seed-unreviewed','expected':[{'category':'错别字','anchor':{'quote':'部暑'},'suggestion':'部署'}]},
            {'block_id':'p2','text':'认真学习。','annotation_status':'seed-unreviewed','expected':[]}]}
        self.review = {'document_sha256':provenance.digest(self.doc),'findings':[]}

    def finding(self, quote='部暑', suggestion='部署', bid='p1', severity='confirmed'):
        return {'reviewed':True,'severity':severity,'rule_id':'T-TYPO','anchors':[{'block_id':bid,'quote':quote}], 'suggestion':suggestion}

    def score(self):
        return evaluate.evaluate(self.doc,self.review,self.gold)

    def test_effect_match_ignores_anchor_size_and_deduplicates(self):
        self.review['findings']=[self.finding(),self.finding('请部暑。','请部署。')]
        score=self.score()
        self.assertEqual(score['overall'],dict(tp=1,fp=0,fn=0,precision=1,recall=1))
        self.assertEqual(score['duplicate_confirmed'],1)
        self.assertEqual(score['annotation_status'],'seed-unreviewed')

    def test_pending_does_not_earn_true_positive(self):
        self.review['findings']=[self.finding(suggestion=None,severity='pending')]
        score=self.score()
        self.assertEqual(score['overall']['fn'],1)
        self.assertIsNone(score['overall']['precision'])
        self.assertEqual(score['pending'],1)

    def test_false_change_on_correct_text_is_counted(self):
        self.review['findings']=[self.finding('认真学习','认真地学习','p2')]
        score=self.score()
        self.assertEqual(score['overall']['fp'],1)
        self.assertEqual(score['no_change_false_positives'],1)

    def test_changed_source_and_mismatched_gold_are_rejected(self):
        self.gold['cases'][0]['text']='错误的金标正文'
        with self.assertRaises(ValueError): self.score()
        Path(self.doc['provenance']['source_path']).write_text('来源变了')
        with self.assertRaises(ValueError): self.score()

    def test_annotation_template_cannot_be_scored_as_no_errors(self):
        source = self.root/'document.json'
        source.write_text(json.dumps(self.doc))
        self.gold = evaluate.annotation_template(source)
        self.assertIsNone(self.gold['cases'][0]['expected'])
        with self.assertRaises(ValueError): self.score()

    def test_all_no_change_has_null_recall(self):
        self.gold['cases'][0]['expected']=[]
        self.assertIsNone(self.score()['overall']['recall'])

    def test_incomplete_gold_is_rejected(self):
        self.gold['cases'].pop()
        with self.assertRaises(ValueError): self.score()

    def test_comparison_requires_matched_source_and_records_failure(self):
        score=self.score()
        rows=[]
        for name in compare_evaluations.VARIANTS:
            (self.root/(name+'.json')).write_text(json.dumps(score))
            rows.append({'variant':name,'material':'sample','repeat':1,'delivered':True,'elapsed_seconds':2,'score_path':name+'.json'})
        manifest=self.root/'runs.json'
        manifest.write_text(json.dumps({'model_config':'synthetic test only','runs':rows}))
        result=compare_evaluations.compare(manifest)
        self.assertEqual(result['fully_scored_groups'],1)
        changed=copy.deepcopy(score); changed['gold_sha256']='different'
        (self.root/'dual-review.json').write_text(json.dumps(changed))
        with self.assertRaises(ValueError): compare_evaluations.compare(manifest)
        rows[-1].update(delivered=False,score_path=None)
        manifest.write_text(json.dumps({'model_config':'synthetic test only','runs':rows}))
        result=compare_evaluations.compare(manifest)
        self.assertEqual(result['fully_scored_groups'],0)
        self.assertEqual(result['variants']['dual-review']['delivery_rate'],0)
        self.assertIsNone(result['variants']['single-pass']['precision'])
