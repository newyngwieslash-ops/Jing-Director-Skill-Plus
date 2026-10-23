"""Project identities, fail-closed bindings and non-color redundancy (offline)."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from director_core import ContractError,digest,load_json
from director_identity import validate_identity,registry_binding,identity_legend
from director_blocking import validate_blocking,build
from director_blocking_output import geometry,render_pair
from director_design_board import render_design_board
from test_blocking_coverage import fixture


def rebind(spec,registry):
    spec['identity_binding']=registry_binding(registry)


def enriched(spec,registry):
    index={p['character_id']:p for p in registry['characters']}
    return {p['id']:{**p,**index[p['id']]} for p in spec['cast']}


class IdentityTests(unittest.TestCase):
    def test_required_registry_and_binding(self):
        spec,doc,roster,registry=fixture()
        for identity in (None,[],"registry"):
            result=validate_blocking(spec,doc,roster,identity_registry=identity)
            self.assertFalse(result['ok'])
            self.assertIn('IDENTITY_REQUIRED',[e['code'] for e in result['errors']])
        spec.pop('identity_binding')
        self.assertEqual(validate_identity(spec,registry)['status'],'blocked')

    def test_version_and_hash_binding_both_checked(self):
        for key,value in [('project_id','different'),('revision',2),('registry_sha256','0'*64)]:
            spec,doc,roster,registry=fixture(); spec['identity_binding'][key]=value
            result=validate_blocking(spec,doc,roster,identity_registry=registry)
            self.assertFalse(result['ok']);self.assertEqual(result['coverage']['identity_status'],'blocked')

    def test_malformed_registry_fails_closed(self):
        mutations=[lambda r:r.update(revision=True),lambda r:r.update(revision=0),
          lambda r:r.update(revision=2**40),lambda r:r.update(project_id=[]),
          lambda r:r.update(schema_version='approved'),lambda r:r.update(manual_approval=True),
          lambda r:r.update(characters=None),lambda r:r['characters'].append(None),
          lambda r:r['characters'][0].update(character_id=[]),
          lambda r:r['characters'][0].update(short_code={}),
          lambda r:r['characters'][0].update(color=[]),
          lambda r:r['characters'][0].update(marker_shape=[]),
          lambda r:r['characters'][0].update(path_style={}),
          lambda r:r['characters'][0].update(approval=True),
          lambda r:r.update(revision=float('nan'))]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                spec,doc,roster,registry=fixture();mutate(registry)
                result=validate_blocking(spec,doc,roster,identity_registry=registry)
                self.assertFalse(result['ok']);self.assertEqual(result['review_status'],'needs_manual_review')

    def test_duplicate_ids_codes_and_invalid_codes_block(self):
        for field,value in [('character_id','A'),('short_code','C001'),('short_code','c001'),
                            ('short_code','TOOLONGCODE'),('color','#fff'),('marker_shape','star'),('path_style','none')]:
            spec,_,_,registry=fixture()
            # Use actual first code, not a palette assignment assumption.
            if field=='short_code' and value=='C001':value=registry['characters'][0]['short_code']
            registry['characters'][1][field]=value;rebind(spec,registry)
            self.assertEqual(validate_identity(spec,registry)['status'],'blocked')

    def test_missing_role_and_color_drift_block(self):
        spec,doc,roster,registry=fixture(); registry['characters'].pop();rebind(spec,registry)
        self.assertIn('IDENTITY_CHARACTER_MISSING',[e['code'] for e in validate_identity(spec,registry)['errors']])
        spec,doc,roster,registry=fixture();spec['cast'][0]['color']='#123456'
        self.assertIn('IDENTITY_COLOR_MISMATCH',[e['code'] for e in validate_identity(spec,registry)['errors']])

    def test_static_marker_collision_blocks_despite_different_routes(self):
        spec,doc,roster,registry=fixture();a,b=registry['characters']
        b.update(color=a['color'],marker_shape=a['marker_shape'],path_style='dotted' if a['path_style']!='dotted' else 'dashed')
        spec['cast'][1]['color']=a['color'];rebind(spec,registry)
        result=validate_blocking(spec,doc,roster,identity_registry=registry)
        self.assertFalse(result['ok'])
        self.assertIn('IDENTITY_VISUAL_COLLISION',[e['code'] for e in result['errors']])

    def test_shared_color_with_distinct_shapes_needs_review(self):
        spec,_,_,registry=fixture();a,b=registry['characters'];b['color']=a['color']
        b['marker_shape']='diamond' if a['marker_shape']!='diamond' else 'square'
        spec['cast'][1]['color']=a['color'];rebind(spec,registry)
        result=validate_identity(spec,registry)
        self.assertEqual(result['status'],'complete')
        self.assertIn('IDENTITY_SHARED_COLOR',[w['code'] for w in result['warnings']])

    def test_contrast_and_near_color_heuristics_are_warnings_not_approval(self):
        spec,_,_,registry=fixture()
        for person,color in zip(registry['characters'],['#ffffff','#fefefe']):
            person['color']=color
            next(p for p in spec['cast'] if p['id']==person['character_id'])['color']=color
        rebind(spec,registry);result=validate_identity(spec,registry)
        codes={w['code'] for w in result['warnings']}
        self.assertTrue({'IDENTITY_LOW_CONTRAST','IDENTITY_NEAR_COLOR'}<=codes)
        self.assertNotIn('approved',result['status'])

    def test_registry_additions_do_not_reassign_existing_codes_or_colors(self):
        spec,doc,roster,registry=fixture();before=copy.deepcopy(registry['characters'])
        registry['revision']+=1
        registry['characters'].insert(0,dict(character_id='UNSEEN',short_code='Z999',color='#555555',marker_shape='triangle',path_style='dashed'))
        rebind(spec,registry)
        result=validate_blocking(spec,doc,roster,identity_registry=registry)
        self.assertTrue(result['ok'],result['errors'])
        self.assertEqual(registry['characters'][1:],before)
        self.assertEqual([p['short_code'] for p in result['identity']['legend']],[p['short_code'] for p in before])

    def test_order_and_other_scene_do_not_change_visual_identity(self):
        spec,_,_,registry=fixture();cast=enriched(spec,registry);scene=spec['scenes'][0]
        expected={p['id']:cast[p['id']]['short_code'] for p in spec['cast']}
        for reverse in (False,True):
            changed=copy.deepcopy(scene);changed['scene_id']='another-scene'
            if reverse: changed['cast_ids'].reverse();spec['cast'].reverse();registry['characters'].reverse()
            drawing=geometry(changed,changed['shots'][0],spec['locations'][0],cast,'entry')
            text=[c[2] for c in drawing[2] if c[0]=='text']
            for cid,code in expected.items():self.assertTrue(any(f'{code} = {cid}:' in line for line in text))

    def test_all_small_text_dark_and_pair_uses_same_identity_symbols(self):
        spec,_,_,registry=fixture();scene=spec['scenes'][0];cast=enriched(spec,registry)
        for phase in ('overview','entry','exit','movement'):
            drawing=geometry(scene,scene['shots'][0],spec['locations'][0],cast,phase,spec['identity_binding'])
            self.assertTrue(all(c[3]=='#172033' for c in drawing[2] if c[0]=='text'))
            self.assertTrue(any(c[0]=='symbol' for c in drawing[2]))
            svg,png=render_pair(drawing);root=ET.fromstring(svg)
            self.assertTrue(png.startswith(b'\x89PNG'))
            for person in registry['characters']:
                self.assertIn(person['color'].encode(),svg)
                self.assertIn(person['short_code'],''.join(root.itertext()))

    def test_resource_caps(self):
        spec,_,_,registry=fixture();registry['characters']*=5001
        result=validate_identity(spec,registry)
        self.assertIn('IDENTITY_CHARACTERS',[e['code'] for e in result['errors']])
        spec,_,_,registry=fixture();spec['scenes'][0]['cast_ids']=['A']*501
        result=validate_identity(spec,registry)
        self.assertIn('IDENTITY_SCENE_LIMIT',[e['code'] for e in result['errors']])

    def test_collision_is_scene_local_not_global(self):
        spec,_,_,registry=fixture();a,b=registry['characters'];b.update(color=a['color'],marker_shape=a['marker_shape'])
        spec['cast'][1]['color']=a['color'];spec['scenes'][0]['cast_ids']=['A'];spec['scenes'][1]['cast_ids']=['B']
        rebind(spec,registry)
        self.assertEqual(validate_identity(spec,registry)['status'],'complete')

    def test_build_missing_identity_publishes_nothing(self):
        spec,doc,roster,_=fixture()
        with tempfile.TemporaryDirectory() as t:
            target=Path(t)/'out'
            with self.assertRaises(ContractError):build(spec,doc,target,roster=roster)
            self.assertFalse(target.exists())


class IdentityBoardTests(unittest.TestCase):
    def fixture(self,root):
        spec,doc,roster,registry=fixture()
        build(spec,doc,root/'bundle',roster=roster,identity_registry=registry)
        current=root/'identity-registry.json';current.write_text(json.dumps(registry))
        design={'schema_version':'design-board-spec-1','contract_sha256':digest(doc),'scenes':{},
                'blocking_bundle':{'manifest_path':'bundle/manifest.json','manifest_sha256':digest((root/'bundle/manifest.json').read_bytes()),
                'identity_registry_path':'identity-registry.json','identity_registry_sha256':digest(current.read_bytes())}}
        return doc,design,registry

    def test_current_project_registry_is_bound_as_input(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);doc,design,registry=self.fixture(root)
            result=render_design_board(doc,root,root/'board',design_spec=design,format='html',require_blocking=True)
            self.assertIn('identity-registry.json',result['input_asset_sha256'])
            self.assertIn('bundle/identity-registry.json',result['input_asset_sha256'])
            self.assertEqual(result['visual_review'],'needs_manual_review')

    def test_missing_changed_rehashed_or_self_snapshot_registry_blocks(self):
        for mutation in ('missing_binding','missing_file','changed','rehashed','self_snapshot'):
            with self.subTest(mutation=mutation),tempfile.TemporaryDirectory() as t:
                root=Path(t);doc,design,registry=self.fixture(root);binding=design['blocking_bundle'];current=root/'identity-registry.json'
                if mutation=='missing_binding':binding.pop('identity_registry_path')
                elif mutation=='missing_file':current.unlink()
                elif mutation=='self_snapshot':
                    binding['identity_registry_path']='bundle/identity-registry.json'
                    binding['identity_registry_sha256']=digest((root/'bundle/identity-registry.json').read_bytes())
                else:
                    registry['revision']+=1;current.write_text(json.dumps(registry))
                    if mutation=='rehashed':binding['identity_registry_sha256']=digest(current.read_bytes())
                with self.assertRaises(ContractError):render_design_board(doc,root,root/'board',design_spec=design,format='html',require_blocking=True)
                self.assertFalse((root/'board').exists())

    def test_rehashed_legend_mismatch_blocks(self):
        for level in ('global','scene'):
            with self.subTest(level=level),tempfile.TemporaryDirectory() as t:
                root=Path(t);doc,design,_=self.fixture(root);path=root/'bundle/manifest.json';manifest=load_json(path)
                target=manifest if level=='global' else manifest['scenes'][0]
                target['identity_legend'][0]['short_code']='FALSE'
                path.write_text(json.dumps(manifest));design['blocking_bundle']['manifest_sha256']=digest(path.read_bytes())
                with self.assertRaisesRegex(ContractError,'identity legend'):
                    render_design_board(doc,root,root/'board',design_spec=design,format='html',require_blocking=True)

    def test_rehashed_identity_snapshot_mutation_blocks(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);doc,design,registry=self.fixture(root);path=root/'bundle/identity-registry.json'
            registry['characters'][0]['short_code']='X999';path.write_text(json.dumps(registry))
            mpath=root/'bundle/manifest.json';manifest=load_json(mpath)
            manifest['identity_registry']['sha256']=digest(path.read_bytes());manifest['identity_registry_sha256']=digest(registry)
            for ref in manifest['files']:
                if ref['path']=='identity-registry.json':ref['sha256']=digest(path.read_bytes())
            mpath.write_text(json.dumps(manifest));design['blocking_bundle']['manifest_sha256']=digest(mpath.read_bytes())
            with self.assertRaisesRegex(ContractError,'snapshot differs'):
                render_design_board(doc,root,root/'board',design_spec=design,format='html',require_blocking=True)

if __name__=='__main__':unittest.main()
