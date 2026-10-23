"""Complete blocking bundles are separately bound and fail closed before publication."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from director_core import ContractError, digest
from director_blocking import build
from director_design_board import render_design_board
from test_blocking_coverage import fixture


class BlockingBoardTests(unittest.TestCase):
    def setup_bundle(self, root):
        sidecar, contract, roster, identity = fixture()
        build(sidecar, contract, root/'bundle', roster=roster, identity_registry=identity)
        identity_path = root/'identity-registry.json'
        identity_path.write_text(json.dumps(identity))
        manifest = root/'bundle/manifest.json'
        spec = {'schema_version':'design-board-spec-1','contract_sha256':digest(contract),
                'scenes':{},'blocking_bundle':{'manifest_path':'bundle/manifest.json',
                'manifest_sha256':digest(manifest.read_bytes()),
                'identity_registry_path':'identity-registry.json',
                'identity_registry_sha256':digest(identity_path.read_bytes())}}
        return contract, spec

    def rewrite_manifest(self, root, spec, mutate):
        path = root/'bundle/manifest.json'
        value = json.loads(path.read_text()); mutate(value)
        path.write_text(json.dumps(value, ensure_ascii=False))
        spec['blocking_bundle']['manifest_sha256'] = digest(path.read_bytes())

    def test_bound_bundle_complete_middle_column_and_immutable_contract(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t); d,s=self.setup_bundle(root); before=digest(d)
            source_hashes={p:digest(p.read_bytes()) for p in (root/'bundle').rglob('*') if p.is_file()}
            m=render_design_board(d,root,root/'board',design_spec=s,require_blocking=True,format='html')
            self.assertEqual(before,digest(d)); self.assertEqual(m['spatial_status'],'spatial_complete_schematic')
            self.assertEqual(source_hashes,{p:digest(p.read_bytes()) for p in source_hashes})
            self.assertEqual(m['visual_review'],'needs_manual_review')
            images=[i for i in m['source_items'] if i.get('blocking_phase')]
            self.assertEqual({i['source_shot_id'] for i in images},{s['shot_id'] for s in d['shots']})
            self.assertTrue(all(i['context_only'] and i['adds_duration_sec']==0 for i in images))
            self.assertTrue(all(400 < i['display_height'] <= 1500 for i in images))
            from PIL import Image
            import math
            for item in images:
                with Image.open(root/item['path']) as raster:
                    self.assertEqual(item['display_height'],min(1500,math.ceil(raster.height*1062/raster.width)))
            for shot in d['shots']:
                self.assertEqual({i['blocking_phase'] for i in images if i['source_shot_id']==shot['shot_id']},{'entry','exit','movement'})
            self.assertTrue(all(1008<=i['x']<2102 for p in m['pages'] for i in p['items'] if ':blocking:' in i['id']))
            self.assertEqual(m['total_duration_sec'],sum(s['duration_sec'] for s in d['shots']))
            self.assertTrue(all(p['adds_duration_sec']==0 for p in m['pages']))
            for item in m['source_items']:
                if item['kind']=='image':
                    self.assertEqual(sum(i['id']==item['id'] for p in m['pages'] for i in p['items']),1)
            self.assertIn('bundle/roster.json',m['input_asset_sha256'])

    def test_repeated_shot_diagrams_are_context_only_in_each_window(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);d,s=self.setup_bundle(root)
            windows=[]
            for shot in d['shots']:
                mid=shot['duration_sec']/2
                for a,b in [(0,mid),(mid,shot['duration_sec'])]:
                    windows.append({'segments':[{'source_shot_id':shot['shot_id'],
                        'review_start_sec':a,'review_end_sec':b}]})
            m=render_design_board(d,root,root/'board',design_spec=s,require_blocking=True,
                                  review_plan=windows,format='html')
            images=[i for i in m['source_items'] if i.get('blocking_phase')]
            self.assertEqual(len(images),len(d['shots'])*6)
            self.assertTrue(all(i['context_only'] and i['adds_duration_sec']==0 for i in images))
            self.assertEqual(m['total_duration_sec'],sum(s['duration_sec'] for s in d['shots']))

    def test_strict_missing_bundle_and_legacy_incomplete(self):
        with tempfile.TemporaryDirectory() as t:
            _,d,_,_=fixture(); root=Path(t)
            with self.assertRaisesRegex(ContractError,'requires blocking_bundle'):
                render_design_board(d,root,root/'strict',require_blocking=True,format='html')
            self.assertFalse((root/'strict').exists())
            m=render_design_board(d,root,root/'draft',format='html')
            self.assertEqual(m['spatial_status'],'spatial_incomplete')

    def test_manifest_hash_missing_scene_shot_and_diagrams_block(self):
        mutations=[lambda m:m['scenes'].pop(), lambda m:m['scenes'][0]['shots'].pop(),
                   lambda m:m['scenes'][0].pop('overview'),
                   lambda m:m['scenes'][0]['shots'][0]['entry'].pop('png'),
                   lambda m:m['scenes'][0]['shots'][0]['exit']['svg'].update(sha256='0'*64),
                   lambda m:m.update(roster_sha256='0'*64),
                   lambda m:m['scenes'][0]['overview']['png'].update(path='../../escape.png')]
        for mutate in mutations:
            with self.subTest(mutate=mutate),tempfile.TemporaryDirectory() as t:
                root=Path(t);d,s=self.setup_bundle(root); self.rewrite_manifest(root,s,mutate)
                with self.assertRaises(ContractError):
                    render_design_board(d,root,root/'board',design_spec=s,require_blocking=True,format='html')
                self.assertFalse((root/'board').exists())

    def test_tampered_png_roster_coverage_and_manifest_block(self):
        for which in ('png','roster','coverage','manifest'):
            with self.subTest(which=which),tempfile.TemporaryDirectory() as t:
                root=Path(t);d,s=self.setup_bundle(root)
                m=json.loads((root/'bundle/manifest.json').read_text())
                rel=(m['scenes'][-1]['shots'][-1]['movement']['png']['path'] if which=='png'
                     else 'manifest.json' if which=='manifest' else m[which]['path'])
                path=root/'bundle'/rel;path.write_bytes(path.read_bytes()+b' ')
                with self.assertRaises(ContractError):
                    render_design_board(d,root,root/'board',design_spec=s,require_blocking=True,format='html')
                self.assertFalse((root/'board').exists())

    def test_rehashed_stale_coverage_still_blocks(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);d,s=self.setup_bundle(root)
            path=root/'bundle/coverage.json';v=json.loads(path.read_text());v['scenes'].pop()
            path.write_text(json.dumps(v))
            self.rewrite_manifest(root,s,lambda m:m['coverage'].update(sha256=digest(path.read_bytes())))
            with self.assertRaisesRegex(ContractError,'Stale blocking coverage'):
                render_design_board(d,root,root/'board',design_spec=s,require_blocking=True,format='html')
            self.assertFalse((root/'board').exists())


    def test_inventory_missing_files_and_stale_metadata_block(self):
        mutations=[lambda m:m['files'].pop(),
                   lambda m:m['files'].append(dict(m['files'][0])),
                   lambda m:m['scenes'][0].update(cast_ids=[]),
                   lambda m:m['scenes'][0].update(location_id='stale'),
                   lambda m:m.update(review_status='approved'),
                   lambda m:m['files'][0].update(sha256='0'*64)]
        for mutate in mutations:
            with self.subTest(mutate=mutate), tempfile.TemporaryDirectory() as t:
                root=Path(t);d,s=self.setup_bundle(root);self.rewrite_manifest(root,s,mutate)
                with self.assertRaises(ContractError):
                    render_design_board(d,root,root/'board',design_spec=s,require_blocking=True,format='html')
                self.assertFalse((root/'board').exists())
        for name in ('index.html','validation.json','scene-002/shot-001/movement.png'):
            with self.subTest(missing=name), tempfile.TemporaryDirectory() as t:
                root=Path(t);d,s=self.setup_bundle(root);(root/'bundle'/name).unlink()
                with self.assertRaises(ContractError):
                    render_design_board(d,root,root/'board',design_spec=s,require_blocking=True,format='html')
                self.assertFalse((root/'board').exists())


    def test_rehashed_stale_roster_semantics_block(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);d,s=self.setup_bundle(root)
            path=root/'bundle/roster.json';v=json.loads(path.read_text())
            v['contract_sha256']='0'*64;path.write_text(json.dumps(v))
            def mutate(m):
                m['roster']['sha256']=digest(path.read_bytes());m['roster_sha256']=digest(v)
                for ref in m['files']:
                    if ref['path']=='roster.json':ref['sha256']=digest(path.read_bytes())
            self.rewrite_manifest(root,s,mutate)
            with self.assertRaisesRegex(ContractError,'Blocking coverage validation failed'):
                render_design_board(d,root,root/'board',design_spec=s,require_blocking=True,format='html')
            self.assertFalse((root/'board').exists())


if __name__=='__main__': unittest.main()
