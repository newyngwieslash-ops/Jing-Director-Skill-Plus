"""Complete producer output and atomic safety regressions (offline)."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from director_core import ContractError,digest,load_json
from director_blocking import build
import director_blocking_output as output


def fixture():
    base=ROOT/'examples/blocking-demo'
    return tuple(load_json(base/name) for name in ('blocking-spec.json','director-contract.json','roster.json','identity-registry.json'))


class BlockingOutputTests(unittest.TestCase):
    def test_complete_pairs_coverage_and_hashes(self):
        spec,contract,roster,registry=fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'out';report=build(spec,contract,root,roster=roster,identity_registry=registry)
            manifest=load_json(root/'manifest.json')
            self.assertEqual(manifest['review_status'],'needs_manual_review')
            self.assertEqual(manifest['roster_sha256'],digest(roster))
            self.assertEqual(load_json(root/manifest['coverage']['path']),report['coverage'])
            for record in manifest['files']:
                self.assertEqual(digest((root/record['path']).read_bytes()),record['sha256'])
            self.assertEqual({str(p.relative_to(root)) for p in root.rglob('*') if p.is_file()}, {x['path'] for x in manifest['files']}|{'manifest.json'})
            for scene in manifest['scenes']:
                self.assertIn('第一镜', (root/scene['overview']['svg']['path']).read_text())
                for pair in [scene['overview']]+[shot[k] for shot in scene['shots'] for k in ('entry','exit','movement')]:
                    svg=ET.parse(root/pair['svg']['path']).getroot()
                    with Image.open(root/pair['png']['path']) as image:
                        self.assertEqual(image.size,(int(svg.attrib['width']),int(svg.attrib['height'])))
                        self.assertGreater(len(image.getcolors(image.width*image.height)),4)

    def test_nonempty_and_symlink_output_rejected_even_overwrite(self):
        spec,contract,roster,registry=fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'out';root.mkdir();(root/'precious.txt').write_text('unchanged')
            self.assertRaises(ContractError,build,spec,contract,root,True,roster,identity_registry=registry)
            self.assertEqual((root/'precious.txt').read_text(),'unchanged')
            link=Path(tmp)/'link';link.symlink_to(root,target_is_directory=True)
            self.assertRaises(ContractError,build,spec,contract,link,roster=roster,identity_registry=registry)

    def test_staging_failure_leaves_no_partial_outputs(self):
        spec,contract,roster,registry=fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'out';root.mkdir()
            with patch.object(output,'render_pair',side_effect=RuntimeError('failure')):
                self.assertRaises(RuntimeError,build,spec,contract,root,roster=roster,identity_registry=registry)
            self.assertEqual(list(root.iterdir()),[])
            self.assertEqual(list(Path(tmp).glob('.blocking-stage-*')),[])

    def test_resource_caps(self):
        spec,contract,roster,registry=fixture()
        for name in ('MAX_FILES','MAX_IMAGE_PIXELS','MAX_TOTAL_PIXELS'):
            with self.subTest(cap=name), tempfile.TemporaryDirectory() as tmp, patch.object(output,name,1):
                root=Path(tmp)/'out'
                self.assertRaises(ContractError,build,spec,contract,root,roster=roster,identity_registry=registry)
                self.assertFalse(root.exists())

    def test_shared_geometry_and_escaped_strings(self):
        spec,contract,roster,registry=fixture();scene=spec['scenes'][0];shot=scene['shots'][0]
        scene=copy.deepcopy(scene);scene['scene_id']='x<script>alert(1)</script>'
        identities={c['character_id']:c for c in registry['characters']}
        cast={c['id']:{**c,**identities[c['id']]} for c in spec['cast']}
        drawing=output.geometry(scene,shot,spec['locations'][0],cast,'entry')
        svg,png=output.render_pair(drawing)
        self.assertNotIn(b'<script>',svg);self.assertIn(b'&lt;script&gt;',svg)
        self.assertTrue(png.startswith(b'\x89PNG'))
        self.assertIn(b'polyline',svg);ET.fromstring(svg)

    def test_compact_plot_labels_keep_full_identity_in_legend(self):
        base=ROOT/'examples/hall-shot-09'
        spec=load_json(base/'blocking-spec.json');scene=spec['scenes'][0]
        shot=scene['shots'][0]
        registry=load_json(base/'identity-registry.json')
        identities={c['character_id']:c for c in registry['characters']}
        cast={c['id']:{**c,**identities[c['id']]} for c in spec['cast']}
        drawing=output.geometry(scene,shot,spec['locations'][0],cast,'movement')
        texts=[c[2] for c in drawing[2] if c[0]=='text']
        fixed_code=identities['employee_1']['short_code']
        self.assertIn(fixed_code,texts)
        self.assertEqual(texts.count(fixed_code),1)
        self.assertNotIn(f'{fixed_code} E=X',texts)
        # Identity and state stay associated, but on separate compact lines.
        index=next(i for i,c in enumerate(drawing[2]) if c[0]=='text' and c[2]==fixed_code)
        state=drawing[2][index+1]
        self.assertEqual(state[0],'text');self.assertEqual(state[2],'E=X')
        self.assertEqual(state[1][0],drawing[2][index][1][0])
        self.assertGreater(state[1][1],drawing[2][index][1][1])
        for cid in scene['cast_ids']:
            self.assertTrue(any(cid in t and ' = ' in t for t in texts))
        for i in range(1,len(shot['trajectories'])+1):
            self.assertIn(f'R{i}',texts)
            self.assertTrue(any(t.startswith(f'R{i} / ') for t in texts))
        self.assertNotIn('employee_1 EXIT',texts)


    def test_identity_labels_avoid_landmark_without_moving_actor(self):
        spec,contract,roster,registry=fixture();original=copy.deepcopy(spec)
        scene=spec['scenes'][0];shot=scene['shots'][0];location=spec['locations'][0]
        identities={c['character_id']:c for c in registry['characters']}
        cast={c['id']:{**c,**identities[c['id']]} for c in spec['cast']}
        drawing=output.geometry(scene,shot,location,cast,'entry')
        commands=drawing[2]
        actor=shot['characters'][0];code=cast[actor['id']]['short_code']
        index=next(i for i,c in enumerate(commands) if c[0]=='text' and c[2]==code)
        labels=commands[index:index+2]
        self.assertEqual(labels[1][2],'E')
        landmarks=[c[1] for c in commands if c[0]=='rect' and c[2] in ('#cbd5e1','#edf2f7')]
        self.assertTrue(landmarks)
        for label in labels:
            x,y=label[1];width=4+sum(10 if ord(c)<128 else 15 for c in label[2])
            box=(x-2,y-2,x+width+2,y+18)
            for obstacle in landmarks:
                self.assertFalse(box[0]<obstacle[2] and box[2]>obstacle[0] and box[1]<obstacle[3] and box[3]>obstacle[1])
        floor=next(c[1] for c in commands if c[0]=='rect' and c[2]=='#fbfcff')
        bounds=location['bounds'];state=actor['entry'];scale=(floor[2]-floor[0])/bounds['w']
        px=floor[0]+(state['x']-bounds['x'])*scale
        py=floor[1]+(bounds['y']+bounds['h']-state['y'])*scale
        self.assertTrue(any(c[0]=='symbol' and abs(c[1][0]-px)<1e-8 and abs(c[1][1]-py)<1e-8 for c in commands))
        self.assertEqual(spec,original)


if __name__=='__main__': unittest.main()
