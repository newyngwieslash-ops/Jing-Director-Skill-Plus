"""Synthetic fixtures test deterministic gates, never real approval or generation."""
import copy
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from director_core import ContractError, compiler, digest, frame_at, validate


def fixture(speech=False):
    d = json.loads((ROOT / 'examples/hall-shot-09/director-contract.json').read_text())
    src = d['source_shots'][0]
    baseline = {'status': 'reviewed', 'reviewed_by': 'TEST_ONLY', 'evidence': 'SYNTHETIC fixture, not human approval', 'lines': []}
    src['dialogue_baseline'] = baseline
    if speech:
        src['sound'] = 'footsteps; Hello. Goodbye.'
        lines = [('D1', 'Hello.', 1), ('D2', 'Goodbye.', 4)]
        d['shots'][0]['dialogue'] = []
        for qid, text, start in lines:
            at = src['sound'].index(text)
            baseline['lines'].append({'id': qid, 'text': text, 'sound_span': [at, at + len(text)]})
            d['shots'][0]['dialogue'].append({'source_dialogue_id': qid, 'text': text, 'start_sec': start, 'end_sec': start + 1, 'speaker_id': 'TEST_SPEAKER', 'speaker_label': {'zh': '测试人物', 'en': 'Test speaker'}, 'delivery': {'zh': '平静', 'en': 'calmly'}, 'language': 'English', 'mode': 'onscreen'})
    return d


def independent(d):
    # Synthetic independently retained copy; never derive this from real mutable contracts.
    return {'source_sha256': d['project']['source_sha256'], 'shots': copy.deepcopy(d['source_shots'])}


def png():
    def chunk(t, data):
        return struct.pack('>I', len(data)) + t + data + struct.pack('>I', zlib.crc32(t + data) & 0xffffffff)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(b'\x00\xff\x00\x00')) + chunk(b'IEND', b'')


def media(d, root):
    data = png(); h = digest(data)
    for a in d['assets']:
        a['path'] = a['id'] + '.png'; (root / a['path']).write_bytes(data)
    for shot in d['shots']:
        for f in shot['keyframes']:
            f['image_path'] = f['id'] + '.png'; (root / f['image_path']).write_bytes(data)
            f['generation_receipt'] = {'tool_call_id': 'TEST_ONLY', 'input_asset_ids': f['reference_asset_ids'], 'input_asset_sha256': {aid: h for aid in f['reference_asset_ids']}, 'output_sha256': h}
            f['visual_review'] = {'status': 'passed', 'evidence': 'SYNTHETIC assertion only', 'reviewed_sha256': h}
    d['review'].update(director='approved', user='approved')


class IntegrityRegressionTests(unittest.TestCase):
    def test_duplicate_exit_rejected_and_selector_consistent(self):
        d = fixture(); d['shots'][0]['keyframes'][-2]['phase'] = 'exit'
        self.assertFalse(validate(d)['ok'])
        with self.assertRaises(ContractError): frame_at(d['shots'][0], 'exit')

    def test_duplicate_entry_rejected(self):
        d = fixture(); d['shots'][0]['keyframes'][1]['phase'] = 'entry'
        self.assertFalse(validate(d)['ok'])

    def test_missing_nested_fields_are_reported(self):
        for field in ('name', 'style', 'aspect_ratio'):
            d = fixture(); del d['project'][field]
            self.assertFalse(validate(d)['ok'])
        d = fixture(); del d['shots'][0]['dialogue']
        self.assertFalse(validate(d)['ok'])

    def test_malformed_receipt_reports_without_crash(self):
        d = fixture(); d['shots'][0]['keyframes'][0]['generation_receipt'] = {'tool_call_id': 'TEST', 'input_asset_ids': [None]}
        self.assertFalse(validate(d)['ok'])

    def test_huge_source_span_integer_is_reported_not_crash(self):
        d = fixture(True); d['source_shots'][0]['dialogue_baseline']['lines'][0]['sound_span'] = [0, 10**400]
        self.assertFalse(validate(d)['ok'])

    def test_bool_is_not_duration(self):
        d = fixture(); d['shots'][0]['duration_sec'] = True
        self.assertFalse(validate(d)['ok'])

    def test_exact_speech_passes(self):
        d = fixture(True)
        self.assertTrue(validate(d, source=independent(d))['ok'])

    def test_speech_omission_duplicate_reorder_rejected(self):
        for operation in ('omit_all', 'omit_one', 'duplicate', 'reverse'):
            d = fixture(True); source = independent(d); q = d['shots'][0]['dialogue']
            if operation == 'omit_all': q.clear()
            elif operation == 'omit_one': q.pop()
            elif operation == 'duplicate': q.append(copy.deepcopy(q[0]))
            else: q[0]['start_sec'], q[0]['end_sec'], q[1]['start_sec'], q[1]['end_sec'] = 4, 5, 1, 2
            self.assertIn('DIALOGUE_COVERAGE', {e['code'] for e in validate(d, source=source)['errors']})

    def test_sound_effects_are_not_invented_as_speech(self):
        d = fixture()
        self.assertTrue(validate(d, source=independent(d))['ok'])
        self.assertEqual(d['shots'][0]['dialogue'], [])

    def test_bad_source_character_span_rejected(self):
        d = fixture(True); d['source_shots'][0]['dialogue_baseline']['lines'][0]['sound_span'][0] = 0
        self.assertFalse(validate(d, source=independent(d))['ok'])

    def test_contract_and_embedded_source_rewrite_cannot_evade_snapshot(self):
        d = fixture(True); source = independent(d)
        d['source_shots'][0]['dialogue_baseline']['lines'].clear(); d['shots'][0]['dialogue'].clear()
        self.assertIn('SOURCE_SNAPSHOT_CHANGED', {e['code'] for e in validate(d, source=source)['errors']})

    def test_legacy_plan_warns_non_draft_compile_blocks(self):
        d = fixture(); del d['source_shots'][0]['dialogue_baseline']
        r = validate(d); self.assertTrue(r['ok']); self.assertTrue(r['warnings'])
        with self.assertRaises(ContractError): compiler(d, 'minimax-h3', 'T2VA', '.', source=independent(d))

    def test_both_families_preserve_all_modes(self):
        for profile, mode, markers in [('seedance-2.0', 'T2V', ['画内对白', '场景内画外对白', '非叙事空间旁白']), ('minimax-h3', 'T2VA', ['says on screen', 'speaks from off screen', 'non-diegetic voiceover'])]:
            prompts = []
            for dialogue_mode, marker in zip(('onscreen', 'offscreen', 'voiceover'), markers):
                d = fixture(True)
                for q in d['shots'][0]['dialogue']: q['mode'] = dialogue_mode
                prompt, manifest = compiler(d, profile, mode, '.', source=independent(d), char_limit=20000)
                self.assertIn(marker, prompt); self.assertFalse(manifest['submitted']); prompts.append(prompt)
            self.assertEqual(len(set(prompts)), 3)

    def test_approved_media_tamper_rejected_by_production_and_compiler(self):
        with tempfile.TemporaryDirectory() as t:
            d = fixture(); root = Path(t); media(d, root); source = independent(d)
            self.assertTrue(validate(d, 'production', root, source)['ok'])
            f = d['shots'][0]['keyframes'][-1]; (root / f['image_path']).write_bytes(png() + b'tampered')
            self.assertFalse(validate(d, 'production', root, source)['ok'])
            with self.assertRaises(ContractError): compiler(d, 'minimax-h3', 'FL2VA', root, source=source)

    def test_review_hash_missing_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            d = fixture(); root = Path(t); media(d, root)
            del d['shots'][0]['keyframes'][0]['visual_review']['reviewed_sha256']
            self.assertFalse(validate(d, 'production', root, independent(d))['ok'])
            with self.assertRaises(ContractError): compiler(d, 'minimax-h3', 'I2VA', root, source=independent(d))

    def test_empty_or_invalid_image_rejected_even_with_matching_claimed_hashes(self):
        for content in (b'', b'not an image'):
            with tempfile.TemporaryDirectory() as t:
                d = fixture(); root = Path(t); media(d, root); f = d['shots'][0]['keyframes'][0]
                (root / f['image_path']).write_bytes(content)
                f['generation_receipt']['output_sha256'] = f['visual_review']['reviewed_sha256'] = digest(content)
                self.assertFalse(validate(d, 'production', root, independent(d))['ok'])

    def test_missing_tool_call_or_extra_unbound_input_blocks_compile(self):
        for mutation in ('tool_call', 'extra_input'):
            with tempfile.TemporaryDirectory() as t:
                d = fixture(); root = Path(t); media(d, root)
                receipt = d['shots'][0]['keyframes'][0]['generation_receipt']
                if mutation == 'tool_call': receipt['tool_call_id'] = ''
                else: receipt['input_asset_ids'] = receipt['input_asset_ids'] + ['UNKNOWN_INPUT']
                with self.assertRaises(ContractError): compiler(d, 'minimax-h3', 'I2VA', root, source=independent(d))

    def test_recut_maps_each_source_line_once_across_parts(self):
        d = fixture(True)
        d['policy'].update(edit_mode='approved_recut', recut_approval='TEST_ONLY synthetic recut')
        original = d['shots'][0]; first = copy.deepcopy(original); second = copy.deepcopy(original)
        for i, shot in enumerate((first, second)):
            shot['shot_id'] = 'TEST_PART_' + str(i)
            shot['duration_sec'] = 5; shot['source_span_sec'] = [i * 5, (i + 1) * 5]
            shot['beats'] = [dict(shot['beats'][0], start_sec=0, end_sec=5)]
            shot['keyframes'] = [shot['keyframes'][0], shot['keyframes'][-1]]
            shot['keyframes'][0]['time_sec'] = 0; shot['keyframes'][-1]['time_sec'] = 5
            for f in shot['keyframes']: f['id'] += '-part' + str(i)
            shot['dialogue'] = [dict(original['dialogue'][i], start_sec=1, end_sec=2)]
        second['continuity']['entry_state'] = copy.deepcopy(first['continuity']['exit_state'])
        d['shots'] = [first, second]
        self.assertTrue(validate(d, source=independent(d))['ok'])
        second['dialogue'] = copy.deepcopy(first['dialogue'])
        self.assertIn('DIALOGUE_COVERAGE', {e['code'] for e in validate(d, source=independent(d))['errors']})

    def test_generation_input_reference_hash_binding(self):
        with tempfile.TemporaryDirectory() as t:
            d = fixture(); root = Path(t); media(d, root)
            a = d['assets'][0]; (root / a['path']).write_bytes(png() + b'changed')
            report = validate(d, 'production', root, independent(d))
            self.assertIn('INPUT_ASSET_INTEGRITY', {e['code'] for e in report['errors']})


if __name__ == '__main__': unittest.main()
