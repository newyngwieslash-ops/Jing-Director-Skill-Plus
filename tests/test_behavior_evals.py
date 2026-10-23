"""Synthetic fixtures testing binding mechanics, NEVER actual LLM/video evaluations."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import director_behavior_evals as ev

class BehaviorEvalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.suite_path = self.root / 'suite.json'
        self.suite = {'schema_version':'1.0','suite_id':'synthetic-mechanics','threshold_percent':50,'cases':[
            {'id':'case-a','prompt':'SYNTHETIC prompt A','hard_fail':True,'assertions':[{'id':'a1','text':'Synthetic assertion','kind':'presence'}]},
            {'id':'case-b','prompt':'SYNTHETIC prompt B','hard_fail':False,'assertions':[{'id':'a1','text':'Synthetic assertion','kind':'absence'}]}]}
        self.save_suite()
        (self.root / 'source.txt').write_text('SYNTHETIC source snapshot', encoding='utf-8')
        for cid in ('case-a', 'case-b'):
            (self.root / (cid+'.txt')).write_text('SYNTHETIC response: quoted evidence.', encoding='utf-8')
        self.spec = {'run_id':'fixture-run','run_kind':'synthetic_fixture','model_label':'NONE — authored test fixture','sources':['source.txt'],'responses':[{'case_id':cid,'path':cid+'.txt','generator_session':'synthetic-'+cid} for cid in ('case-a','case-b')]}
        self.run = ev.record(self.suite_path, self.root, self.spec)
        self.grades = self.make_grades()

    def save_suite(self):
        self.suite_path.write_text(json.dumps(self.suite, ensure_ascii=False), encoding='utf-8')

    def make_grades(self):
        return {'schema_version':'1.0','run_sha256':ev.sha(ev.encoded(self.run)),'reviewer_id':'SYNTHETIC TEST','grader_session':'synthetic-grader','manual_review_acknowledged':True,'grades':[{'case_id':r['case_id'],'response_sha256':r['artifact']['sha256'],'assertions':[{'id':'a1','verdict':'pass','quotes':['quoted evidence'],'rationale':'SYNTHETIC mechanical fixture, not semantic evidence.'}]} for r in self.run['responses']]}

    def evaluate(self):
        return ev.evaluate(self.suite_path, self.root, self.run, self.grades)

    def test_packaged_cases_validate_without_run(self):
        path = ROOT / 'evals/cases.json'
        self.assertEqual(len(ev.validate_suite(ev.load(path))['cases']),20)
        self.assertEqual(ev.evaluate(path, ROOT)['status'], 'not_run')

    def test_packaged_baseline_is_bound_to_current_suite_and_not_run(self):
        path = ROOT / 'evals/cases.json'
        suite = ev.validate_suite(ev.load(path))
        stored = ev.load(ROOT / 'evals/baseline-not-run.json')
        actual = ev.evaluate(path, ROOT)
        self.assertEqual(stored, actual)
        self.assertEqual(stored['suite_sha256'], ev.sha(path.read_bytes()))
        self.assertEqual(stored['total_cases'], len(suite['cases']))
        self.assertEqual(stored['total_cases'], 20)
        self.assertEqual(sum(len(case['assertions']) for case in suite['cases']), 60)
        self.assertEqual(suite['threshold_percent'], 92)
        self.assertEqual(stored['required_passes'], ev.required_count(len(suite['cases']), suite['threshold_percent']))
        self.assertEqual(stored['required_passes'], 19)
        self.assertEqual(stored['status'], 'not_run')
        self.assertEqual(stored['passed_cases'], 0)
        self.assertEqual(stored['case_results'], [])
        for field in ('production_evidence', 'release_ready', 'video_quality_verified',
                      'semantic_correctness_verified', 'model_identity_verified'):
            self.assertFalse(stored[field])

    def test_threshold_uses_ceiling(self):
        self.assertEqual(ev.required_count(57,92),53)
        self.assertEqual(ev.required_count(20,92),19)
        self.assertEqual(ev.required_count(25,92),23)

    def test_no_run_is_not_pass(self):
        result = ev.evaluate(self.suite_path,self.root)
        self.assertEqual(result['status'],'not_run')
        self.assertFalse(result['release_ready'])

    def test_synthetic_cannot_be_production(self):
        result = self.evaluate()
        self.assertEqual(result['status'],'synthetic_fixture_pass')
        for field in ('production_evidence','release_ready','video_quality_verified','semantic_correctness_verified','provided_model_response_evidence'):
            self.assertFalse(result[field])

    def test_provided_run_still_not_video_or_release_approval(self):
        self.run['run_kind']='provided_model_run'
        self.grades=self.make_grades()
        result=self.evaluate()
        self.assertEqual(result['status'],'manual_grades_pass')
        self.assertTrue(result['provided_model_response_evidence'])
        self.assertFalse(result['release_ready'])
        self.assertFalse(result['video_quality_verified'])

    def test_hard_fail_cannot_be_offset_by_score(self):
        self.grades['grades'][0]['assertions'][0]['verdict']='fail'
        result=self.evaluate()
        self.assertEqual(result['passed_cases'],result['required_passes'])
        self.assertEqual(result['status'],'synthetic_fixture_fail')
        self.assertEqual(result['hard_failures'],['case-a'])

    def test_nonhard_fail_at_threshold_allowed(self):
        self.grades['grades'][1]['assertions'][0]['verdict']='fail'
        self.assertEqual(self.evaluate()['status'],'synthetic_fixture_pass')

    def test_below_threshold_fails(self):
        self.suite['threshold_percent']=51; self.save_suite()
        self.run=ev.record(self.suite_path,self.root,self.spec); self.grades=self.make_grades()
        self.grades['grades'][1]['assertions'][0]['verdict']='fail'
        self.assertEqual(self.evaluate()['status'],'synthetic_fixture_fail')

    def test_missing_response_is_incomplete(self):
        self.spec['responses'].pop()
        self.run=ev.record(self.suite_path,self.root,self.spec); self.grades=self.make_grades()
        result=self.evaluate()
        self.assertEqual(result['status'],'incomplete')
        self.assertEqual(result['missing_responses'],['case-b'])

    def test_missing_grades_incomplete(self):
        self.assertEqual(ev.evaluate(self.suite_path,self.root,self.run)['status'],'incomplete')
        self.grades['grades'].pop()
        self.assertEqual(self.evaluate()['status'],'incomplete')

    def test_missing_assertion_incomplete(self):
        self.grades['grades'][0]['assertions']=[]
        self.assertEqual(self.evaluate()['status'],'incomplete')

    def test_duplicate_response_rejected(self):
        self.spec['responses'].append(copy.deepcopy(self.spec['responses'][0]))
        with self.assertRaises(ev.EvalError): ev.record(self.suite_path,self.root,self.spec)

    def test_duplicate_grade_rejected(self):
        self.grades['grades'].append(copy.deepcopy(self.grades['grades'][0]))
        with self.assertRaises(ev.EvalError): self.evaluate()

    def test_duplicate_assertion_rejected(self):
        self.grades['grades'][0]['assertions']*=2
        with self.assertRaises(ev.EvalError): self.evaluate()

    def test_stale_suite_rejected_even_whitespace(self):
        self.suite_path.write_text(self.suite_path.read_text()+'\n')
        with self.assertRaises(ev.EvalError): self.evaluate()

    def test_stale_prompt_rejected(self):
        self.run['responses'][0]['prompt_sha256']='0'*64
        self.grades=self.make_grades()
        with self.assertRaises(ev.EvalError): self.evaluate()

    def test_stale_response_rejected(self):
        (self.root/'case-a.txt').write_text('changed')
        with self.assertRaises(ev.EvalError): self.evaluate()

    def test_stale_source_rejected(self):
        (self.root/'source.txt').write_text('changed')
        with self.assertRaises(ev.EvalError): self.evaluate()

    def test_stale_grade_run_hash_rejected(self):
        self.grades['run_sha256']='0'*64
        with self.assertRaises(ev.EvalError): self.evaluate()

    def test_stale_grade_response_hash_rejected(self):
        self.grades['grades'][0]['response_sha256']='0'*64
        with self.assertRaises(ev.EvalError): self.evaluate()

    def test_fabricated_quote_rejected(self):
        self.grades['grades'][0]['assertions'][0]['quotes']=['not in response']
        with self.assertRaises(ev.EvalError): self.evaluate()

    def test_presence_pass_requires_quote(self):
        self.grades['grades'][0]['assertions'][0]['quotes']=[]
        with self.assertRaises(ev.EvalError): self.evaluate()

    def test_absence_pass_allows_reason_instead_of_quote(self):
        self.grades['grades'][1]['assertions'][0]['quotes']=[]
        self.assertEqual(self.evaluate()['status'],'synthetic_fixture_pass')

    def test_fail_allows_no_quote_for_missing_requirement(self):
        a=self.grades['grades'][0]['assertions'][0]
        a['quotes']=[]; a['verdict']='fail'
        self.assertEqual(self.evaluate()['status'],'synthetic_fixture_fail')

    def test_draft_review_not_accepted(self):
        self.grades['manual_review_acknowledged']=False
        with self.assertRaises(ev.EvalError): self.evaluate()

    def test_same_generation_and_grading_session_rejected(self):
        self.grades['grader_session']=self.run['responses'][0]['generator_session']
        with self.assertRaises(ev.EvalError): self.evaluate()

    def test_reused_generation_session_rejected(self):
        self.spec['responses'][1]['generator_session']=self.spec['responses'][0]['generator_session']
        with self.assertRaises(ev.EvalError): ev.record(self.suite_path,self.root,self.spec)

    def test_traversal_absolute_and_symlink_paths_rejected(self):
        (self.root/'link.txt').symlink_to(self.root/'source.txt')
        (self.root/'linked-dir').symlink_to(self.root, target_is_directory=True)
        for name in ('../source.txt',str(self.root/'source.txt'),'link.txt','linked-dir/source.txt','a\\b'):
            with self.subTest(name=name),self.assertRaises(ev.EvalError): ev.artifact(self.root,name)

    def test_resource_guard(self):
        (self.root/'huge.txt').write_bytes(b'x'*(ev.MAX_BYTES+1))
        with self.assertRaises(ev.EvalError): ev.read_bytes(self.root/'huge.txt')

    def test_output_never_overwrites(self):
        out=self.root/'result.json'
        ev.write_new(out,{'first':True})
        with self.assertRaises(FileExistsError): ev.write_new(out,{'second':True})
        self.assertTrue(ev.load(out)['first'])

    def test_invalid_suite_duplicate_cases_and_threshold(self):
        bad=copy.deepcopy(self.suite); bad['cases']*=2
        with self.assertRaises(ev.EvalError): ev.validate_suite(bad)
        for value in (0,101,True,92.0):
            bad=copy.deepcopy(self.suite); bad['threshold_percent']=value
            with self.subTest(value=value),self.assertRaises(ev.EvalError): ev.validate_suite(bad)

    def test_duplicate_json_keys_rejected(self):
        path=self.root/'invalid.json';path.write_text('{"x":1,"x":2}')
        with self.assertRaises(ev.EvalError): ev.load(path)

    def test_grades_without_run_rejected(self):
        with self.assertRaises(ev.EvalError): ev.evaluate(self.suite_path,self.root,grades=self.grades)

if __name__=='__main__':
    unittest.main()
