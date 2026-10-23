"""Offline sidecar regression gates; these are not observed video quality tests."""
from __future__ import annotations
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from director_core import ContractError, digest
from director_methods import scaffold, validate_pack, render_review, _unknown

class DirectorMethodsTests(unittest.TestCase):
    def setUp(self):
        self.contract=json.loads((ROOT/'examples/hall-shot-09/director-contract.json').read_text())
        self.pack=scaffold(self.contract)
        self.shot=self.pack['shots'][0]
    def report(self):return validate_pack(self.contract,self.pack)
    def codes(self):return {x['code'] for x in self.report()['errors']}
    def blockers(self):return {x['code'] for x in self.report()['blockers']}
    def test_scaffold_draft_not_approval(self):
        r=self.report();self.assertTrue(r['structurally_valid']);self.assertEqual(r['status'],'draft');self.assertFalse(r['execution_ready']);self.assertFalse(r['artistic_approval']);self.assertIn('CAPABILITY_BLOCKED',self.blockers())
    def test_scaffold_does_not_mutate(self):
        before=digest(self.contract);scaffold(self.contract);self.assertEqual(before,digest(self.contract))
        self.shot['locked_source']['subjects'].append('x');self.assertEqual(before,digest(self.contract))
    def test_empty_shot_performance_not_applicable(self):
        contract=json.loads((ROOT/'examples/blocking-demo/director-contract.json').read_text())
        result=validate_pack(contract,scaffold(contract))
        pending={b['where'] for b in result['blockers'] if b['code']=='PERFORMANCE_UNPLANNED'}
        self.assertEqual(pending,{'shots.'+s['shot_id'] for s in contract['shots'] if s['subjects']})
        self.assertTrue(any(not s['subjects'] for s in contract['shots']))
        self.assertFalse(result['execution_ready'])
        self.assertIn('PLANNING_ONLY',{b['code'] for b in result['blockers']})
    def test_stale_contract(self):
        self.pack['contract_sha256']='0'*64;self.assertIn('STALE_CONTRACT',self.codes())
    def test_missing_shot(self):
        self.pack['shots']=[];self.assertIn('SHOT_COVERAGE',self.codes())
    def test_extra_shot(self):
        self.pack['shots'].append(copy.deepcopy(self.shot));self.assertIn('SHOT_COVERAGE',self.codes())
    def test_extra_unknown_shot(self):
        x=copy.deepcopy(self.shot);x['shot_id']='invented';self.pack['shots'].append(x);self.assertIn('SHOT_COVERAGE',self.codes())
    def test_missing_role(self):
        self.shot['role_ids'].pop();self.assertIn('ROLE_COVERAGE',self.codes())
    def test_extra_role(self):
        self.shot['role_ids'].append('new_actor');self.assertIn('ROLE_COVERAGE',self.codes())
    def test_source_drift(self):
        self.shot['locked_source']['duration_sec']=9;self.assertIn('SOURCE_DRIFT',self.codes())
    def test_scene_drift(self):
        self.shot['scene_id']='new_scene';self.assertIn('SCENE_DRIFT',self.codes())
    def test_fake_approval_rejected(self):
        self.shot['approved']=True;self.assertIn('METHOD_SHAPE',self.codes())
    def test_fake_approval_cannot_authorize_drift(self):
        self.shot['locked_source']['approved']=True;self.assertIn('SOURCE_DRIFT',self.codes())
    def test_unsupported_shape_failclosed(self):
        self.shot['capability']['requested_shape']='S4';self.assertIn('CAPABILITY_BLOCKED',self.blockers());self.assertFalse(self.report()['derived']['shots'][0]['prompt_shape_plannable'])
    def test_fake_execution_ready_rejected(self):
        self.shot['capability']['execution_ready']=True;self.assertIn('METHOD_SHAPE',self.codes())
    def test_capability_requires_evidence(self):
        self.shot['capability']['capabilities']['text_to_video']='supported';self.assertIn('CAPABILITY_EVIDENCE',self.codes())
    def test_capability_manual_evidence_not_api(self):
        c=self.shot['capability'];c['requested_shape']='S2';c['capabilities']['text_to_video']='supported';c['evidence']=[{'capability':'text_to_video','source':'manual observation (not verified by tool)','observed_at':'2026-10-23','claim':'supported'}]
        r=self.report();self.assertTrue(r['structurally_valid']);self.assertFalse(r['execution_ready']);self.assertIn('CAPABILITY_MANUAL_ONLY',self.blockers())
    def test_s3_requires_two_frame_references(self):
        c=self.shot['capability'];c['requested_shape']='S3'
        for k in ['first_frame','last_frame']:
            c['capabilities'][k]='supported';c['evidence'].append({'capability':k,'source':'manual','observed_at':'2026-10-23','claim':'supported'})
        self.assertIn('CAPABILITY_BLOCKED',self.blockers())
    def attempt(self,**kw):
        a={'attempt_id':'a1','design_id':'d1','batch_size':1,'outcome':'failed','failure_codes':['F1'],'repair_level':'retry','note':'manual historical observation; no receipt'};a.update(kw);return a
    def test_batch_and_design_counter(self):
        r=self.shot['repair'];r['attempts']=[self.attempt(batch_size=3),self.attempt(attempt_id='a2',design_id='d2',batch_size=2)]
        d=self.report()['derived']['shots'][0];self.assertEqual(d['attempt_units'],5);self.assertEqual(d['design_failures'],{'d1':3,'d2':2});self.assertIn('DESIGN_FAILURE_LIMIT',self.blockers())
    def test_v2v_does_not_add_strike_but_counts_budget(self):
        self.shot['repair']['attempts']=[self.attempt(batch_size=4,repair_level='video_to_video')]
        d=self.report()['derived']['shots'][0];self.assertEqual(d['attempt_units'],4);self.assertEqual(d['design_failures'],{})
    def test_budget_not_reset_by_new_design(self):
        self.shot['repair']['shot_attempt_budget']=3;self.shot['repair']['attempts']=[self.attempt(batch_size=2),self.attempt(attempt_id='a2',design_id='d2',batch_size=2)]
        self.assertIn('SHOT_BUDGET_EXCEEDED',self.codes())
    def test_no_trusted_counter(self):
        self.shot['repair']['failure_count']=0;self.assertIn('METHOD_SHAPE',self.codes())
    def test_no_fake_provider_receipt(self):
        a=self.attempt();a['provider_receipt']='fake';self.shot['repair']['attempts']=[a];self.assertIn('METHOD_SHAPE',self.codes())
    def test_f19_and_invalid_failure(self):
        self.shot['repair']['attempts']=[self.attempt(failure_codes=['F19'])];self.assertTrue(self.report()['structurally_valid'])
        self.shot['repair']['attempts'][0]['failure_codes']=['F20'];self.assertIn('METHOD_SHAPE',self.codes())
    def test_recut_not_execution_record(self):
        self.shot['repair']['attempts']=[self.attempt(repair_level='delete_proposal')];self.assertIn('PROPOSAL_NOT_ATTEMPT',self.codes())
    def test_proposal_inactive_and_immutable(self):
        before=digest(self.contract);self.pack['change_requests']=[{'request_id':'r1','shot_ids':['S009'],'reason':'manual review','proposed_change':'cut a shot','state':'inactive_proposal'}]
        self.assertTrue(self.report()['structurally_valid']);self.assertEqual(before,digest(self.contract));self.assertIn('INACTIVE_CHANGE_REQUEST',self.blockers())
    def test_exact_edit_no_retime(self):
        self.shot['edit']['source_out_frame']-=1;self.assertIn('EDIT_DRIFT',self.codes())
    def test_no_implicit_crossfade(self):
        self.shot['edit']['transition']='crossfade';self.assertIn('METHOD_SHAPE',self.codes())
    def test_boolean_not_fps(self):
        self.pack['fps']=True;self.assertIn('METHOD_SHAPE',self.codes())
    def test_sound_source_preserved(self):
        self.shot['sound']['source_music']['zh']='添加悲伤音乐';self.assertIn('SOUND_SOURCE_DRIFT',self.codes())
    def cue(self):
        return {'cue_id':'cue1','layer':'AMB','start_frame':0,'end_frame':240,'description':_unknown(),'space':{'relation':'unknown','role_id':None,'position':_unknown()},'asset_ref':None}
    def test_cue_out_of_range(self):
        c=self.cue();c['end_frame']=241;self.shot['sound']['cues']=[c];self.assertIn('CUE_TIME',self.codes())
    def test_unknown_sound_role(self):
        c=self.cue();c['space']['role_id']='invented';self.shot['sound']['cues']=[c];self.assertIn('CUE_ROLE',self.codes())
    def test_no_inferred_dialogue(self):
        c=self.cue();c['layer']='DIALOGUE';c['description']={'classification':'inference','text':'new dialogue','evidence':[]};self.shot['sound']['cues']=[c];self.assertIn('DIALOGUE_ADDED',self.codes());self.assertIn('DIALOGUE_INFERENCE',self.codes())
    def performance(self):
        return {'role_id':self.shot['role_ids'][0],'beat_index':0,**{k:_unknown() for k in ['task','attention','trigger','weight_support','contact_feedback','end_state']}}
    def test_performance_unknown_role_and_beat(self):
        p=self.performance();p['role_id']='invented';p['beat_index']=99;self.shot['performance']=[p];self.assertIn('PERFORMANCE_ROLE',self.codes());self.assertIn('PERFORMANCE_BEAT',self.codes())
    def test_source_quote_exact(self):
        p=self.performance();value=self.contract['shots'][0]['beats'][0]['trigger'];p['trigger']={'classification':'source','text':value,'evidence':[{'pointer':'/shots/0/beats/0/trigger','value':value}]};self.shot['performance']=[p];self.assertTrue(self.report()['structurally_valid'])
        p['trigger']['text']='adds tears';self.assertIn('SOURCE_PARAPHRASE',self.codes())
    def test_changed_evidence(self):
        p=self.performance();p['trigger']={'classification':'source','text':'fake','evidence':[{'pointer':'/shots/0/beats/0/trigger','value':'fake'}]};self.shot['performance']=[p];self.assertIn('SOURCE_EVIDENCE',self.codes())
    def test_inference_never_approved(self):
        p=self.performance();p['task']={'classification':'inference','text':'possible observable task','evidence':[]};self.shot['performance']=[p];self.assertTrue(self.report()['structurally_valid']);self.assertIn('INFERENCE_UNAPPROVED',self.blockers())
    def test_no_render_script_injection(self):
        self.pack['change_requests']=[{'request_id':'r','shot_ids':['S009'],'reason':'<script>alert(1)</script>','proposed_change':'https://example.com','state':'inactive_proposal'}]
        h=render_review(self.contract,self.pack);self.assertNotIn('<script>',h);self.assertIn('&lt;script&gt;',h);self.assertIn("default-src 'none'",h)
    def test_nonfinite_rejected(self):
        self.pack['fps']=float('nan')
        with self.assertRaises(ContractError):self.report()
    def test_unrepresentable_frame_duration_never_rounded(self):
        from test_director_pipeline import two_shots
        c=two_shots(0.101);p=scaffold(c,24);r=validate_pack(c,p)
        self.assertTrue(r['structurally_valid']);self.assertIsNone(p['shots'][0]['edit']['source_out_frame']);self.assertIn('FRAME_UNREPRESENTABLE',{b['code'] for b in r['blockers']});self.assertIsNone(r['derived']['total_frames'])
    def test_canonical_sequence_and_program_frames(self):
        from test_director_pipeline import two_shots
        c=two_shots(5);p=scaffold(c);self.assertEqual(p['shots'][1]['edit']['program_in_frame'],120)
        p['shots'].reverse();r=validate_pack(c,p);self.assertIn('SHOT_COVERAGE',{e['code'] for e in r['errors']})
    def test_style_conflict_remains_blocker(self):
        self.pack['director_book']['camera']['rules']=[{'rule_id':'r1','shot_ids':['S009'],'preference':{'classification':'inference','text':'possible camera preference','evidence':[]},'counterexample':'Not a new camera command','conflict':'unresolved','priority':1}]
        self.assertTrue(self.report()['structurally_valid']);self.assertIn('STYLE_CONFLICT',self.blockers())
    def test_style_scope_cannot_invent_shot(self):
        self.pack['director_book']['camera']['rules']=[{'rule_id':'r1','shot_ids':['new'],'preference':_unknown(),'counterexample':'','conflict':'none','priority':1}]
        self.assertIn('RULE_SCOPE',self.codes())
    def test_source_unknown_cannot_carry_instruction(self):
        p=self.performance();p['trigger']['text']='turn around';self.shot['performance']=[p];self.assertIn('UNKNOWN_WITH_TEXT',self.codes())
    def test_duplicate_attempt_rejected(self):
        self.shot['repair']['attempts']=[self.attempt(),self.attempt()];self.assertIn('DUPLICATE_ATTEMPT',self.codes())
    def test_failed_record_requires_diagnostic(self):
        self.shot['repair']['attempts']=[self.attempt(failure_codes=[])];self.assertIn('FAILURE_CODE_REQUIRED',self.codes())
    def test_duplicate_performance_rejected(self):
        self.shot['performance']=[self.performance(),self.performance()];self.assertIn('PERFORMANCE_DUPLICATE',self.codes())
    def test_empty_budget_not_allowed(self):
        self.shot['repair']['shot_attempt_budget']=0;self.assertIn('METHOD_SHAPE',self.codes())
    def test_source_authentication_not_claimed(self):
        self.assertIn('SOURCE_BASELINE_NOT_AUTHENTICATED',self.blockers())
    def test_readable_review_sections_and_collapsed_raw(self):
        h=render_review(self.contract,self.pack)
        for title in ['部门导演参数卡','表演方法','修复账本','能力与提示词形态','声音 Cue','剪辑帧计划','<details>','CLI exit 0']:
            self.assertIn(title,h)
        self.assertNotIn('<script',h);self.assertNotIn('<iframe',h)
    def test_duplicate_json_keys_rejected_on_read(self):
        from director_methods import _read
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'duplicate.json';p.write_text('{"approved":true,"approved":false}')
            with self.assertRaises(ContractError):_read(p)
    def test_review_malformed_root_clean_diagnostic(self):
        h=render_review(self.contract,[])
        self.assertIn('METHOD_SHAPE',h);self.assertIn('blocked',h)
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'pack.json';p.write_text('[]');out=Path(t)/'review'
            run=subprocess.run([sys.executable,str(ROOT/'scripts/director_methods.py'),'review','--contract',str(ROOT/'examples/hall-shot-09/director-contract.json'),'--pack',str(p),'--out',str(out)],capture_output=True,text=True)
            self.assertEqual(run.returncode,2);self.assertNotIn('Traceback',run.stderr)
            report=json.loads((out/'method-report.json').read_text());self.assertFalse(report['structurally_valid']);self.assertFalse(report['execution_ready'])
    def test_cli_no_overwrite(self):
        with tempfile.TemporaryDirectory() as t:
            out=Path(t)/'new';args=[sys.executable,str(ROOT/'scripts/director_methods.py'),'scaffold','--contract',str(ROOT/'examples/hall-shot-09/director-contract.json'),'--out',str(out)]
            first=subprocess.run(args,capture_output=True);self.assertEqual(first.returncode,0,first.stderr)
            before=(out/'method-pack.json').read_bytes();again=subprocess.run(args,capture_output=True);self.assertEqual(again.returncode,2);self.assertEqual(before,(out/'method-pack.json').read_bytes())
    def test_cli_symlink_output_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            real=Path(t)/'real';real.mkdir();link=Path(t)/'link';link.symlink_to(real,target_is_directory=True)
            p=subprocess.run([sys.executable,str(ROOT/'scripts/director_methods.py'),'scaffold','--contract',str(ROOT/'examples/hall-shot-09/director-contract.json'),'--out',str(link)],capture_output=True);self.assertEqual(p.returncode,2);self.assertEqual(list(real.iterdir()),[])

if __name__=='__main__':unittest.main()
