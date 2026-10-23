"""Strict subject classification, roster expansion and fail-closed coverage."""
import copy
import sys
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from director_core import digest, load_json
from director_blocking import validate_blocking


def fixture():
    contract = load_json(ROOT / 'examples/blocking-demo/director-contract.json')
    spec = load_json(ROOT / 'examples/blocking-demo/blocking-spec.json')
    subjects = sorted({x for s in contract['shots'] for x in s['subjects']})
    entries = []
    for sid in subjects:
        sh = next(s for s in contract['shots'] if sid in s['subjects'])
        src = next(s for s in contract['source_shots'] if s['source_shot_no'] == sh['source_shot_no'])
        entries.append(dict(subject_id=sid, kind='individual', member_ids=[sid], expected_count=1,
                            evidence=[dict(source_shot_no=src['source_shot_no'], field='action', quote=src['action'])]))
    roster = dict(schema_version='1.0', contract_sha256=digest(contract), subjects=entries,
                  scenes=[dict(scene_id=s['scene_id'], cast_ids=s['cast_ids'][:], expected_count=len(s['cast_ids'])) for s in spec['scenes']])
    identity = load_json(ROOT / 'examples/blocking-demo/identity-registry.json')
    return spec, contract, roster, identity


class CoverageTests(unittest.TestCase):
    def test_complete_including_explicit_empty_scene(self):
        s, c, r, identity = fixture(); report = validate_blocking(s, c, r, identity_registry=identity)
        self.assertTrue(report['ok'], report['errors'])
        self.assertEqual(report['coverage']['status'], 'complete')
        self.assertEqual(report['coverage']['scenes'][1]['expected_count'], 0)
        self.assertEqual(report['review_status'], 'needs_manual_review')

    def test_legacy_not_completeness_green(self):
        s, c, _, identity = fixture(); report = validate_blocking(s, c, identity_registry=identity)
        self.assertFalse(report['ok'])
        self.assertIn('ROSTER_REQUIRED', [e['code'] for e in report['errors']])
        self.assertEqual(report['coverage']['unclassified_subject_ids'], ['A', 'B'])
        self.assertIsNone(report['coverage']['scenes'][0]['expected_count'])
        self.assertEqual(report['coverage']['status'], 'blocked')

    def test_missing_scene_shot_or_character_blocks(self):
        for mutate in (lambda s: s['scenes'].pop(), lambda s: s['scenes'][0]['shots'].pop(),
                       lambda s: s['scenes'][0]['shots'][0]['characters'].pop(),
                       lambda s: s['scenes'][0]['shots'][0]['characters'][0].pop('exit')):
            s,c,r, identity = fixture(); mutate(s); report=validate_blocking(s,c,r, identity_registry=identity)
            self.assertFalse(report['ok']); self.assertEqual(report['coverage']['status'], 'blocked')

    def test_delete_person_from_all_spec_lists_still_blocks(self):
        s,c,r, identity = fixture(); s['cast']=s['cast'][1:]
        for scene in s['scenes']:
            scene['cast_ids']=[x for x in scene['cast_ids'] if x != 'A']
            for shot in scene['shots']:
                shot['characters']=[x for x in shot['characters'] if x['id'] != 'A']
                shot['trajectories']=[x for x in shot['trajectories'] if x['who'] != 'A']
        self.assertFalse(validate_blocking(s,c,r, identity_registry=identity)['ok'])

    def test_unclassified_and_wrong_group_count_block(self):
        for mutate in (lambda r: r['subjects'].pop(), lambda r: r['subjects'][0].update(kind='group', expected_count=4),
                       lambda r: r['subjects'][0].update(kind='non_character'),
                       lambda r: r['subjects'][0].update(evidence=[]),
                       lambda r: r.update(contract_sha256='stale'),
                       lambda r: r['scenes'][1].pop('expected_count')):
            s,c,r, identity = fixture(); mutate(r); self.assertFalse(validate_blocking(s,c,r, identity_registry=identity)['ok'])

    def test_group_expands_to_individuals(self):
        s,c,r, identity = fixture()
        for shot in c['shots']:
            if shot['subjects']: shot['subjects']=['pair']
        r['subjects']=[dict(subject_id='pair',kind='group',member_ids=['A','B'],expected_count=2,evidence=r['subjects'][0]['evidence'])]
        s['contract_sha256']=r['contract_sha256']=digest(c)
        report=validate_blocking(s,c,r, identity_registry=identity); self.assertTrue(report['ok'],report['errors'])
        self.assertEqual(report['coverage']['scenes'][0]['expected_cast_ids'], ['A','B'])
        r['subjects'][0]['member_ids'].pop()
        self.assertFalse(validate_blocking(s,c,r, identity_registry=identity)['ok'])

    def test_evidenced_prop_is_not_inferred_as_person(self):
        s,c,r, identity = fixture(); c['shots'][-1]['subjects']=['empty_room']
        src=next(x for x in c['source_shots'] if x['source_shot_no']==c['shots'][-1]['source_shot_no'])
        r['subjects'].append(dict(subject_id='empty_room',kind='non_character',member_ids=[],expected_count=0,
             evidence=[dict(source_shot_no=src['source_shot_no'],field='action',quote=src['action'])]))
        s['contract_sha256']=r['contract_sha256']=digest(c)
        self.assertTrue(validate_blocking(s,c,r, identity_registry=identity)['ok'])
        r['subjects'][-1]['evidence'][0]['quote']='fabricated'
        self.assertFalse(validate_blocking(s,c,r, identity_registry=identity)['ok'])

    def test_malformed_inputs_fail_closed(self):
        for mutate in (lambda s,c,r: r['subjects'][0].update(subject_id=[]),
                       lambda s,c,r: r['subjects'][0].update(member_ids=[{}]),
                       lambda s,c,r: s['scenes'][0].update(cast_ids=[{}]),
                       lambda s,c,r: r['subjects'][0]['evidence'][0].update(source_shot_no=[])):
            s,c,r, identity = fixture(); mutate(s,c,r)
            report=validate_blocking(s,c,r, identity_registry=identity)
            self.assertFalse(report['ok'])
            self.assertEqual(report['coverage']['status'], 'blocked')

    def test_roster_schema_unknown_fields_fail_closed(self):
        for level in ('root', 'subject', 'evidence', 'scene'):
            with self.subTest(level=level):
                s, c, r, identity = fixture()
                target = {'root': r, 'subject': r['subjects'][0],
                          'evidence': r['subjects'][0]['evidence'][0],
                          'scene': r['scenes'][0]}[level]
                target['manual_approval'] = 'approved'
                report = validate_blocking(s, c, r, identity_registry=identity)
                self.assertFalse(report['ok'])
                self.assertIn('ROSTER_FIELDS', [e['code'] for e in report['errors']])
                self.assertEqual(report['review_status'], 'needs_manual_review')

    def test_invalid_kind_cardinality_has_no_authoritative_count(self):
        for kind in ('group', 'non_character'):
            s, c, r, identity = fixture()
            r['subjects'][0]['kind'] = kind
            report = validate_blocking(s, c, r, identity_registry=identity)
            self.assertFalse(report['ok'])
            row = report['coverage']['scenes'][0]
            self.assertIsNone(row['expected_count'])
            self.assertIn(r['subjects'][0]['subject_id'], row['unresolved_subject_ids'])

    def test_hall_every_individual_is_independently_required(self):
        path = ROOT / 'examples/hall-shot-09'
        identity = load_json(path / 'identity-registry.json')
        spec = load_json(path / 'blocking-spec.json')
        contract = load_json(path / 'director-contract.json')
        roster = load_json(path / 'roster.json')
        report = validate_blocking(spec, contract, roster, identity_registry=identity)
        self.assertTrue(report['ok'], report['errors'])
        row = report['coverage']['scenes'][0]
        self.assertEqual(row['expected_count'], 10)
        self.assertEqual(len(row['shots'][0]['frame_states']), 10)
        self.assertEqual(len(row['shots'][0]['path_coverage']), 10)
        for missing in row['expected_cast_ids']:
            with self.subTest(missing=missing):
                s = copy.deepcopy(spec)
                s['cast'] = [c for c in s['cast'] if c['id'] != missing]
                for scene in s['scenes']:
                    scene['cast_ids'].remove(missing)
                    for shot in scene['shots']:
                        shot['characters'] = [c for c in shot['characters'] if c['id'] != missing]
                        shot['trajectories'] = [r for r in shot['trajectories'] if r['who'] != missing]
                report = validate_blocking(s, contract, roster, identity_registry=identity)
                self.assertFalse(report['ok'])
                self.assertEqual(report['coverage']['status'], 'blocked')
                row = report['coverage']['scenes'][0]['shots'][0]
                self.assertEqual(row['missing_cast_ids'], [missing])
                self.assertEqual(row['status'], 'blocked')

    def test_hall_group_counts_and_unique_members_are_blocking(self):
        path = ROOT / 'examples/hall-shot-09'
        identity = load_json(path / 'identity-registry.json')
        s = load_json(path / 'blocking-spec.json')
        c = load_json(path / 'director-contract.json')
        original = load_json(path / 'roster.json')
        for group in ('staff_group_4', 'tourist_pair'):
            for mutation in ('count', 'member', 'duplicate', 'bool_count'):
                with self.subTest(group=group, mutation=mutation):
                    r = copy.deepcopy(original)
                    subject = next(x for x in r['subjects'] if x['subject_id'] == group)
                    if mutation == 'count': subject['expected_count'] -= 1
                    elif mutation == 'member': subject['member_ids'].pop()
                    elif mutation == 'duplicate': subject['member_ids'][-1] = subject['member_ids'][0]
                    else: subject['expected_count'] = True
                    self.assertFalse(validate_blocking(s, c, r, identity_registry=identity)['ok'])

    def test_duplicate_scene_shot_and_cast_are_blocking(self):
        for level in ('scene', 'shot', 'cast', 'roster_subject', 'roster_scene'):
            s, c, r, identity = fixture()
            target = {'scene': s['scenes'], 'shot': s['scenes'][0]['shots'],
                      'cast': s['scenes'][0]['shots'][0]['characters'],
                      'roster_subject': r['subjects'], 'roster_scene': r['scenes']}[level]
            target.append(copy.deepcopy(target[0]))
            report = validate_blocking(s, c, r, identity_registry=identity)
            self.assertFalse(report['ok'], level)
            self.assertTrue(all(row['status'] == 'blocked' for scene in report['coverage']['scenes'] for row in scene['shots']))

    def test_exact_but_unrelated_evidence_is_blocked(self):
        s, c, r, identity = fixture()
        unrelated = c['source_shots'][-1]
        r['subjects'][0]['evidence'] = [dict(source_shot_no=unrelated['source_shot_no'],
                                            field='action', quote=unrelated['action'])]
        report = validate_blocking(s, c, r, identity_registry=identity)
        self.assertFalse(report['ok'])
        self.assertIn('ROSTER_EVIDENCE', [e['code'] for e in report['errors']])

    def test_offscreen_still_needs_both_states(self):
        s,c,r, identity = fixture(); char=s['scenes'][0]['shots'][0]['characters'][0]
        char['entry']['visibility']=char['exit']['visibility']='offscreen'
        self.assertTrue(validate_blocking(s,c,r, identity_registry=identity)['ok'])
        char.pop('entry'); self.assertFalse(validate_blocking(s,c,r, identity_registry=identity)['ok'])

if __name__ == '__main__': unittest.main()
