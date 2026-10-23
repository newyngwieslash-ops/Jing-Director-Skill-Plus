"""Offline blocking delivery: shared geometry, independent safe SVG/Pillow backends."""
from __future__ import annotations
from html import escape
from pathlib import Path
import io
import json
import math
import os
import shutil
import tempfile
import textwrap
from PIL import Image, ImageDraw, ImageFont
from director_core import ContractError, digest

MAX_FILES = 5000
MAX_IMAGE_PIXELS = 12_000_000
MAX_TOTAL_PIXELS = 160_000_000
FONT = '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'


def geometry(scene, shot, location, cast, kind, identity_binding=None):
    """A single unambiguous world frame. Drawing commands feed BOTH backends."""
    width = 1100
    commands = []
    def label(x, y, value, color='#172033', size=18):
        commands.append(('text', (x, y), str(value), color, size))
    def line(points, color='#172033', thickness=2, style='solid'):
        commands.append(('line', points, color, thickness, style))
    def arrow(a, z, color, thickness=2, style='solid'):
        line([a, z], color, thickness, style)
        theta = math.atan2(z[1]-a[1], z[0]-a[0])
        commands.append(('polygon', [z, (z[0]-9*math.cos(theta-.45),z[1]-9*math.sin(theta-.45)),(z[0]-9*math.cos(theta+.45),z[1]-9*math.sin(theta+.45))],color))
    y = 20
    def paragraph(value, color='#172033'):
        nonlocal y
        # Conservative CJK wrapping: no glyph-width assumptions needed.
        for part in textwrap.wrap(str(value), 54, replace_whitespace=True) or ['']:
            label(24, y, part, color); y += 27
    title = {'overview':'场景总览 / 第一镜 ENTRY（非全场同时状态）', 'entry':'ENTRY / 每镜起始站位', 'exit':'EXIT / 每镜结束站位', 'movement':'MOVEMENT / 每镜完整走位'}[kind]
    paragraph(f"{scene['scene_id']} | {title}")
    paragraph(f"原镜 {shot['source_shot_no']} | {shot['shot_id']} | {shot['duration_sec']:g}s | {location['name']}")
    paragraph(f"{location['coordinate_mode']} / {location['units']}；依据：{location['basis']}")
    paragraph('needs_manual_review / 待人工审核；坐标 x 向右、y 向上；0°东 / 90°北；N↑')
    paragraph('实心=ENTRY，空心=EXIT；虚线边框+OFF=画外；箭头=朝向/路径；CAM=机位')
    if kind == 'overview': paragraph('总览仅展示本场第一镜起始状态、场地和图例。各镜实际变化见逐镜图。')
    for cid in scene['cast_ids']:
        person = cast[cid]
        if not all(key in person for key in ('short_code', 'marker_shape', 'path_style')):
            raise ContractError('Geometry requires validated project identity metadata for '+cid)
    markers = {cid: cast[cid]['short_code'] for cid in scene['cast_ids']}
    paragraph('固定角色编号跨场不变；X=EXIT；E=X=首末相同；R=走位段')
    paragraph('身份=颜色＋形状＋编号；图例短线表示该角色的走位线型')
    if identity_binding is not None:
        paragraph(f"标识表 {identity_binding['project_id']} / r{identity_binding['revision']} / SHA256 {identity_binding['registry_sha256'][:12]}…")
    for cid in scene['cast_ids']:
        person = cast[cid]
        commands.append(('symbol', (38, y+10, 10), person['color'], person['color'], 2, False, person['marker_shape']))
        line([(60,y+10),(116,y+10)], person['color'], 3, person['path_style'])
        for part in textwrap.wrap(f"{markers[cid]} = {cid}: {person['name']}", 46, replace_whitespace=True) or ['']:
            label(136,y,part); y += 27
    for i, mark in enumerate(location['landmarks'],1): paragraph(f"地标 {i}: {mark['label']} ({mark['id']}) / {'阻挡' if mark['blocking'] else '非阻挡'}")
    bounds=location['bounds']; left=70; top=y+25; pw=960; ph=600
    scale=min(pw/bounds['w'],ph/bounds['h'])
    if not math.isfinite(scale) or scale <= 0: raise ContractError('Coordinate scale cannot be represented safely')
    ox=left+(pw-bounds['w']*scale)/2; oy=top+(ph-bounds['h']*scale)/2
    def xy(x,yy): return ox+(x-bounds['x'])*scale,oy+(bounds['y']+bounds['h']-yy)*scale
    commands.append(('rect',(ox,oy,ox+bounds['w']*scale,oy+bounds['h']*scale),'#fbfcff','#64748b',2))
    label(1015,top-24,'N ↑')
    landmark_rects=[]
    for i,mark in enumerate(location['landmarks'],1):
        a=xy(mark['x']-mark['w']/2,mark['y']+mark['h']/2); z=xy(mark['x']+mark['w']/2,mark['y']-mark['h']/2)
        landmark_rects.append((a[0]-5,a[1]-5,z[0]+5,z[1]+5))
        commands.append(('rect',(*a,*z),'#cbd5e1' if mark['blocking'] else '#edf2f7','#64748b',2))
        label(a[0]+3,a[1]+3,i,size=15)
    for wall in location['walls']: line([xy(*p) for p in wall],thickness=4)
    route_segments=[]
    if kind == 'movement':
        for ri, route in enumerate(shot['trajectories'], 1):
            pts=[xy(*p) for p in route['points']]; color=cast[route['who']]['color']
            route_segments.extend(zip(pts,pts[1:]))
            for a,z in zip(pts,pts[1:]): arrow(a,z,color,3,cast[route['who']]['path_style'])
            # Compact route keys belong near path midpoints, not crowded endpoints.
            lengths = [math.dist(a,z) for a,z in zip(pts,pts[1:])]
            remaining = sum(lengths)/2
            midpoint = pts[0]
            for a,z,length in zip(pts,pts[1:],lengths):
                if length and remaining <= length:
                    ratio = remaining/length
                    midpoint = (a[0]+ratio*(z[0]-a[0]), a[1]+ratio*(z[1]-a[1]))
                    break
                remaining -= length
            label(midpoint[0],midpoint[1]+18,f'R{ri}',size=15)
    placed_label_rects=[]
    def overlaps(a,b):
        return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]
    def line_hits_rect(start,end,rect):
        # Liang-Barsky clipping. Only label positions change; geometry is untouched.
        dx=end[0]-start[0];dy=end[1]-start[1];low=0.;high=1.
        for p,q in ((-dx,start[0]-rect[0]),(dx,rect[2]-start[0]),(-dy,start[1]-rect[1]),(dy,rect[3]-start[1])):
            if abs(p)<1e-12:
                if q<0: return False
                continue
            ratio=q/p
            if p<0: low=max(low,ratio)
            else: high=min(high,ratio)
            if low>high: return False
        return True
    def identity_labels(px,py,code,state,off):
        labels=[(code,0)] + ([(state,45)] if state else []) + ([('OFF',64)] if off else [])
        # Conservative width estimates include a safety margin; text remains dark.
        widths=[4+sum(10 if ord(c)<128 else 15 for c in text) for text,_ in labels]
        max_width=max(widths);max_offset=max(offset for _,offset in labels)
        candidates=[(px+16,py-28),(px-16-max_width,py-28),
                    (px-max_width/2,py-24-max_offset-18),(px-max_width/2,py+24),
                    (px+24,py-50-max_offset),(px-24-max_width,py-50-max_offset),
                    (px+24,py+38),(px-24-max_width,py+38)]
        best=None
        for index,(lx,ly) in enumerate(candidates):
            boxes=[(lx-2,ly+offset-2,lx+width+2,ly+offset+18) for width,(_,offset) in zip(widths,labels)]
            clipped=sum(b[0]<ox+3 or b[1]<oy+3 or b[2]>ox+bounds['w']*scale-3 or b[3]>oy+bounds['h']*scale-3 for b in boxes)
            blocked=sum(overlaps(b,o) for b in boxes for o in landmark_rects+placed_label_rects)
            crossed=sum(line_hits_rect(a,z,b) for b in boxes for a,z in route_segments)
            score=(clipped,blocked,crossed,index)
            if best is None or score<best[0]: best=(score,lx,ly,boxes)
            if score[:3]==(0,0,0): break
        _,lx,ly,boxes=best
        # Clamp the fallback so a crowded boundary cannot clip a label.
        lx=min(max(lx,ox+5),ox+bounds['w']*scale-max_width-5)
        ly=min(max(ly,oy+5),oy+bounds['h']*scale-max_offset-23)
        boxes=[(lx-2,ly+offset-2,lx+width+2,ly+offset+18) for width,(_,offset) in zip(widths,labels)]
        placed_label_rects.extend(boxes)
        # Leaders are needed only for displaced vertical groups, not left/right labels.
        if abs(ly-(py-28))>1:
            near_y=min(max(py,ly),ly+max_offset+18)
            near_x=min(max(px,lx),lx+max_width)
            line([(px,py),(near_x,near_y)],'#64748b',1)
        for value,offset in labels: label(lx,ly+offset,value,size=15)
    def token(state,cid,color,shape,hollow=False,camera=False,coincident=False):
        px,py=xy(state['x'],state['y']); rad=math.radians(state['facing_deg']%360)
        off=state.get('visibility')=='offscreen'
        commands.append(('symbol',(px,py,14 if hollow else 10),None if hollow and kind=='movement' else ('#ffffff' if hollow else color),color,2,off,shape))
        if coincident: commands.append(('symbol',(px,py,14),None,color,2,off,shape))
        arrow((px,py),(px+25*math.cos(rad),py-25*math.sin(rad)),color)
        # Keep four-character project codes compact at dense cast spacing. State
        # is a separate line, never a suffix that can collide with the next actor.
        identity_labels(px,py,('CAM ' if camera else '')+cid,
                        None if camera else ('E=X' if coincident else ('X' if hollow else 'E')),off)
    for char in shot['characters']:
        same = kind=='movement' and char['entry']==char['exit']
        phases=['entry','exit'] if kind=='movement' and not same else ['exit' if kind=='exit' else 'entry']
        person = cast[char['id']]
        for phase in phases: token(char[phase],markers[char['id']],person['color'],person['marker_shape'],phase=='exit',coincident=same)
    for cam in shot['cameras']: token(cam,cam['id'],'#475569','square',camera=True)
    y=top+ph+45
    for ref in shot['evidence']: paragraph(f"依据 [{ref['field']}] {ref['quote']}")
    if shot.get('transition'): paragraph(f"转场待审: {shot['transition']['kind']} / {shot['transition']['evidence']}")
    if kind=='movement':
        for char in shot['characters']:
            routes=[r for r in shot['trajectories'] if r['who']==char['id']]
            if not routes: paragraph(f"{char['id']}: 原地无位移（允许朝向变化）0–{shot['duration_sec']:g}s")
            for r in routes: paragraph(f"R{shot['trajectories'].index(r)+1} / {markers[r['who']]} ({r['who']}) / beat {r['beat_index']} / {r['start_sec']:g}–{r['end_sec']:g}s: {r['reason']}")
    height=int(y+24)
    if width*height>MAX_IMAGE_PIXELS: raise ContractError('Blocking image pixel limit exceeded')
    def finite_values(value):
        if isinstance(value,(list,tuple)):
            return all(finite_values(v) for v in value)
        return not isinstance(value,(int,float)) or math.isfinite(value)
    if not finite_values(commands): raise ContractError('Rendered coordinates must remain finite')
    return width,height,commands


def stroke_segments(points, style):
    """Resolve dash geometry once; SVG and PNG receive identical visible segments."""
    if style == 'solid': return [(points[i], points[i+1]) for i in range(len(points)-1)]
    pattern = {'dashed': (12.0, 7.0), 'dotted': (2.0, 6.0)}.get(style)
    if pattern is None: raise ContractError('Unsupported path style')
    segments=[]; phase=0; remaining=pattern[0]
    for a,z in zip(points,points[1:]):
        length=math.dist(a,z)
        if not length: continue
        used=0.0
        while used < length-1e-9:
            step=min(remaining,length-used)
            if phase == 0:
                segments.append(((a[0]+(z[0]-a[0])*used/length,a[1]+(z[1]-a[1])*used/length),
                                 (a[0]+(z[0]-a[0])*(used+step)/length,a[1]+(z[1]-a[1])*(used+step)/length)))
            used+=step;remaining-=step
            if remaining < 1e-9: phase=1-phase; remaining=pattern[phase]
    return segments


def symbol_points(x,y,r,shape):
    if shape == 'square': return [(x-r,y-r),(x+r,y-r),(x+r,y+r),(x-r,y+r)]
    if shape == 'diamond': return [(x,y-r),(x+r,y),(x,y+r),(x-r,y)]
    if shape == 'triangle': return [(x,y-r),(x+r,y+r),(x-r,y+r)]
    if shape == 'circle':
        return [(x+r*math.cos(i*math.tau/64),y+r*math.sin(i*math.tau/64)) for i in range(64)]
    raise ContractError('Unsupported identity marker shape')


def render_pair(drawing, font_path=None):
    width,height,commands=drawing
    im=Image.new('RGB',(width,height),'white'); d=ImageDraw.Draw(im); fonts={}
    svg=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img"><title>场景调度待人工审核</title><rect width="100%" height="100%" fill="white"/>']
    def coords(points): return ' '.join(f'{x:.6f},{y:.6f}' for x,y in points)
    def stroke(pts,color,t,style):
        # Explicit segments avoid backend-specific dash scaling or phase drift.
        for start,end in stroke_segments(pts,style):
            d.line([start,end],fill=color,width=t)
            svg.append(f'<polyline points="{coords([start,end])}" fill="none" stroke="{color}" stroke-width="{t}"/>')
    for cmd in commands:
        kind=cmd[0]
        if kind=='text':
            _,(x,y),value,color,size=cmd
            if size not in fonts: fonts[size]=ImageFont.truetype(str(font_path or FONT),size)
            d.text((x,y),value,font=fonts[size],fill=color,anchor='lt')
            svg.append(f'<text x="{x:.6f}" y="{y:.6f}" dominant-baseline="text-before-edge" font-family="Noto Sans CJK SC,sans-serif" font-size="{size}" fill="{color}">{escape(value)}</text>')
        elif kind=='line':
            _,pts,color,t,style=cmd; stroke(pts,color,t,style)
        elif kind=='polygon':
            _,pts,color=cmd; d.polygon(pts,fill=color)
            svg.append(f'<polygon points="{coords(pts)}" fill="{color}"/>')
        elif kind=='rect':
            _,(x,y,z,w),fill,outline,t=cmd; d.rectangle((x,y,z,w),fill=fill,outline=outline,width=t)
            svg.append(f'<rect x="{x:.6f}" y="{y:.6f}" width="{z-x:.6f}" height="{w-y:.6f}" fill="{fill}" stroke="{outline}" stroke-width="{t}"/>')
        elif kind=='symbol':
            _,(x,y,r),fill,outline,t,offscreen,shape=cmd
            pts=symbol_points(x,y,r,shape)
            if fill is not None: d.polygon(pts,fill=fill)
            svg.append(f'<polygon data-marker-shape="{shape}" points="{coords(pts)}" fill="{fill or 'none'}"/>')
            # OFF is an outline-only state. It never changes the identity path style.
            stroke(pts+[pts[0]],outline,t,'dotted' if offscreen else 'solid')
        else: raise ContractError('Unknown shared drawing command: '+str(kind))
    svg.append('</svg>'); stream=io.BytesIO(); im.save(stream,format='PNG')
    return ''.join(svg).encode('utf8'),stream.getvalue()


def publish(spec,contract,roster,report,out_dir,legacy_renderer,font_path=None,identity_registry=None):
    """Validate first in caller; stage all outputs then rename to new/empty target."""
    root=Path(os.path.abspath(out_dir))
    if root.is_symlink() or (root.exists() and (not root.is_dir() or any(root.iterdir()))):
        raise ContractError('Blocking output requires a new or empty directory; overwrite cannot mix versions')
    if not isinstance(identity_registry, dict): raise ContractError('Project identity registry is required')
    identities={x['character_id']:x for x in identity_registry['characters']}
    locations={x['id']:x for x in spec['locations']}; cast={x['id']:{**x, **identities[x['id']]} for x in spec['cast']}
    def identity_legend(ids):
        return [{key: (cid if key=='character_id' else cast[cid][key]) for key in ('character_id','name','short_code','color','marker_shape','path_style')} for cid in ids]
    shot_count=sum(len(s['shots']) for s in spec['scenes'])
    if 6*shot_count+2*len(spec['scenes'])+7>MAX_FILES: raise ContractError('Blocking output file count limit exceeded')
    root.parent.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix='.blocking-stage-',dir=root.parent))
    files=[]; entries=[]; total_pixels=0
    def write(relative,data):
        data=data.encode('utf8') if isinstance(data,str) else data
        target=stage/relative; target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(data)
        record=dict(path=relative,sha256=digest(data)); files.append(record); return record
    def pair(prefix,scene,shot,kind):
        nonlocal total_pixels
        drawing=geometry(scene,shot,locations[scene['location_id']],cast,kind,spec['identity_binding'])
        total_pixels+=drawing[0]*drawing[1]
        if total_pixels>MAX_TOTAL_PIXELS: raise ContractError('Blocking total pixel limit exceeded')
        svg,png=render_pair(drawing,font_path)
        return dict(svg=write(prefix+'.svg',svg),png=write(prefix+'.png',png))
    try:
        for i,scene in enumerate(spec['scenes'],1):
            folder=f'scene-{i:03d}'
            entry=dict(scene_id=scene['scene_id'],location_id=scene['location_id'],cast_ids=scene['cast_ids'],identity_legend=identity_legend(scene['cast_ids']),shots=[],files=[])
            entry['overview']=pair(folder+'/overview',scene,scene['shots'][0],'overview')
            # Legacy aggregate SVGs are retired: only unambiguous registered views ship.
            for j,shot in enumerate(scene['shots'],1):
                item=dict(shot_id=shot['shot_id'],source_shot_no=shot['source_shot_no'])
                for kind in ('entry','exit','movement'): item[kind]=pair(f'{folder}/shot-{j:03d}/{kind}',scene,shot,kind)
                entry['shots'].append(item)
            entries.append(entry)
        coverage=report['coverage']
        coverage_ref=write('coverage.json',json.dumps(coverage,ensure_ascii=False,indent=2)+'\n')
        spec_ref=write('blocking.json',json.dumps(spec,ensure_ascii=False,indent=2)+'\n')
        roster_ref=write('roster.json',json.dumps(roster,ensure_ascii=False,indent=2)+'\n')
        identity_ref=write('identity-registry.json',json.dumps(identity_registry,ensure_ascii=False,indent=2)+'\n')
        html=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>完整场景调度审核</title><style>body{font:16px sans-serif;margin:2rem}img{max-width:1100px;width:100%}td,th{border:1px solid #aaa;padding:.5rem}</style><h1>场景总览＋逐镜首末站位＋走位</h1><p>needs_manual_review：结构覆盖完整不是艺术审核通过。总览仅代表第一镜起始状态。</p><p><a href="identity-registry.json">项目角色标识表</a> | <a href="coverage.json">逐镜覆盖清单 JSON</a> | <a href="manifest.json">文件哈希</a> | <a href="validation.json">校验报告</a></p>']
        def links(p): return f'<a href="{p["svg"]["path"]}">SVG</a> / <a href="{p["png"]["path"]}">PNG</a>'
        for entry in entries:
            html.append(f'<h2>{escape(entry["scene_id"])}</h2><h3>场景总览（首镜 ENTRY）</h3>'+links(entry['overview'])+f'<br><img src="{entry["overview"]["png"]["path"]}" alt="首镜起始状态总览">')
            html.append('<table><tr><th>原镜 / 镜号</th><th>角色覆盖</th><th>首站位</th><th>末站位</th><th>走位</th><th>审核</th></tr>')
            for item in entry['shots']:
                html.append('<tr><td>'+escape(str(item['source_shot_no'])+' / '+item['shot_id'])+'</td><td>'+escape(', '.join(entry['cast_ids']) or '空镜')+'</td>'+''.join('<td>'+links(item[k])+'</td>' for k in ('entry','exit','movement'))+'<td>needs_manual_review</td></tr>')
            html.append('</table>')
        write('index.html',''.join(html)+'</html>')
        write('validation.json',json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        manifest=dict(schema_version='1.2',identity_legend=identity_legend(list(cast)),identity_registry=identity_ref,identity_registry_sha256=digest(identity_registry),identity_binding=spec['identity_binding'],source_contract_sha256=report['source_sha256'],spec_sha256=report['spec_sha256'],review_status='needs_manual_review',scenes=entries,files=list(files),coverage=coverage_ref,blocking_spec=spec_ref,roster=roster_ref,roster_sha256=report['coverage']['roster_sha256'],hash_scope='Every delivered file except manifest.json (no self-hash)',rendering='Shared validated geometry; SVG and Pillow PNG independently drawn',total_png_pixels=total_pixels)
        write('manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
        # Refuse a target populated during staging, even when caller requested overwrite.
        if root.exists():
            if root.is_symlink() or not root.is_dir() or any(root.iterdir()): raise ContractError('Output changed during build')
            root.rmdir()
        os.rename(stage,root)
        return report
    finally:
        if stage.exists(): shutil.rmtree(stage)
