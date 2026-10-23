from __future__ import annotations
import copy
from decimal import Decimal
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from director_core import ContractError, compiler, digest
from director_render import frame_jobs
from director_review_plan import MAX_WINDOWS, MAX_SEGMENTS, plan_review
from test_director_pipeline import two_shots


def single(duration=18):
    doc = two_shots(duration)
    doc['shots'] = doc['shots'][:1]
    doc['source_shots'] = doc['source_shots'][:1]
    return doc


def explicit(*ranges):
    return [{'segments': [{'source_shot_id': 'S009', 'review_start_sec': a,
                           'review_end_sec': z}]} for a, z in ranges]


class ReviewPlanTests(unittest.TestCase):
    def test_duration_matrix_and_exact_coverage(self):
        for duration, count in [(14.999,1),(15,1),(15.001,2),(18,2),(30,2),(31,3),
                                (30.000000000000004,2)]:
            with self.subTest(duration=duration):
                doc = single(duration)
                plan = plan_review(doc)
                self.assertEqual(len(plan['windows']), count)
                self.assertEqual(plan['total_duration_sec'], duration)
                last = 0
                for w in plan['windows']:
                    s = w['segments'][0]
                    self.assertEqual(s['review_start_sec'], last)
                    last = s['review_end_sec']
                    self.assertFalse(s['cut_before'])
                    self.assertFalse(s['cut_after'])
                self.assertEqual(last, duration)

    def test_greedy_short_group_scene_boundary(self):
        doc = two_shots(5)
        self.assertEqual(len(plan_review(doc)['windows']), 1)
        doc['shots'][1]['scene_id'] = 'SC_OTHER'
        self.assertEqual(len(plan_review(doc)['windows']), 2)
        doc = two_shots(10)
        self.assertEqual(len(plan_review(doc)['windows']), 2)

    def test_beat_boundary_preferred_and_review_only_fallback(self):
        doc = single()
        beat = doc['shots'][0]['beats'][0]
        doc['shots'][0]['beats'] = [{**beat, 'start_sec':0,'end_sec':12},
                                   {**beat,'start_sec':12,'end_sec':18}]
        plan = plan_review(doc)
        self.assertEqual(plan['windows'][0]['duration_sec'], 12)
        self.assertEqual(plan['windows'][0]['segments'][0]['boundary_end_kind'], 'beat_endpoint')
        doc['shots'][0]['beats'] = [beat]
        self.assertEqual(plan_review(doc)['windows'][0]['segments'][0]['boundary_end_kind'], 'review_only')

    def test_explicit_windows_and_metadata_not_invented(self):
        doc = single()
        plan = plan_review(doc, explicit((0,12),(12,18)))
        first, last = [w['segments'][0] for w in plan['windows']]
        self.assertEqual([f['time_sec'] for f in first['keyframes']], [0])
        self.assertEqual([f['time_sec'] for f in last['keyframes']], [18])
        self.assertEqual(first['beats'][0]['original']['end_sec'], 18)
        self.assertTrue(first['beats'][0]['continues_across_windows'])
        self.assertEqual(first['frame_status'], 'no_generated_keyframes_in_window')
        plan['windows'][0]['segments'][0]['keyframes'] = [{'id':'FAKE','time_sec':12}]
        checked = plan_review(doc, plan)
        self.assertNotIn('FAKE', str(checked))

    def test_boundary_frames_belong_once_and_dialogue_full_text(self):
        doc = single()
        shot = doc['shots'][0]
        frame = copy.deepcopy(shot['keyframes'][0])
        frame.update(id='S009-MIDDLE', phase='development', time_sec=12)
        shot['keyframes'].insert(1,frame)
        line = {'speaker_id':'TEST','text':'完整对白','start_sec':10,'end_sec':16, 'speaker_label':{'zh':'测试','en':'Test'}, 'language':'zh', 'delivery':{'zh':'平静','en':'Calm'}, 'mode':'offscreen'}
        shot['dialogue'] = [line]
        doc['source_shots'][0]['sound'] = '完整对白'
        doc['source_shots'][0].pop('dialogue_baseline', None)
        plan = plan_review(doc, explicit((0,12),(12,18)))
        segments = [w['segments'][0] for w in plan['windows']]
        self.assertEqual([f['id'] for s in segments for f in s['keyframes']],
                         [f['id'] for f in shot['keyframes']])
        for segment in segments:
            self.assertEqual(segment['dialogue'][0]['original'], line)
            self.assertTrue(segment['dialogue'][0]['continues_across_windows'])

    def test_reject_bad_windows(self):
        bad = [explicit((0,12),(13,18)), explicit((0,12),(11,18)),
               explicit((12,18),(0,12)), explicit((0,18)), explicit((0,12)),
               explicit((0,12),(12,12),(12,18)), explicit((0,float('nan'))),
               explicit((0,float('inf'))), explicit((False,12),(12,18)),
               explicit((0,-1)), [], {'windows':None}]
        for windows in bad:
            with self.subTest(windows=windows), self.assertRaises(ContractError):
                plan_review(single(), windows)

    def test_reject_stale_hash_and_forged_duration(self):
        doc = single()
        plan = plan_review(doc)
        plan['contract_sha256'] = 'stale'
        with self.assertRaises(ContractError): plan_review(doc, plan)
        plan = plan_review(doc)
        plan['windows'][0]['duration_sec'] = 1
        with self.assertRaises(ContractError): plan_review(doc, plan)

    def test_no_mutation_no_jobs_no_production_bypass(self):
        doc = single()
        before = digest(doc)
        jobs = frame_jobs(doc, ROOT)
        plan_review(doc)
        self.assertEqual(digest(doc), before)
        self.assertEqual(frame_jobs(doc, ROOT), jobs)
        with self.assertRaises(ContractError):
            compiler(doc, 'seedance-2.0', 'T2V', ROOT, draft=True)

    def test_capacity_tiny_cap_and_explicit_huge_input(self):
        doc = single(18)
        doc['policy']['board_max_duration_sec'] = 1e-12
        before = digest(doc)
        with self.assertRaisesRegex(ContractError, 'capacity'):
            plan_review(doc)
        self.assertEqual(digest(doc), before)
        doc = single(18)
        item = explicit((0, 12))[0]
        with self.assertRaisesRegex(ContractError, 'capacity'):
            plan_review(doc, [item] * (MAX_WINDOWS + 1))
        with self.assertRaisesRegex(ContractError, 'capacity'):
            plan_review(doc, [{'segments': item['segments'] * (MAX_SEGMENTS + 1)}])

    def test_auto_loop_budget_when_beats_reduce_window_packing(self):
        doc = single(44)
        beat = doc['shots'][0]['beats'][0]
        doc['shots'][0]['beats'] = [{**beat, 'start_sec': a, 'end_sec': z}
                                    for a, z in [(0,3),(3,18),(18,33),(33,44)]]
        with patch('director_review_plan.MAX_WINDOWS', 2):
            with self.assertRaisesRegex(ContractError, 'capacity'):
                plan_review(doc)
        # Ideal packing needs 3 windows, beat-preferred packing needs 4.
        with patch('director_review_plan.MAX_WINDOWS', 3):
            with self.assertRaisesRegex(ContractError, 'capacity'):
                plan_review(doc)

    def test_decimal_short_group_no_tiny_tails(self):
        doc = two_shots(0.1)
        plan = plan_review(doc)
        self.assertEqual(plan['total_duration_sec'], 0.2)
        self.assertEqual(len(plan['windows']), 1)
        self.assertEqual(sum(Decimal(str(s['duration_sec'])) for s in plan['windows'][0]['segments']), Decimal('0.2'))


if __name__ == '__main__': unittest.main()
