"""Regression checks for source-bound, offline blocking deliverables."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from director_core import ContractError, digest, load_json
from director_blocking import build, validate_blocking


def fixture():
    path = ROOT / 'examples/hall-shot-09'
    contract = load_json(path / 'director-contract.json')
    spec = load_json(path / 'blocking-spec.json')
    roster = load_json(path / 'roster.json')
    registry = load_json(path / 'identity-registry.json')
    # Short synthetic route retains every contract subject and every group member.
    shot = spec['scenes'][0]['shots'][0]
    shot['characters'][0]['exit']['x'] = 4
    shot['trajectories'] = [dict(who='xiao_nan_hai', beat_index=0, start_sec=0,
        end_sec=2, points=[[2, 2], [4, 2]], reason='测试路线，不是拍摄批准')]
    return spec, contract, roster, registry


def add_shot(spec, contract, roster, scene_id=None):
    shot = copy.deepcopy(contract['shots'][0])
    shot.update(shot_id='S010', source_shot_no='10')
    if scene_id: shot['scene_id'] = scene_id
    shot['continuity']['entry_state'] = copy.deepcopy(contract['shots'][0]['continuity']['exit_state'])
    for frame in shot['keyframes']: frame['id'] = frame['id'].replace('S009', 'S010')
    contract['shots'].append(shot)
    contract['source_shots'].append({**contract['source_shots'][0], 'source_shot_no': '10'})
    bs = copy.deepcopy(spec['scenes'][0]['shots'][0])
    bs.update(shot_id='S010', source_shot_no='10', trajectories=[])
    bs['characters'][0]['entry']['x'] = 4
    if scene_id:
        spec['scenes'].append(dict(scene_id=scene_id, location_id='hall', cast_ids=list(spec['scenes'][0]['cast_ids']), shots=[bs]))
    else:
        spec['scenes'][0]['shots'].append(bs)
    spec['contract_sha256'] = digest(contract)
    roster['contract_sha256'] = digest(contract)
    if scene_id:
        roster['scenes'].append(dict(scene_id=scene_id, cast_ids=list(spec['scenes'][0]['cast_ids']), expected_count=10))


class BlockingTests(unittest.TestCase):
    def test_valid_and_deliverables_need_review(self):
        spec, contract, roster, registry = fixture()
        self.assertTrue(validate_blocking(spec, contract, roster, identity_registry=registry)['ok'])
        with tempfile.TemporaryDirectory() as tmp:
            report = build(spec, contract, Path(tmp) / 'out', roster=roster, identity_registry=registry)
            self.assertEqual(report['review_status'], 'needs_manual_review')
            out = Path(tmp) / 'out'
            for name in ['overview.svg', 'shot-001/entry.svg', 'shot-001/exit.svg', 'shot-001/movement.svg']:
                ET.parse(out / 'scene-001' / name)
            manifest = json.loads((out / 'manifest.json').read_text(encoding='utf8'))
            self.assertEqual(manifest['source_contract_sha256'], digest(contract))
            self.assertTrue((out / 'index.html').exists())
            self.assertRaises(ContractError, build, spec, contract, out, roster=roster, identity_registry=registry)

    def test_invalid_inputs_rejected_without_images(self):
        def move_start(s): s['scenes'][0]['shots'][0]['trajectories'][0]['points'][0] = [3, 2]
        def move_end(s): s['scenes'][0]['shots'][0]['trajectories'][0]['points'][-1] = [5, 2]
        mutations = [
            lambda s: s.update(contract_sha256='bad'),
            lambda s: s['scenes'][0].update(shots=[]),
            lambda s: s['scenes'][0]['shots'].append(copy.deepcopy(s['scenes'][0]['shots'][0])),
            lambda s: s['scenes'][0]['shots'][0]['evidence'][0].update(quote='捏造剧情'),
            lambda s: s['scenes'][0]['shots'][0]['characters'][0].update(id='UNKNOWN'),
            lambda s: s['scenes'][0]['shots'][0].update(trajectories=[]), move_start, move_end,
            lambda s: s['scenes'][0]['shots'][0]['trajectories'][0].update(end_sec=999),
            lambda s: s['scenes'][0]['shots'][0]['characters'][0]['entry'].update(x=float('nan')),
            lambda s: s['locations'][0]['bounds'].update(w=0),
            lambda s: s['locations'].append(copy.deepcopy(s['locations'][0])),
            lambda s: s['scenes'][0]['shots'][0]['trajectories'][0].update(beat_index=True),
            lambda s: s['scenes'][0]['shots'][0].update(duration_sec=1),
            lambda s: s['scenes'][0]['shots'][0].update(source_shot_no='other'),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate), tempfile.TemporaryDirectory() as tmp:
                spec, contract, roster, registry = fixture(); mutate(spec)
                self.assertFalse(validate_blocking(spec, contract, roster, identity_registry=registry)['ok'])
                self.assertRaises(ContractError, build, spec, contract, tmp, roster=roster, identity_registry=registry)
                self.assertFalse(list(Path(tmp).rglob('*.svg')))

    def test_order_continuity_and_transition(self):
        spec, contract, roster, registry = fixture(); add_shot(spec, contract, roster)
        self.assertTrue(validate_blocking(spec, contract, roster, identity_registry=registry)['ok'])
        spec['scenes'][0]['shots'].reverse()
        self.assertFalse(validate_blocking(spec, contract, roster, identity_registry=registry)['ok'])
        spec['scenes'][0]['shots'].reverse()
        shot = spec['scenes'][0]['shots'][1]
        shot['characters'][0]['entry']['x'] = 8
        shot['characters'][0]['exit']['x'] = 8
        shot['cut'] = 'teleport'
        self.assertFalse(validate_blocking(spec, contract, roster, identity_registry=registry)['ok'])
        shot['transition'] = dict(kind='time_jump', evidence='原片中有时间间隔，需导演复核')
        report = validate_blocking(spec, contract, roster, identity_registry=registry)
        self.assertTrue(report['ok']); self.assertTrue(report['warnings'])
        self.assertEqual(report['review_status'], 'needs_manual_review')

    def test_empty_scene_cast_is_valid_only_with_empty_contract_subjects(self):
        path = ROOT / 'examples/blocking-demo'
        spec = load_json(path / 'blocking-spec.json')
        contract = load_json(path / 'director-contract.json')
        roster = load_json(path / 'roster.json')
        registry = load_json(path / 'identity-registry.json')
        self.assertTrue(validate_blocking(spec, contract, roster, identity_registry=registry)['ok'])
        spec['scenes'][0]['cast_ids'] = []
        self.assertFalse(validate_blocking(spec, contract, roster, identity_registry=registry)['ok'])

    def test_xml_escaping_and_safe_output_paths(self):
        spec, contract, roster, registry = fixture()
        malicious = '../../escape<script>&"'
        spec['cast'][0]['name'] = malicious
        contract['shots'][0]['scene_id'] = malicious
        spec['scenes'][0]['scene_id'] = malicious
        roster['scenes'][0]['scene_id'] = malicious
        spec['locations'][0]['name'] = malicious
        spec['contract_sha256'] = digest(contract)
        roster['contract_sha256'] = digest(contract)
        with tempfile.TemporaryDirectory() as tmp:
            build(spec, contract, tmp, roster=roster, identity_registry=registry)
            svg = (Path(tmp) / 'scene-001/overview.svg').read_text(encoding='utf8')
            ET.fromstring(svg)
            self.assertNotIn('<script>', svg)
            self.assertNotIn('<script>', (Path(tmp) / 'index.html').read_text(encoding='utf8'))
            self.assertEqual(len(list(Path(tmp).rglob('*.svg'))), 4)

    def test_facing_wrap_and_visibility_change(self):
        spec, contract, roster, registry = fixture(); add_shot(spec, contract, roster)
        state = spec['scenes'][0]['shots'][1]['characters'][0]['entry']
        state.update(facing_deg=360, visibility='offscreen')
        self.assertTrue(validate_blocking(spec, contract, roster, identity_registry=registry)['ok'])

    def test_overlap_and_disconnected_routes(self):
        spec, contract, roster, registry = fixture()
        routes = spec['scenes'][0]['shots'][0]['trajectories']
        routes.append(copy.deepcopy(routes[0]))
        self.assertFalse(validate_blocking(spec, contract, roster, identity_registry=registry)['ok'])

    def test_multi_route_chain_and_collision_warning(self):
        spec, contract, roster, registry = fixture()
        routes = spec['scenes'][0]['shots'][0]['trajectories']
        mid = routes[0]['end_sec'] / 2
        routes.append({**routes[0], 'start_sec': mid, 'points': [[3, 2], [4, 2]]})
        routes[0].update(end_sec=mid, points=[[2, 2], [3, 2]])
        spec['locations'][0]['landmarks'] = [dict(id='desk', label='桌子', x=3, y=2, w=1, h=1, blocking=True)]
        report = validate_blocking(spec, contract, roster, identity_registry=registry)
        self.assertTrue(report['ok'])
        self.assertIn('OBSTACLE_REVIEW', [w['code'] for w in report['warnings']])
        routes[1]['points'][0] = [3.1, 2]
        self.assertFalse(validate_blocking(spec, contract, roster, identity_registry=registry)['ok'])

    def test_scene_return_is_reviewed_without_false_adjacency(self):
        spec, contract, roster, registry = fixture(); add_shot(spec, contract, roster, 'other_scene')
        third = copy.deepcopy(contract['shots'][1]); third.update(shot_id='S011', source_shot_no='11', scene_id=contract['shots'][0]['scene_id'])
        for frame in third['keyframes']: frame['id'] = frame['id'].replace('S010', 'S011')
        contract['shots'].append(third)
        contract['source_shots'].append({**contract['source_shots'][1], 'source_shot_no': '11'})
        bs = copy.deepcopy(spec['scenes'][1]['shots'][0]); bs.update(shot_id='S011', source_shot_no='11')
        for phase in ['entry', 'exit']: bs['characters'][0][phase]['x'] = 8
        spec['scenes'][0]['shots'].append(bs); spec['contract_sha256'] = digest(contract)
        roster['contract_sha256'] = digest(contract)
        report = validate_blocking(spec, contract, roster, identity_registry=registry)
        self.assertTrue(report['ok'])
        self.assertIn('SCENE_RETURN_REVIEW', [w['code'] for w in report['warnings']])

    def test_hall_example_expands_six_subjects_to_ten_people(self):
        path = ROOT / 'examples/hall-shot-09'
        spec = load_json(path / 'blocking-spec.json')
        contract = load_json(path / 'director-contract.json')
        roster = load_json(path / 'roster.json')
        registry = load_json(path / 'identity-registry.json')
        self.assertEqual(len(contract['shots'][0]['subjects']), 6)
        self.assertEqual(len(spec['cast']), 10)
        self.assertEqual(sum(s['expected_count'] for s in roster['subjects']), 10)
        self.assertEqual(len(spec['scenes'][0]['shots'][0]['characters']), 10)
        self.assertTrue(validate_blocking(spec, contract, roster, identity_registry=registry)['ok'])
        # Missing people must not become a valid 'empty' shot or collapsed group.
        for missing in ('employee_4', 'tourist_2', 'lu_jing_tian'):
            broken = copy.deepcopy(spec)
            shot = broken['scenes'][0]['shots'][0]
            shot['characters'] = [p for p in shot['characters'] if p['id'] != missing]
            self.assertFalse(validate_blocking(broken, contract, roster, identity_registry=registry)['ok'])
        self.assertFalse(validate_blocking(spec, contract, identity_registry=registry)['ok'])

    def test_malformed_nested_types_fail_cleanly(self):
        for key, value in [('characters', None), ('trajectories', [None]), ('evidence', 'text')]:
            spec, contract, roster, registry = fixture(); spec['scenes'][0]['shots'][0][key] = value
            self.assertFalse(validate_blocking(spec, contract, roster, identity_registry=registry)['ok'])

    def test_packaged_example_and_manifest_hashes(self):
        path = ROOT / 'examples/blocking-demo'
        spec = load_json(path / 'blocking-spec.json'); contract = load_json(path / 'director-contract.json')
        roster = load_json(path / 'roster.json')
        registry = load_json(path / 'identity-registry.json')
        with tempfile.TemporaryDirectory() as tmp:
            build(spec, contract, tmp, roster=roster, identity_registry=registry)
            manifest = load_json(Path(tmp) / 'manifest.json')
            self.assertEqual(len(manifest['scenes']), 2)
            self.assertEqual(len(list(Path(tmp).rglob('*.svg'))), 11)
            for item in manifest['files']:
                self.assertEqual(digest((Path(tmp) / item['path']).read_bytes()), item['sha256'])
            self.assertIn('原地无位移', (Path(tmp) / 'scene-001/shot-001/movement.svg').read_text(encoding='utf8'))
            self.assertEqual(manifest['scenes'][1]['cast_ids'], [])
            self.assertEqual(manifest['scenes'][1]['identity_legend'], [])
            self.assertIn('空镜', (Path(tmp) / 'index.html').read_text(encoding='utf8'))
            self.assertRaises(ContractError, build, spec, contract, tmp, overwrite=True, roster=roster, identity_registry=registry)


if __name__ == '__main__':
    unittest.main()
