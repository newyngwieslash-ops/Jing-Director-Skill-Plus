"""Offline board drafts; synthetic fixtures do not provide human approvals."""
import copy
import tempfile
import unittest
from pathlib import Path
from test_integrity_regressions import fixture, media, png
from director_core import ContractError, digest
from director_design_board import render_design_board, FONT


class DesignBoardTests(unittest.TestCase):
    def render(self,d,root,**kw):
        return render_design_board(d,root,Path(root)/'out',**kw)

    def test_canvas_determinism_missing_draft_and_source_immutable(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as t:
            d=fixture(); before=digest(d)
            m=self.render(d,t)
            self.assertEqual(before,digest(d)); self.assertEqual(m['visual_review'],'needs_manual_review')
            self.assertTrue(m['issues']); self.assertEqual(m['uncovered_items'],[])
            for p in m['pages']:
                with Image.open(Path(t)/'out'/(p['page_id']+'.png')) as im: self.assertEqual(im.size,(3840,2160))
            m2=render_design_board(d,t,Path(t)/'out2')
            self.assertEqual(m['output_sha256'],m2['output_sha256'])
            self.assertEqual(m['total_duration_sec'],sum(s['duration_sec'] for s in d['shots']))
            self.assertTrue(all(p['adds_duration_sec']==0 for p in m['pages']))

    def test_many_frames_and_long_text_lossless(self):
        with tempfile.TemporaryDirectory() as t:
            d=fixture(speech=True); s=d['shots'][0]
            q=s['dialogue'][0]; text=('中文对白。  保留空白\n\n'+('甲'*70)+'\n')*35
            q['text']=text
            src=d['source_shots'][0]; src['sound']=text+' Goodbye.'
            baseline=src['dialogue_baseline']['lines']; baseline[0].update(text=text,sound_span=[0,len(text)]); baseline[1]['sound_span']=[len(text)+1,len(text)+9]
            f=s['keyframes']; template=copy.deepcopy(f[1]); s['keyframes']=[f[0]]
            for i in range(18):
                k=copy.deepcopy(template); k.update(id='TEST-'+str(i),phase=template['phase'],time_sec=(i+1)*s['duration_sec']/20); s['keyframes'].append(k)
            s['keyframes'].append(f[-1])
            m=self.render(d,t,format='html')
            self.assertGreater(len(m['pages']),4)
            frame_items=[r for r in m['source_items'] if r['kind']=='image' and ':frame:' in r['id']]
            self.assertEqual(len(frame_items),20)
            item=next(r for r in m['source_items'] if r['id'].endswith(':dialogue:0:text'))
            pieces=[r for p in m['pages'] for r in p['items'] if r['id']==item['id']]
            self.assertEqual(''.join(item['text'][r['start']:r['end']] for r in pieces),text)

    def test_longshot_and_footer_source_bindings(self):
        from test_review_plan import single, explicit
        with tempfile.TemporaryDirectory() as t:
            d=single(18); before=digest(d)
            spec={'schema_version':'design-board-spec-1','contract_sha256':digest(d),'scenes':{},'footer':{'tone':{'source_pointer':'/project/style/zh'}}}
            m=self.render(d,t,format='html',review_plan=explicit((0,12),(12,18)),design_spec=spec)
            self.assertEqual(m['total_duration_sec'],18)
            self.assertEqual({p['window_id'] for p in m['pages']},{'RW-001','RW-002'})
            self.assertEqual(digest(d),before)
            self.assertTrue(any(i.get('source_pointer')=='/project/style/zh' and i['text']==d['project']['style']['zh'] for i in m['source_items']))
            spec['footer']['tone']['source_pointer']='/missing'
            with self.assertRaises(ContractError): self.render(d,t,format='html',design_spec=spec,overwrite=True)

    def test_mapped_assets_overflow_and_wide_image_contains(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as t:
            d=fixture(); root=Path(t); a=d['assets'][0]; a['path']='wide.png'
            Image.new('RGB',(2390,1000),(10,20,30)).save(root/'wide.png')
            spec={'schema_version':'design-board-spec-1','contract_sha256':digest(d),'scenes':{d['shots'][0]['scene_id']:{'character_asset_ids':[a['id']]*9,'plate_asset_id':a['id']}}}
            m=self.render(d,t,design_spec=spec,format='png')
            chars=[i for i in m['source_items'] if i['kind']=='image' and ':character:' in i['id']]
            self.assertEqual(len(chars),9)
            page=m['pages'][0]; r=next(r for r in page['items'] if r['id']==chars[0]['id'])
            with Image.open(root/'out'/(page['page_id']+'.png')) as im:
                # Whole wide image is letterboxed, not stretched or cropped.
                self.assertNotEqual(im.getpixel((r['x'],r['y'])),(10,20,30))
                self.assertEqual(im.getpixel((r['x']+r['width']//2,r['y']+r['height']//2)),(10,20,30))
            self.assertIn('wide.png',m['input_asset_sha256'])

    def test_large_raster_rejected_before_loading_or_publication(self):
        import struct, zlib
        with tempfile.TemporaryDirectory() as t:
            d=fixture(); a=d['assets'][0]; a['path']='huge.png'
            raw=png(); header=struct.pack('>IIBBBBB',10000,5000,8,2,0,0,0)
            raw=raw[:16]+header+struct.pack('>I',zlib.crc32(b'IHDR'+header)&0xffffffff)+raw[33:]
            (Path(t)/a['path']).write_bytes(raw)
            spec={'schema_version':'design-board-spec-1','contract_sha256':digest(d),'scenes':{d['shots'][0]['scene_id']:{'plate_asset_id':a['id']}}}
            with self.assertRaisesRegex(ContractError,'40 megapixels'):
                self.render(d,t,format='html',design_spec=spec)
            self.assertFalse((Path(t)/'out').exists())

    def test_text_budget_and_unknown_scene_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            d=fixture(); d['project']['style']['zh']='甲'*1000001
            spec={'schema_version':'design-board-spec-1','contract_sha256':digest(d),'scenes':{},'footer':{'tone':{'source_pointer':'/project/style/zh'}}}
            with self.assertRaisesRegex(ContractError,'1000000 text'):
                self.render(d,t,format='html',design_spec=spec)
            self.assertFalse((Path(t)/'out').exists())
            d=fixture();spec={'schema_version':'design-board-spec-1','contract_sha256':digest(d),'scenes':{'UNKNOWN':{}}}
            with self.assertRaisesRegex(ContractError,'unknown scene'):
                self.render(d,t,format='html',design_spec=spec)

    def test_stale_bindings_reported(self):
        with tempfile.TemporaryDirectory() as t:
            d=fixture(); media(d,Path(t)); k=d['shots'][0]['keyframes'][0]
            (Path(t)/k['image_path']).write_bytes(png()+b'changed')
            m=self.render(d,t,format='html')
            labels=[i['text'] for i in m['source_items'] if i['kind']=='text' and i['id'].endswith(':review')]
            self.assertIn('未核验/已失效',labels[0]); self.assertNotIn('字节绑定已核验',labels[0])

    def test_spec_mapping_and_svg_explicitly_unsupported(self):
        with tempfile.TemporaryDirectory() as t:
            d=fixture(); a=d['assets'][0]; a['path']='diagram.svg'
            (Path(t)/'diagram.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>')
            spec={'schema_version':'design-board-spec-1','contract_sha256':digest(d),'scenes':{d['shots'][0]['scene_id']:{'blocking_asset_ids':[a['id']]}}}
            m=self.render(d,t,design_spec=spec,format='html')
            self.assertTrue(any(i['reason']=='unsupported_svg_no_raster_preview' for i in m['issues']))
            self.assertNotIn('<script>',(Path(t)/'out/index.html').read_text())
            spec['contract_sha256']='0'*64
            with self.assertRaises(ContractError): self.render(d,t,design_spec=spec,overwrite=True)

    def test_overwrite_inputs_paths_and_symlinks(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t); d=fixture()
            self.render(d,t,format='html')
            with self.assertRaises(ContractError): self.render(d,t,format='html')
            old=(root/'out/manifest.json').read_bytes()
            with self.assertRaises(ContractError): self.render(d,t,format='html',overwrite=True)
            self.assertEqual(old,(root/'out/manifest.json').read_bytes())
            with self.assertRaises(ContractError): self.render(d,t,format='html',overwrite=True,protected_paths=[root/'out/index.html'])
            (root/'out/index.html').unlink(); (root/'out/index.html').symlink_to(root/'untouched')
            with self.assertRaises(ContractError): self.render(d,t,format='html',overwrite=True)
            for path in ('../outside.png','https://example.test/a.png'):
                d=fixture(); d['assets'][0]['path']=path
                with self.assertRaises(ContractError): self.render(d,t,format='html',overwrite=True)


if __name__=='__main__': unittest.main()
