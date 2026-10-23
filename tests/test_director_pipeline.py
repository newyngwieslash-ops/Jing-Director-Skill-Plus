from __future__ import annotations
import base64
import copy
import io
import json
from pathlib import Path
import subprocess
import struct
import sys
import tempfile
import unittest
import zipfile
import zlib
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from director_core import (ContractError, compiler, digest, duration, group_boards, ingest, load_json,
                           project_path, shape_errors, skeleton, validate, write_json)
from director_render import continuity_graph, frame_jobs, render_html, render_png

def png_chunk(kind,data):
    return struct.pack('!I',len(data))+kind+data+struct.pack('!I',zlib.crc32(kind+data)&0xffffffff)


# One complete, CRC-valid RGB image, not an arbitrary image-header stub.
PNG=(b'\x89PNG\r\n\x1a\n'+png_chunk(b'IHDR',struct.pack('!2I5B',1,1,8,2,0,0,0))
     +png_chunk(b'IDAT',zlib.compress(b'\x00\xff\xff\xff'))+png_chunk(b'IEND',b''))
EXAMPLE=ROOT/'examples/hall-shot-09/director-contract.json'


def sample():
    """Synthetic TEST_ONLY review records, never written back to the example."""
    doc=load_json(EXAMPLE)
    for src in doc['source_shots']:
        src['dialogue_baseline']={'status':'reviewed','reviewed_by':'TEST_ONLY',
            'evidence':'TEST_ONLY synthetic classification: this fixture has no spoken lines.','lines':[]}
    return doc


def fixture_source(doc):
    """Independent in-memory snapshot for synthetic tests, not a provenance service.

    Capture before any mutation being tested. Real callers must retain the imported
    source independently rather than reconstruct it from a candidate contract.
    """
    return {'source_sha256':doc['project']['source_sha256'],
            'shots':copy.deepcopy(doc['source_shots'])}


def fixture_dialogue(doc, spoken):
    src=doc['source_shots'][0]
    src['sound']=spoken
    src['dialogue_baseline']['lines']=[{'id':'TEST_ONLY_LINE_1','text':spoken,'sound_span':[0,len(spoken)]}]


def review_test_frames(doc):
    for s in doc['shots']:
        for k in s['keyframes']:
            k['generation_receipt']={'tool_call_id':'TEST_ONLY','input_asset_ids':k['reference_asset_ids'][:],
                'input_asset_sha256':{aid:digest(PNG) for aid in k['reference_asset_ids']},'output_sha256':digest(PNG)}
            k['visual_review']={'status':'passed','evidence':'TEST_ONLY synthetic record, not production verification.','reviewed_sha256':digest(PNG)}


def two_shots(duration_sec=5):
    d=sample();s=d['shots'][0];s['duration_sec']=duration_sec;s['source_span_sec']=[0,duration_sec]
    s['beats']=[{**s['beats'][0],'start_sec':0,'end_sec':duration_sec}]
    s['keyframes']=[s['keyframes'][0],s['keyframes'][-1]];s['keyframes'][-1]['time_sec']=duration_sec
    d['source_shots'][0]['duration_sec']=duration_sec
    new=copy.deepcopy(s);new.update(shot_id='S010',source_shot_no='10')
    new['continuity']['entry_state']=copy.deepcopy(s['continuity']['exit_state'])
    for k in new['keyframes']:k['id']=k['id'].replace('S009','S010')
    source=copy.deepcopy(d['source_shots'][0]);source['source_shot_no']='10'
    d['source_shots'].append(source);d['shots'].append(new)
    return d


def provide_files(doc,root):
    for a in doc['assets']:
        p=Path(root)/a['path'];p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(PNG)
    for s in doc['shots']:
        for k in s['keyframes']:
            k['image_path']=f"frames/{k['id']}.png";p=Path(root)/k['image_path'];p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(PNG)


class ImportTests(unittest.TestCase):
    def test_timecodes_and_seconds(self):
        for x in [10,'10','10秒','10s','00:10','01:07-01:17','01:07—01:17','00:01:07至00:01:17']:
            with self.subTest(x=x):self.assertEqual(duration(x),10)
    def test_ambiguous_durations_rejected(self):
        for x in ['6-8秒','约10秒','10-15','00:30-00:15',0,-1,True,'=A1+B1','NaN',float('inf'),'00:99']:
            with self.subTest(x=x):self.assertRaises(ContractError,duration,x)
    def test_csv_preserves_order_and_source(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'分镜.csv';p.write_text('镜号,时长,画面内容,声音\n9,01:07-01:17,向右跑,脚步\n11,6秒,停下,无对白\n',encoding='utf-8-sig')
            d=ingest(p);self.assertEqual(d['total_duration_sec'],16);self.assertEqual([x['source_shot_no'] for x in d['shots']],['9','11']);self.assertTrue(d['warnings']);self.assertEqual(d['shots'][0]['source_row'],2)
    def test_duplicate_shot_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'x.csv';p.write_text('镜号,时长,画面内容\n1,5,甲\n1,5,乙\n');self.assertRaises(ContractError,ingest,p)
    def test_missing_content_not_silently_skipped(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'x.csv';p.write_text('镜号,时长,画面内容\n1,5,\n');self.assertRaises(ContractError,ingest,p)
    def test_json_table(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'x.json';write_json(p,{'headers':['镜号','时长','画面内容'],'rows':[['9','10秒','原文']]});d=ingest(p);self.assertEqual(d['shots'][0]['action'],'原文')
    def test_xlsx_no_external_dependency(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'x.xlsx'
            with zipfile.ZipFile(p,'w') as z:
                z.writestr('xl/workbook.xml','<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="镜表" sheetId="1" r:id="rId1"/></sheets></workbook>')
                z.writestr('xl/_rels/workbook.xml.rels','<Relationships><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
                rows=[]
                for n,vals in enumerate([['镜号','时长','画面内容'],['9','01:07-01:17','左向右']],1):
                    cells=''.join(f'<c r="{chr(65+i)}{n}" t="inlineStr"><is><t>{v}</t></is></c>' for i,v in enumerate(vals));rows.append(f'<row r="{n}">{cells}</row>')
                z.writestr('xl/worksheets/sheet1.xml','<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'+''.join(rows)+'</sheetData></worksheet>')
            self.assertEqual(ingest(p)['total_duration_sec'],10)
    def test_nonfinite_json_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'x.json';p.write_text('{"x": NaN}');self.assertRaises(ContractError,load_json,p)


class ContractTests(unittest.TestCase):
    def test_example_plan_valid(self):self.assertTrue(validate(load_json(EXAMPLE))['ok'])
    def test_draft_cannot_compile(self):
        d=skeleton(load_json(ROOT/'examples/hall-shot-09/source-excerpt.json'));self.assertFalse(validate(d)['ok']);self.assertRaises(ContractError,compiler,d,'minimax-h3','T2VA','.')
    def test_missing_director_is_error(self):
        d=sample();d['shots'][0]['director']['viewing_task']='';self.assertIn('DIRECTOR_DECISION',[x['code'] for x in validate(d)['errors']])
    def test_nested_type_error_clean(self):
        d=sample();d['shots'][0]['camera']=None;self.assertFalse(validate(d)['ok'])
    def test_duration_drift(self):
        d=sample();d['source_shots'][0]['duration_sec']=11;self.assertIn('SOURCE_TOTAL',[x['code'] for x in validate(d)['errors']])
    def test_beat_overlap(self):
        d=sample();d['shots'][0]['beats'][1]['start_sec']=1;self.assertFalse(validate(d)['ok'])
    def test_source_order(self):
        d=two_shots();d['shots'].reverse();self.assertIn('SOURCE_ORDER',[x['code'] for x in validate(d)['errors']])
    def test_unapproved_recut(self):
        d=two_shots();d['shots'][1]['source_shot_no']='9';d['shots'][1]['source_span_sec']=[5,10];d['source_shots']=[d['source_shots'][0]];d['source_shots'][0]['duration_sec']=10
        self.assertFalse(validate(d)['ok']);d['policy'].update(edit_mode='approved_recut',recut_approval='TEST_ONLY synthetic approval of 5s + 5s camera shots; not a real user approval.');self.assertTrue(validate(d)['ok'])
    def test_missing_recut_approval(self):
        d=sample();d['policy']['edit_mode']='approved_recut';self.assertIn('RECUT_APPROVAL',[x['code'] for x in validate(d)['errors']])
    def test_state_jump(self):
        d=two_shots();d['shots'][1]['continuity']['entry_state']['stand.condition']='broken';self.assertIn('STATE_JUMP',[x['code'] for x in validate(d)['errors']])
    def test_axis_cross_and_explanation(self):
        d=two_shots();c=d['shots'][1]['continuity'];c['axis_side']='B';self.assertIn('AXIS_CROSS',[x['code'] for x in validate(d)['errors']]);c['exceptions']=[{'field':'axis_side','reason':'TEST_ONLY synthetic approval of crossing after a visible bridge; not real user approval.','approved_by_user':True}];self.assertTrue(validate(d)['ok'])
    def test_duplicate_global_frame_id(self):
        d=two_shots();d['shots'][1]['keyframes'][0]['id']=d['shots'][0]['keyframes'][0]['id'];self.assertIn('FRAME_ID',[x['code'] for x in validate(d)['errors']])
    def test_board_short_not_padded(self):
        d=two_shots(3);g=group_boards(d);self.assertEqual(g['boards'][0]['total_duration_sec'],6)
    def test_board_cap_and_long_generation_are_separate(self):
        d=two_shots(10);self.assertEqual(len(group_boards(d)['boards']),2)
        prompt,m=compiler(d,'seedance-2.5','T2V','.',draft=True);self.assertEqual(m['requested_duration_sec'],20)
        self.assertRaises(ContractError,compiler,d,'minimax-h3','T2VA','.',draft=True)
    def test_production_cannot_pass_planned_example(self):self.assertFalse(validate(sample(),'production','.')['ok'])
    def test_production_explicit_records(self):
        with tempfile.TemporaryDirectory() as t:
            d=sample();provide_files(d,t)
            review_test_frames(d)
            d['review'].update(director='approved',user='approved');self.assertTrue(validate(d,'production',t,source=fixture_source(d))['ok'])
    def test_schema(self):
        try: from jsonschema import Draft202012Validator
        except ImportError:self.skipTest('optional jsonschema absent')
        schema=load_json(ROOT/'schemas/director-contract.schema.json');Draft202012Validator.check_schema(schema)
        for doc in (load_json(EXAMPLE),sample()):
            self.assertEqual(list(Draft202012Validator(schema).iter_errors(doc)),[])


class CompilerTests(unittest.TestCase):
    def test_h3_base_structure(self):
        d=sample();p,m=compiler(d,'minimax-h3','T2VA','.',source=fixture_source(d))
        self.assertTrue(p.startswith('integrated_multimodal_description:'));self.assertNotIn('[Shot 2]',p);self.assertEqual(m['upload_plan'],[]);self.assertFalse(m['submitted']);self.assertIsNone(m['provider_payload'])
    def test_h3_reference_six_sections(self):
        p,m=compiler(sample(),'minimax-h3','Ref2VA','.',draft=True)
        fields=['subject_definitions:','summary:','retention_analysis:','detailed_description:','overall_soundscape:','non_diegetic_music:']
        self.assertEqual(sorted(fields,key=p.index),fields);self.assertNotIn('keyframe completion',p);self.assertEqual(m['status'],'draft_missing_assets');self.assertFalse(m['submitted'])
    def test_h3_missing_english_fails(self):
        d=sample();source=fixture_source(d);d['shots'][0]['opening']['en']='';self.assertRaisesRegex(ContractError,'English|translation|en',compiler,d,'minimax-h3','T2VA','.',source=source)
    def test_h3_cut_time_not_beat_time(self):
        d=two_shots();p,m=compiler(d,'minimax-h3','T2VA','.',source=fixture_source(d));self.assertIn('[Shot 2] At 00:05.000',p);self.assertNotIn('[Shot 3]',p)
    def test_missing_references_fail_without_draft(self):
        d=sample();review_test_frames(d);self.assertRaisesRegex(ContractError,'Missing (actual image/reference files|generation-time input asset)',compiler,d,'minimax-h3','I2VA','.',source=fixture_source(d))
    def test_keyframe_mode_only_keyframes(self):
        with tempfile.TemporaryDirectory() as t:
            d=sample();provide_files(d,t);review_test_frames(d);p,m=compiler(d,'minimax-h3','FL2VA',t,source=fixture_source(d));self.assertEqual([a['role'] for a in m['upload_plan']],['first_frame','last_frame']);self.assertEqual(len(m['upload_plan']),2);self.assertNotIn('subject_definitions:',p)
    def test_no_silent_prompt_truncation(self):
        d=sample();self.assertRaises(ContractError,compiler,d,'seedance-2.0','T2V','.',char_limit=20,source=fixture_source(d))
    def test_legacy_2000_budget(self):
        p,m=compiler(sample(),'seedance-2.0','REF','.',draft=True);self.assertLessEqual(m['prompt_char_count'],2000);self.assertIn('2–7秒',p)
    def test_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as t:
            d=sample();provide_files(d,t);d['assets'][0]['sha256']='0'*64;self.assertRaisesRegex(ContractError,'changed since approval',compiler,d,'seedance-2.5','REF',t,source=fixture_source(d))
    def test_path_traversal(self):
        for rel in ['../secret.txt','/etc/passwd','C:\\Users\\x.png','https://example.com/a.png']:
            with self.subTest(rel=rel):self.assertRaises(ContractError,project_path,'.',rel)
    def test_review_board_is_not_valid_ref_role(self):
        d=sample();d['assets'][0]['role']='review_board';self.assertFalse(validate(d)['ok'])
    def test_min_duration_no_padding(self):
        d=two_shots(3);self.assertRaisesRegex(ContractError,'outside',compiler,d,'minimax-h3','T2VA','.',ids=['S009'],source=fixture_source(d))
    def test_fractional_duration_no_rounding(self):
        d=two_shots(4.25);self.assertRaisesRegex(ContractError,'whole-second',compiler,d,'minimax-h3','T2VA','.',ids=['S009'],source=fixture_source(d))
    def test_noncontiguous_job_rejected(self):
        d=two_shots();third=copy.deepcopy(d['shots'][-1]);third.update(shot_id='S011',source_shot_no='11')
        for k in third['keyframes']:k['id']=k['id'].replace('S010','S011')
        third['continuity']['entry_state']=copy.deepcopy(d['shots'][-1]['continuity']['exit_state']);d['shots'].append(third);src=copy.deepcopy(d['source_shots'][-1]);src['source_shot_no']='11';d['source_shots'].append(src)
        self.assertRaises(ContractError,compiler,d,'minimax-h3','T2VA','.',ids=['S009','S011'],source=fixture_source(d))
    def test_dialogue_verbatim_and_speaker(self):
        d=sample();spoken='爸，您带我来能看出啥？我又不懂这些。';fixture_dialogue(d,spoken)
        d['shots'][0]['dialogue']=[{'source_dialogue_id':'TEST_ONLY_LINE_1','start_sec':1,'end_sec':8,'speaker_id':'xiao_nan_hai','speaker_label':{'zh':'小男孩','en':'the boy'},'text':spoken,'language':'Mandarin','delivery':{'zh':'小声','en':'quietly'},'mode':'onscreen'}]
        p,m=compiler(d,'minimax-h3','Ref2VA','.',draft=True);self.assertEqual(p.count(spoken),1);self.assertIn('<Subject 1> (S1)',p);self.assertIn('<d>[Mandarin] '+spoken+'</d>',p)
        d['shots'][0]['dialogue'][0]['text']='改写后的台词';self.assertFalse(validate(d)['ok'])
    def test_voiceover_closed_lips(self):
        d=sample();fixture_dialogue(d,'原台词');d['shots'][0]['dialogue']=[{'source_dialogue_id':'TEST_ONLY_LINE_1','start_sec':1,'end_sec':3,'speaker_id':'narrator','speaker_label':{'zh':'旁白','en':'the narrator'},'text':'原台词','language':'Mandarin','delivery':{'zh':'平静','en':'calmly'},'mode':'voiceover'}]
        p,m=compiler(d,'minimax-h3','T2VA','.',source=fixture_source(d));self.assertIn('narrates in a non-diegetic voiceover',p);self.assertIn("Do not animate any visible character's lips for this line",p)


class RenderingTests(unittest.TestCase):
    def test_missing_frames_explicit(self):
        p=render_html(sample(),'.');self.assertIn('未生成',p);self.assertNotIn('data:image/png',p)
    def test_html_escapes_content(self):
        d=sample();d['project']['name']='<script>alert(1)</script>';p=render_html(d,'.');self.assertNotIn('<script>',p);self.assertIn('&lt;script&gt;',p)
    def test_html_embeds_only_actual_images(self):
        with tempfile.TemporaryDirectory() as t:
            d=sample();provide_files(d,t);p=render_html(d,t);self.assertIn('data:image/png;base64,',p)
    def test_frame_jobs_do_not_generate(self):
        d=frame_jobs(sample(),'.');self.assertEqual(len(d['jobs']),4);self.assertTrue(all(not j['executed'] and j['tool_call_id'] is None for j in d['jobs']));self.assertTrue(all(j['status']=='blocked_missing_references' for j in d['jobs']))
    def test_graph_explicit_not_visual(self):
        g=continuity_graph(two_shots());self.assertEqual(len(g['edges']),1);self.assertTrue(g['edges'][0]['requires_visual_comparison'])
    def test_png_multiboard_not_silently_dropped(self):
        with tempfile.TemporaryDirectory() as t:self.assertRaises(ContractError,render_png,two_shots(10),t,str(Path(t)/'x.png'))




class CLITests(unittest.TestCase):
    def call(self,*args):return subprocess.run([sys.executable,str(ROOT/'scripts/director_pipeline.py'),*map(str,args)],capture_output=True,text=True,encoding='utf-8')
    def test_validate_cli(self):self.assertEqual(self.call('validate',EXAMPLE).returncode,0)
    def test_draft_compile_marks_missing(self):
        with tempfile.TemporaryDirectory() as t:
            r=self.call('compile',EXAMPLE,'--profile','minimax-h3','--mode','Ref2VA','--asset-root',t,'--out-dir',Path(t)/'out','--draft');self.assertEqual(r.returncode,0,r.stderr);m=load_json(Path(t)/'out/manifest.json');self.assertEqual(m['status'],'draft_missing_assets')
    def test_refuse_overwrite(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'out.json';p.write_text('KEEP');r=self.call('group',EXAMPLE,'--out',p);self.assertEqual(r.returncode,2);self.assertEqual(p.read_text(),'KEEP')
    def test_source_snapshot_guard(self):
        with tempfile.TemporaryDirectory() as t:
            d=sample();d['source_shots'][0]['action']='tampered source';p=Path(t)/'d.json';write_json(p,d);r=self.call('validate',p,'--source',ROOT/'examples/hall-shot-09/source-excerpt.json');self.assertEqual(r.returncode,2);self.assertIn('SOURCE_SNAPSHOT_CHANGED',r.stdout)

if __name__=='__main__':unittest.main()
