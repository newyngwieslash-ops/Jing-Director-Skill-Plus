"""Offline fixed-canvas design-board drafts. No image generation or automatic approval.

Spec: {schema_version: design-board-spec-1, contract_sha256, scenes: {
scene_id: {character_asset_ids: [], plate_asset_id: str, blocking_asset_ids: []}}}.
Contract references and separately hash-bound complete blocking bundles are displayed.
SVG is deliberately unsupported in v1 (including HTML); no converter is invoked.
"""
from __future__ import annotations
import base64
import html
import io
import json
import math
from pathlib import Path
from director_core import ContractError, digest, project_path
from director_render import checked, local_image, review_label

WIDTH, HEIGHT = 3840, 2160
VERSION = 'design-board-1.2'
FONT = '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'
COLS = [(64, 912), (1008, 1094), (2134, 1642)]
TOP, BOTTOM, LINE = 270, 1990, 48


def _blocking_bundle(doc, root, binding, required=False):
    """Validate the whole separately-bound bundle, never just visible windows."""
    if binding is None:
        if required: raise ContractError('Full spatial design board requires blocking_bundle')
        return None
    if not isinstance(binding, dict) or set(binding) != {'manifest_path', 'manifest_sha256', 'identity_registry_path', 'identity_registry_sha256'}:
        raise ContractError('blocking_bundle requires manifest_path, manifest_sha256, identity_registry_path and identity_registry_sha256')
    from director_core import load_json
    from director_blocking import validate_blocking
    try:
        from PIL import Image
    except ImportError as exc:
        raise ContractError('Pillow unavailable; no installation attempted') from exc
    inputs, protected = {}, set()
    manifest_path = project_path(root, binding['manifest_path'])
    def verified(path, expected):
        if not isinstance(expected, str) or len(expected) != 64:
            raise ContractError('Blocking bundle requires SHA256 for every input')
        if not path.is_file(): raise ContractError('Missing blocking bundle input: '+str(path))
        if path.stat().st_size > 32*1024*1024: raise ContractError('Blocking input exceeds 32 MiB')
        raw = path.read_bytes()
        if digest(raw) != expected: raise ContractError('Stale blocking bundle hash: '+str(path))
        rel = str(path.relative_to(Path(root).resolve()))
        inputs[rel] = expected; protected.add(path)
        return raw, rel
    verified(manifest_path, binding['manifest_sha256'])
    current_identity_path = project_path(root, binding['identity_registry_path'])
    if current_identity_path.is_relative_to(manifest_path.parent):
        raise ContractError('Current project identity registry must be outside the historical blocking bundle')
    verified(current_identity_path, binding['identity_registry_sha256'])
    try:
        manifest = load_json(manifest_path)
        if manifest.get('schema_version') != '1.2' or manifest.get('source_contract_sha256') != digest(doc):
            raise ContractError('Blocking manifest schema or contract hash is stale')
        def reference(ref, suffix=None):
            if not isinstance(ref, dict) or not {'path','sha256'} <= set(ref):
                raise ContractError('Missing blocking file reference')
            # Both bundle-local and project-root confinement are mandatory.
            path = project_path(manifest_path.parent, ref['path'])
            if not path.is_relative_to(Path(root).resolve()): raise ContractError('Blocking file escapes asset root')
            if suffix and path.suffix.lower() != suffix: raise ContractError('Blocking diagram format mismatch')
            raw, rel = verified(path, ref['sha256'])
            if suffix == '.png':
                try:
                    with Image.open(io.BytesIO(raw)) as im:
                        if im.format != 'PNG': raise ContractError('Blocking raster must be PNG')
                        if im.width*im.height > 40000000: raise ContractError('Raster exceeds 40 megapixels')
                        im.verify()
                except ContractError: raise
                except Exception as exc: raise ContractError('Invalid blocking PNG') from exc
            ref['root_path'] = rel
            return path
        sidecar = load_json(reference(manifest['blocking_spec']))
        roster = load_json(reference(manifest['roster']))
        coverage = load_json(reference(manifest['coverage']))
        current_identity = load_json(current_identity_path)
        snapshot_identity = load_json(reference(manifest['identity_registry']))
        if snapshot_identity != current_identity:
            raise ContractError('Blocking identity registry snapshot differs from current project registry')
        report = validate_blocking(sidecar, doc, roster=roster, identity_registry=current_identity)
        from director_identity import registry_binding, identity_legend
        if manifest.get('identity_registry_sha256') != digest(current_identity) or manifest.get('identity_binding') != registry_binding(current_identity):
            raise ContractError('Stale blocking identity registry hash or revision')
        if manifest.get('identity_legend') != identity_legend(sidecar['cast'],current_identity):
            raise ContractError('Blocking identity legend differs from project registry')
        if not report['ok']: raise ContractError('Blocking coverage validation failed: '+json.dumps(report['errors'],ensure_ascii=False))
        if coverage != report['coverage']: raise ContractError('Stale blocking coverage or roster')
        if manifest.get('roster_sha256') != digest(roster) or manifest.get('spec_sha256') != digest(sidecar):
            raise ContractError('Stale blocking roster/spec hash')
        # Every declared delivered file is bound, including reports and legacy views.
        inventory = manifest.get('files')
        if not isinstance(inventory, list) or not inventory or len(inventory) > 5000:
            raise ContractError('Invalid blocking file inventory')
        indexed = {}
        for ref in inventory:
            path = reference(ref)
            if path == manifest_path or path in indexed:
                raise ContractError('Duplicate or self-referencing blocking file inventory')
            indexed[path] = ref['sha256']
        for path in protected - {manifest_path,current_identity_path}:
            if indexed.get(path) != inputs[str(path.relative_to(Path(root).resolve()))]:
                raise ContractError('Blocking reference is absent or inconsistent in file inventory')
        for name in ('validation.json', 'index.html'):
            if project_path(manifest_path.parent, name) not in indexed:
                raise ContractError('Missing blocking delivery report in file inventory: '+name)
        def diagram(ref, suffix):
            path = reference(ref, suffix)
            if indexed.get(path) != ref['sha256']:
                raise ContractError('Blocking diagram is absent or inconsistent in file inventory')
        if manifest.get('review_status') != 'needs_manual_review':
            raise ContractError('Blocking bundle cannot assert artistic approval')
        expected_scenes = list(dict.fromkeys(s['scene_id'] for s in doc['shots']))
        scenes = manifest['scenes']
        if not isinstance(scenes,list) or [s['scene_id'] for s in scenes] != expected_scenes:
            raise ContractError('Blocking manifest must cover every scene exactly once')
        shot_map = {}
        sidecar_scenes = {s['scene_id']: s for s in sidecar['scenes']}
        for scene in scenes:
            source_scene = sidecar_scenes[scene['scene_id']]
            if scene.get('identity_legend') != identity_legend(sidecar['cast'],current_identity,source_scene['cast_ids']):
                raise ContractError('Blocking scene identity legend differs from project registry')
            if scene.get('location_id') != source_scene['location_id'] or scene.get('cast_ids') != source_scene['cast_ids']:
                raise ContractError('Stale blocking scene location or cast metadata')
            expected_shots = [s for s in doc['shots'] if s['scene_id'] == scene['scene_id']]
            if [s['shot_id'] for s in scene['shots']] != [s['shot_id'] for s in expected_shots]:
                raise ContractError('Blocking manifest must cover every shot exactly once')
            for ref in scene['files']: diagram(ref, '.svg')
            for ext in ('svg','png'): diagram(scene['overview'][ext], '.'+ext)
            for shot, expected in zip(scene['shots'], expected_shots):
                if shot['source_shot_no'] != expected['source_shot_no']: raise ContractError('Stale blocking source shot')
                for phase in ('entry','exit','movement'):
                    for ext in ('svg','png'): diagram(shot[phase][ext], '.'+ext)
                shot_map[shot['shot_id']] = shot
        return {'binding':dict(binding), 'scenes':{s['scene_id']:s for s in scenes},
                'shots':shot_map,'coverage':coverage,'inputs':inputs,'protected':protected}
    except ContractError: raise
    except (KeyError, TypeError, ValueError, OSError, AttributeError) as exc:
        raise ContractError('Malformed or incomplete blocking bundle: '+str(exc)) from exc


def render_design_board(doc, root, out_dir, review_plan=None, design_spec=None,
                        format='both', font_path=None, overwrite=False, protected_paths=(),
                        require_blocking=False):
    """Return manifest after publishing HTML/PNG and manifest last.

    Existing nonempty output directories are always rejected, even with overwrite.
    Use a fresh directory; publishing multiple files is not an atomic transaction. Caller supplies input JSON paths in
    protected_paths, since an in-memory document has no filesystem identity.
    """
    checked(doc)
    from director_review_plan import plan_review
    plan = plan_review(doc, windows=review_plan) if review_plan is not None else plan_review(doc)
    if format not in ('html', 'png', 'both'): raise ContractError('format must be html, png or both')
    spec = design_spec or {'schema_version': 'design-board-spec-1', 'contract_sha256': digest(doc), 'scenes': {}}
    if not isinstance(spec,dict): raise ContractError('Design spec must be an object')
    if spec.get('schema_version') != 'design-board-spec-1' or spec.get('contract_sha256') != digest(doc):
        raise ContractError('Design spec schema or contract hash is stale')
    if set(spec) - {'schema_version', 'contract_sha256', 'scenes', 'footer', 'blocking_bundle'}:
        raise ContractError('Unsupported design spec fields; blocking approvals are not interpreted in v1')
    if not isinstance(spec.get('scenes'), dict): raise ContractError('Design spec scenes must be an object keyed by scene_id')
    if set(spec['scenes'])-{s['scene_id'] for s in doc['shots']}: raise ContractError('Design spec contains an unknown scene; no mappings may be silently omitted')
    bundle = _blocking_bundle(doc, root, spec.get('blocking_bundle'), require_blocking)
    footer = spec.get('footer', {})
    if not isinstance(footer, dict) or set(footer)-{'tone','character_dynamics','cinematic_approach'}:
        raise ContractError('Unsupported footer mapping')
    footer_text = {}
    for key, ref in footer.items():
        if not isinstance(ref,dict) or set(ref)!={'source_pointer'} or not isinstance(ref['source_pointer'],str) or not ref['source_pointer'].startswith('/'):
            raise ContractError('Footer requires a contract JSON source_pointer')
        value = doc
        try:
            for token in ref['source_pointer'][1:].split('/'):
                token=token.replace('~1','/').replace('~0','~')
                value=value[int(token)] if isinstance(value,list) else value[token]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ContractError('Invalid footer source pointer: '+ref['source_pointer']) from exc
        if not isinstance(value,str): raise ContractError('Footer source pointer must resolve to original text')
        footer_text[key]=value
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc: raise ContractError('Pillow unavailable: design-board layout unsupported; no installation attempted') from exc
    fontfile = Path(font_path or FONT)
    if not fontfile.is_file(): raise ContractError('Supply a local CJK font with --font; no download attempted')
    font = ImageFont.truetype(str(fontfile), 32)
    measure = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    aset = {a['id']: a for a in doc['assets']}
    shots = {s['shot_id']: s for s in doc['shots']}
    inputs, issues, items, pages, image_data = {}, [], [], [], {}
    protected = {Path(p).resolve() for p in protected_paths}
    protected.add(fontfile.resolve())
    if bundle:
        inputs.update(bundle['inputs'])
        protected.update(bundle['protected'])
    else:
        issues.append({'reason': 'spatial_incomplete', 'detail': 'No complete hash-bound blocking bundle; legacy references are not coverage evidence'})
    # Preflight every referenced input, even a frame not on the first page.
    for a in doc['assets']:
        if a.get('path'):
            p = project_path(root, a['path']); protected.add(p)
            if p.is_file():
                if p.stat().st_size > 32*1024*1024: raise ContractError('Reference exceeds 32 MiB: '+a['path'])
                inputs[a['path']] = digest(p.read_bytes())
    for shot in doc['shots']:
        for frame in shot['keyframes']:
            if frame.get('image_path'): protected.add(project_path(root, frame['image_path']))
    item_count = 0
    text_count = 0
    def budget(value=''):
        nonlocal item_count,text_count
        item_count += 1; text_count += len(value)
        if item_count>50000 or text_count>1000000:
            raise ContractError('Design board limit: 50000 items / 1000000 text characters; use smaller review batches')
    def add_text(seq, ident, value):
        budget(str(value))
        seq.append({'id': ident, 'kind': 'text', 'text': str(value)})
    def add_image(seq, ident, path, expected=None, strict=False):
        budget()
        actual = None
        display_height = 400
        if path:
            p = project_path(root, path)
            if p.is_file():
                if p.stat().st_size > 32*1024*1024: raise ContractError('Image exceeds 32 MiB: '+path)
                actual = digest(p.read_bytes()); inputs[path] = actual
                if p.suffix.lower() == '.svg':
                    issues.append({'item_id': ident, 'reason': 'unsupported_svg_no_raster_preview', 'path': path, 'sha256': actual, 'display_height': 1000 if strict else 400})
                else:
                    raw = local_image(root, path)
                    if strict and digest(raw[0]) != expected: raise ContractError('Blocking raster changed during preflight: '+path)
                    try:
                        with Image.open(io.BytesIO(raw[0])) as im:
                            if im.width*im.height>40000000: raise ContractError('Raster exceeds 40 megapixels: '+path)
                            if strict:
                                display_height = min(1500, max(1, math.ceil(im.height*(COLS[1][1]-32)/im.width)))
                            im.verify()
                        image_data[ident] = raw
                    except ContractError: raise
                    except Exception as exc: raise ContractError('Invalid raster: '+path) from exc
            else: issues.append({'item_id': ident, 'reason': 'missing_image', 'path': path})
        else: issues.append({'item_id': ident, 'reason': 'missing_image_mapping'})
        if strict and (actual != expected or ident not in image_data):
            raise ContractError('Missing or stale required blocking raster: '+str(path))
        seq.append({'id': ident, 'kind': 'image', 'path': path, 'sha256': actual, 'display_height': display_height})
        if expected and actual != expected:
            issues.append({'item_id': ident, 'reason': 'stale_asset_hash', 'expected_sha256': expected, 'actual_sha256': actual})
            add_text(seq, ident+':binding', '参考资产哈希失效；未审核 / stale binding')
    def mapped(seq, aid, prefix):
        if aid not in aset: raise ContractError('Unknown explicitly mapped asset ID: '+str(aid))
        a = aset[aid]
        add_text(seq, prefix+':label', aid+' · 参考图，未认证人工审核')
        if a['kind'] != 'image': raise ContractError('Mapped asset must be image: '+aid)
        add_image(seq, prefix, a.get('path'), a.get('sha256'))
    def lines(value, width):
        # Each range includes its original newline; concatenation is lossless.
        result=[]; start=0; current=''
        for i,ch in enumerate(value):
            if ch == '\n':
                result.append((start,i+1,current)); start=i+1; current=''
            elif current and measure.textlength(current+ch,font=font)>width:
                result.append((start,i,current)); start=i; current=ch
            else: current+=ch
        if start < len(value): result.append((start,len(value),current))
        if not result: result=[(0,0,'')]
        return result
    def paginate(seq, col):
        chunks=[[]]; y=TOP; x,w=COLS[col]
        for index,item in enumerate(seq):
            if item['kind']=='text' and index+1<len(seq) and seq[index+1]['kind']=='image':
                needed=len(lines(item['text'],w-32))*LINE+16+seq[index+1].get('display_height',400)+20
                if needed<=BOTTOM-TOP and y+needed>BOTTOM:
                    chunks.append([]); y=TOP
            items.append(item)
            if item['kind']=='image':
                height=item.get('display_height',400)
                if y+height+20 > BOTTOM: chunks.append([]); y=TOP
                chunks[-1].append(dict(item, x=x+16,y=y,width=w-32,height=height)); y+=height+20
            else:
                for start,end,line in lines(item['text'],w-32):
                    if y+LINE > BOTTOM: chunks.append([]); y=TOP
                    chunks[-1].append({'id':item['id'],'kind':'text','start':start,'end':end,'text':line,'x':x+16,'y':y,'width':w-32,'height':LINE}); y+=LINE
                y+=16
        if len(chunks)>1000: raise ContractError('Design board exceeds 1000 pages')
        return chunks
    for wi,window in enumerate(plan['windows']):
        scene=window['scene_id']; mapping=spec['scenes'].get(scene,{})
        if not isinstance(mapping,dict) or set(mapping)-{'character_asset_ids','plate_asset_id','blocking_asset_ids'}:
            raise ContractError('Unsupported scene mapping: '+scene)
        seqs=[[],[],[]]; prefix=window['window_id']
        for key in ('character_asset_ids','blocking_asset_ids'):
            if not isinstance(mapping.get(key,[]),list): raise ContractError(key+' must be a list')
        for i,aid in enumerate(mapping.get('character_asset_ids',[])): mapped(seqs[0],aid,f'{prefix}:character:{i}')
        if not seqs[0]: add_image(seqs[0],prefix+':characters',None)
        if mapping.get('plate_asset_id'): mapped(seqs[1],mapping['plate_asset_id'],prefix+':plate')
        elif bundle: add_text(seqs[1],prefix+':plate-status','场景底图未提供；以下为空间示意，不是生成画面。')
        else: add_image(seqs[1],prefix+':plate',None)
        for i,aid in enumerate(mapping.get('blocking_asset_ids',[])): mapped(seqs[1],aid,f'{prefix}:blocking:{i}')
        if bundle:
            entry = bundle['scenes'][scene]
            add_text(seqs[1],prefix+':overview:label','场景总览 · schematic / needs_manual_review')
            add_image(seqs[1],prefix+':overview',entry['overview']['png']['root_path'],entry['overview']['png']['sha256'],strict=True)
            coverage_scene = next(c for c in bundle['coverage']['scenes'] if c['scene_id'] == scene)
            add_text(seqs[1],prefix+':coverage', '逐镜覆盖清单 / '+scene+' / '+coverage_scene['status']+' / 角色 '+', '.join(coverage_scene['expected_cast_ids']))
            seen = set()
            for seg in window['segments']:
                sid = seg['source_shot_id']
                if sid in seen: continue
                seen.add(sid)
                coverage_shot = next(c for c in coverage_scene['shots'] if c['shot_id'] == sid)
                add_text(seqs[1],prefix+':coverage:'+sid, sid+' / '+coverage_shot['status']+' / 应有角色 '+', '.join(coverage_shot['expected_cast_ids'])+' / 实有角色 '+', '.join(coverage_shot['actual_cast_ids']))
                for phase, label in [('entry','首站位'), ('exit','末站位'), ('movement','走位')]:
                    ref = bundle['shots'][sid][phase]['png']
                    ident = prefix+':blocking:'+sid+':'+phase
                    add_text(seqs[1],ident+':label',sid+' / '+label+' · 全镜上下文；跨窗重复不新增时长 · 示意待人工审核')
                    add_image(seqs[1],ident,ref['root_path'],ref['sha256'],strict=True)
                    seqs[1][-1].update(context_only=True, adds_duration_sec=0, source_shot_id=sid, blocking_phase=phase)
            add_text(seqs[1],prefix+':blocking-status','全项目逐镜空间覆盖与字节绑定已核验；示意图 schematic，剧情与空间关系仍须人工审核。')
        else:
            add_text(seqs[1],prefix+':blocking-status','spatial_incomplete · 空间资料不完整。参考图仅陈列，不代表站位或走位审核。')
        for key in ('tone','character_dynamics','cinematic_approach'):
            add_text(seqs[1],prefix+':footer:'+key+':label',key+' · 合同引用（审批未独立核验）' if key in footer_text else key+' · 待定')
            if key in footer_text:
                add_text(seqs[1],prefix+':footer:'+key,footer_text[key])
                seqs[1][-1]['source_pointer']=footer[key]['source_pointer']
        for seg in window['segments']:
            sid=seg['source_shot_id']; s=shots[sid]; a=seg['review_start_sec']; b=seg['review_end_sec']; p=prefix+':'+sid
            add_text(seqs[2],p+':time',f'{sid} / 原镜 {s["source_shot_no"]} / {a}–{b}s（镜内时间；分页不是剪切）')
            frames=[k for k in s['keyframes'] if a<=k['time_sec']<b or (b==s['duration_sec'] and k['time_sec']==b)]
            for k in frames:
                kp=p+':frame:'+k['id']
                add_text(seqs[2],kp+':label',f'{k["id"]} / {k["phase"]} / {k["time_sec"]}s')
                add_image(seqs[2],kp,k.get('image_path'))
                seqs[2][-1]['review_label']=review_label(k,doc,root)
                seqs[2][-1]['declared_reviewed_sha256']=k.get('visual_review',{}).get('reviewed_sha256')
                add_text(seqs[2],kp+':state',k['visible_state']['zh'])
                add_text(seqs[2],kp+':review',review_label(k,doc,root))
            if not frames: add_text(seqs[2],p+':no-frames','该时间窗无已生成关键帧；不拿其它时刻图替代。')
            for kind in ('beats','dialogue'):
                for j,obj in enumerate(s[kind]):
                    if obj['end_sec']<=a or obj['start_sec']>=b: continue
                    ident=p+':'+kind+':'+str(j)
                    add_text(seqs[2],ident+':timing',f'{kind} {obj["start_sec"]}–{obj["end_sec"]}s / 完整原项；跨窗重复仅供上下文')
                    if kind=='dialogue':
                        add_text(seqs[2],ident+':speaker',obj['speaker_label']['zh'])
                        add_text(seqs[2],ident+':text',obj['text'])
                    else:
                        add_text(seqs[2],ident+':action',obj['action']['zh'])
                        add_text(seqs[2],ident+':camera',obj['camera']['zh'])
                        if obj.get('sound'): add_text(seqs[2],ident+':sound',obj['sound'].get('zh','') if isinstance(obj['sound'],dict) else obj['sound'])
            add_text(seqs[2],p+':soundscape',s['soundscape']['zh'])
        cols=[paginate(seq,i) for i,seq in enumerate(seqs)]
        count=max(map(len,cols))
        if len(pages)+count>1000: raise ContractError('Design board exceeds 1000 pages')
        for n in range(count):
            pages.append({'page_id':f'board-{wi+1:03d}-p{n+1:03d}','board_id':window['board_id'],'window_id':window['window_id'],'page_index':n+1,'page_count':count,'window_duration_sec':window['duration_sec'],'adds_duration_sec':0,'scene_id':scene,'items':[v for col in cols if n<len(col) for v in col[n]]})
    # Assert lossless coverage independently of visual line wrapping.
    by_item = {}
    for page in pages:
        for ref in page['items']: by_item.setdefault(ref['id'], []).append(ref)
    for item in items:
        if item['kind']!='text': continue
        refs=by_item.get(item['id'],[])
        if ''.join(item['text'][r['start']:r['end']] for r in refs)!=item['text']:
            raise ContractError('Internal text coverage error: '+item['id'])
    out=Path(out_dir)
    if out.is_symlink(): raise ContractError('Output directory must not be a symlink')
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise ContractError('Design-board output must be an empty or new directory; nonempty output is never overwritten (even with --overwrite)')
    names=['manifest.json']+(['index.html'] if format in ('html','both') else [])+([p['page_id']+'.png' for p in pages] if format in ('png','both') else [])
    for name in names:
        target=out/name
        if target.is_symlink() or target.resolve() in protected or (target.exists() and any(p.exists() and target.samefile(p) for p in protected)): raise ContractError('Output would overwrite input or symlink: '+str(target))
    out.mkdir(parents=True,exist_ok=True)
    esc=lambda v:html.escape(str(v),quote=True)
    html_parts=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>设计板 · 人审草稿</title><style>body{background:#ddd}.page{position:relative;width:3840px;height:2160px;background:#f8f7f3;margin:32px;overflow:hidden}.txt{position:absolute;font:32px/48px sans-serif;white-space:pre}.image{position:absolute;object-fit:contain;background:#e6e3d9}h1{font:40px sans-serif;margin:0;padding:48px 64px}p{margin:0}</style>']
    hashes={}
    for page in pages:
        im=Image.new('RGB',(WIDTH,HEIGHT),'#f8f7f3'); draw=ImageDraw.Draw(im)
        title=f'{page["board_id"]} / {page["window_id"]} / {page["page_index"]}/{page["page_count"]} · 设计板人审草稿'
        header=f'画板 16:9 / 影片 {doc["project"]["aspect_ratio"]} / 窗口 {page["window_duration_sec"]}s；续页不新增时长'
        html_parts.append('<section class="page"><h1>'+esc(title)+'</h1>')
        for x,y,text in [(64,120,header),(64,2040,'needs_manual_review · 未生成影视画面；空间图为示意 · Tone / Dynamics / Approach 见中栏；未擅自补写')]+[(x+16,210,label) for (x,w),label in zip(COLS,['角色 / 明确映射参考','场景 / 空间参考（未审核）','时间关键帧 / 动作 / 完整对白'])]:
            draw.text((x,y),text,font=font,fill='#334452')
            html_parts.append(f'<div class="txt" style="left:{x}px;top:{y}px">{esc(text)}</div>')
        draw.text((64,48),title,font=font,fill='#202b34')
        for x,w in COLS: draw.rectangle((x,200,x+w,2005),outline='#abb4b9',width=2)
        for r in page['items']:
            x,y,w,h=r['x'],r['y'],r['width'],r['height']
            if r['kind']=='text':
                draw.text((x,y),r['text'],font=font,fill='#23313b')
                html_parts.append(f'<div class="txt" style="left:{x}px;top:{y}px">{esc(r["text"])}</div>')
            else:
                raw=image_data.get(r['id'])
                if raw:
                    with Image.open(io.BytesIO(raw[0])) as inp:
                        pic=inp.convert('RGB'); pic.thumbnail((w,h)); im.paste(pic,(x+(w-pic.width)//2,y+(h-pic.height)//2))
                    src='data:'+raw[1]+';base64,'+base64.b64encode(raw[0]).decode('ascii')
                    html_parts.append(f'<img class="image" alt="{esc(r["id"])}" src="{src}" style="left:{x}px;top:{y}px;width:{w}px;height:{h}px">')
                else:
                    draw.rectangle((x,y,x+w,y+h),fill='#e6e3d9'); draw.text((x+20,y+150),'缺图 / 未生成或不支持预览',font=font,fill='#795a1c')
                    html_parts.append(f'<div class="txt image" style="left:{x}px;top:{y}px;width:{w}px;height:{h}px">缺图 / 未生成或不支持预览</div>')
        html_parts.append('</section>')
        if format in ('png','both'):
            target=out/(page['page_id']+'.png'); im.save(target,format='PNG'); hashes[target.name]=digest(target.read_bytes())
    if format in ('html','both'):
        target=out/'index.html'; target.write_text('\n'.join(html_parts)+'</html>\n',encoding='utf-8'); hashes[target.name]=digest(target.read_bytes())
    manifest={'schema_version':VERSION,'renderer_version':VERSION,'contract_sha256':digest(doc),'review_plan_sha256':digest(plan),'review_plan_input_sha256':digest(review_plan) if review_plan is not None else None,'design_spec_sha256':digest(spec),'input_asset_sha256':inputs,'font_sha256':digest(fontfile.read_bytes()),'canvas':{'width':WIDTH,'height':HEIGHT,'aspect_ratio':'16:9'},'total_duration_sec':plan['total_duration_sec'],'pages':pages,'source_items':items,'output_sha256':hashes,'issues':issues,'uncovered_items':[],'resource_limits':{'max_pages':1000,'max_items':50000,'max_text_characters':1000000,'max_raster_pixels':40000000},'layout_checks':{'text_ranges_lossless':True,'fixed_canvas':True},'status':'draft','spatial_status':'spatial_complete_schematic' if bundle else 'spatial_incomplete','blocking_bundle':bundle['binding'] if bundle else None,'visual_review':'needs_manual_review','html_pixel_parity':'not_verified_browser_font_dependent','unsupported':['SVG preview/conversion','blocking approval interpretation']}
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return manifest
