"""Deterministic review composition and generation-job plans. Never synthesizes images."""
from __future__ import annotations
import base64
import html
import io
from pathlib import Path
from director_core import ContractError, VERSION, check_files, digest, frame_binding, frame_inputs, group_boards, project_path, validate


def checked(doc):
    report=validate(doc)
    if not report['ok']: raise ContractError(str(report))
    return report


def local_image(root,rel):
    if not rel: return None
    p=project_path(root,rel)
    if not p.is_file(): return None
    if p.stat().st_size>32*1024*1024: raise ContractError(f"Review image exceeds 32 MiB: {rel}")
    raw=p.read_bytes()
    if raw.startswith(b'\x89PNG\r\n\x1a\n'): mime='image/png'
    elif raw.startswith(b'\xff\xd8\xff'): mime='image/jpeg'
    elif raw[:4]==b'RIFF' and raw[8:12]==b'WEBP': mime='image/webp'
    else: raise ContractError(f"Not a supported clean raster image (PNG/JPEG/WebP): {rel}")
    return raw,mime


def review_label(frame, doc, root):
    """Check byte binding, not reviewer identity or the artistic review itself."""
    declared = frame['visual_review']['status']
    actual = None
    try:
        if frame.get('image_path'):
            path = project_path(root, frame['image_path'])
            if path.is_file() and path.stat().st_size <= 32 * 1024 * 1024:
                actual = digest(path.read_bytes())
        if declared != 'passed':
            return f'合同声明 {declared}（未核验）' + (f'；当前 SHA-256: {actual}' if actual else '')
        expected = frame_binding(frame)
        frame_inputs(frame, {a['id']: a for a in doc['assets']}, root)
        missing = check_files([{'id': frame['id'], 'kind': 'image', 'path': frame.get('image_path'), 'sha256': expected}], root)
        if missing: raise ContractError('Current frame file is missing')
        return f'passed 声明的字节绑定已核验；不认证审核人或审美结论；当前 SHA-256: {actual}'
    except (ContractError, OSError) as exc:
        return f'合同声明 {declared}，未核验/已失效：{exc}；当前 SHA-256: {actual or "missing"}'


def render_html(doc,root):
    checked(doc);boards=group_boards(doc);byid={s['shot_id']:s for s in doc['shots']}
    esc=lambda value: html.escape(str(value),quote=True)
    parts=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
      '<title>'+esc(doc['project']['name'])+' · 时间化故事板审阅</title>',
      '''<style>body{font:15px/1.6 "Microsoft YaHei","Noto Sans CJK SC",sans-serif;color:#222b33;background:#f6f5f1;margin:24px}h1{font-size:26px}h2{font-size:21px}.notice{padding:12px;background:#fff2cd;border:1px solid #b99b3c}.board{break-before:page;margin-top:24px}table{border-collapse:collapse;width:100%;table-layout:fixed}th,td{border:1px solid #87929b;padding:10px;vertical-align:top;text-align:left}th{background:#e8ebeb}th:nth-child(1){width:9%}th:nth-child(2){width:56%}th:nth-child(3){width:15%}.frames{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.frame{border:1px solid #c3c8cc;padding:8px;margin:0}img{width:100%;aspect-ratio:16/9;object-fit:contain;background:#dededb}.missing{aspect-ratio:16/9;display:flex;align-items:center;justify-content:center;background:#e7e5dd;text-align:center;color:#765c3a;font-weight:700}.meta{font-size:12px;color:#56616a}pre{white-space:pre-wrap;word-break:break-word;font:inherit}.assetstrip{display:flex;gap:12px;flex-wrap:wrap}.asset{width:160px}ul{padding-left:18px}@media(max-width:850px){body{margin:10px}.frames{grid-template-columns:1fr}table{font-size:12px}}@media print{body{margin:0}.notice{border:2px solid #555}a{color:inherit}}@page{size:A3 landscape;margin:12mm}</style>''',
      '<h1>'+esc(doc['project']['name'])+' · 导演时间化故事板</h1>',
      '<div class="notice">本文件供人工审阅，不是视频模型的默认参考图。缺图位置明确标为未生成；静帧不能验证运动、口型、时长或成片连续性。</div>',
      '<p class="meta">Contract SHA-256: '+digest(doc)+'<br>合同审批声明（未独立核验）：'+esc(doc['review'])+'</p>']
    for board in boards['boards']:
        parts += ['<section class="board"><h2>'+esc(board['board_id'])+' / '+esc(board['total_duration_sec'])+'秒</h2>',
                  '<table><thead><tr><th>TIME</th><th>SHOT / ACTION</th><th>DIALOGUE</th><th>NOTES / VISUALS</th></tr></thead><tbody>']
        offset=0;assetids=[]
        for sid in board['shot_ids']:
            shot=byid[sid];d=shot['duration_sec'];assetids.extend(shot['reference_asset_ids'])
            parts+=['<tr><td>'+f'{offset:g}–{offset+d:g}s<br>'+esc(sid)+'<br>原镜'+esc(shot['source_shot_no'])+'</td><td><div class="frames">']
            for frame in shot['keyframes']:
                raw=local_image(root,frame.get('image_path'))
                if raw:
                    picture='<img alt="'+esc(frame['id'])+'" src="data:'+raw[1]+';base64,'+base64.b64encode(raw[0]).decode('ascii')+'">'
                else: picture='<div class="missing">计划关键帧 · 未生成<br>不是成品图像</div>'
                parts+=['<figure class="frame">'+picture+'<figcaption><strong>'+esc(frame['phase'])+f' / {frame["time_sec"]:g}s</strong><br>'+esc(frame['visible_state']['zh'])+'<br><span class="meta">审图：'+esc(review_label(frame,doc,root))+'</span></figcaption></figure>']
            parts+=['</div><p><b>观看任务：</b>'+esc(shot['director']['viewing_task'])+'</p>']
            for b in shot['beats']:
                parts+=['<p>'+f'{b["start_sec"]:g}–{b["end_sec"]:g}s · '+esc(b['action']['zh'])+'<br><b>摄影机：</b>'+esc(b['camera']['zh'])+'</p>']
            parts+=['</td><td>']
            if not shot['dialogue']: parts+=['无对白。']
            for q in shot['dialogue']:
                parts+=['<p>'+esc(q['speaker_label']['zh'])+f' / {q["start_sec"]:g}–{q["end_sec"]:g}s<br>“'+esc(q['text'])+'”</p>']
            parts+=['<p>'+esc(shot['soundscape']['zh'])+'</p></td><td><b>摄影理由：</b>'+esc(shot['director']['why_this_camera'])+'<p>'+esc(shot['camera']['composition'])+'</p><p>'+esc(shot['constraints']['zh'])+'</p><p class="meta">轴线：'+esc(shot['continuity']['axis_id'])+' / '+esc(shot['continuity']['axis_side'])+'</p></td></tr>']
            offset+=d
        parts+=['</tbody></table><h3>参考素材（仅陈列，不表示已上传模型）</h3><div class="assetstrip">']
        for a in doc['assets']:
            if a['id'] not in assetids: continue
            raw=local_image(root,a.get('path')) if a['kind']=='image' else None
            pic='<img alt="'+esc(a['id'])+'" src="data:'+raw[1]+';base64,'+base64.b64encode(raw[0]).decode('ascii')+'">' if raw else '<div class="missing">参考文件未显示</div>'
            parts+=['<div class="asset">'+pic+esc(a['id'])+'<br><span class="meta">'+esc(a['role'])+'</span></div>']
        parts+=['</div></section>']
    return '\n'.join(parts)+ '\n</html>\n'


def render_png(doc,root,out,font_path=None,overwrite=False):
    checked(doc)
    boards=group_boards(doc)['boards']
    if len(boards)!=1: raise ContractError("PNG renderer accepts one review board at a time. Use a source excerpt/HTML for multiple boards; do not silently omit shots.")
    try: from PIL import Image, ImageDraw, ImageFont
    except ImportError: raise ContractError("Optional PNG rendering requires Pillow: python -m pip install Pillow")
    candidates=[font_path, 'C:/Windows/Fonts/msyh.ttc','/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc','/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc']
    fontpath=next((str(p) for p in candidates if p and Path(p).is_file()),None)
    if not fontpath: raise ContractError("Supply --font with a local Chinese font. Fonts are not included in this package.")
    font=ImageFont.truetype(fontpath,23);titlefont=ImageFont.truetype(fontpath,33)
    W=2048;left=32;cols=[32,184,1352,1648,2016]
    scratch=Image.new('RGB',(W,64));d=ImageDraw.Draw(scratch)
    def wrap(value,width):
        lines=[]
        for para in str(value).split('\n'):
            line=''
            for ch in para:
                if line and d.textlength(line+ch,font=font)>width: lines.append(line);line=ch
                else: line+=ch
            lines.append(line)
        return lines
    layouts=[]
    for s in doc['shots']:
        cwidth=(cols[2]-cols[1]-42)//2
        cards=[]
        for k in s['keyframes']:
            caption=f"{k['phase']} / {k['time_sec']:g}s\n{k['visible_state']['zh']}\n审图：{review_label(k,doc,root)}"
            lines=wrap(caption,cwidth-18)
            cards.append((k,lines,300+len(lines)*32+24))
        cardrows=[cards[i:i+2] for i in range(0,len(cards),2)]
        frameheight=sum(max(c[2] for c in row)+12 for row in cardrows)
        action=wrap('观看任务：'+s['director']['viewing_task']+'\n'+'\n'.join(f"{b['start_sec']:g}–{b['end_sec']:g}s {b['action']['zh']} 摄影机：{b['camera']['zh']}" for b in s['beats']),cols[2]-cols[1]-24)
        dialogue=wrap(('\n'.join(q['speaker_label']['zh']+'：“'+q['text']+'”' for q in s['dialogue']) or '无对白。')+'\n'+s['soundscape']['zh'],cols[3]-cols[2]-24)
        notes=wrap(s['director']['why_this_camera']+'\n'+s['constraints']['zh'],cols[4]-cols[3]-24)
        h=max(frameheight+len(action)*32+36,len(dialogue)*32+30,len(notes)*32+30)
        layouts.append((s,cardrows,action,dialogue,notes,h))
    H=230+sum(x[-1] for x in layouts)+80
    if H>30000: raise ContractError("PNG would exceed safe height; use HTML or split review batches.")
    im=Image.new('RGB',(W,H),(248,247,243));draw=ImageDraw.Draw(im)
    draw.text((32,22),doc['project']['name']+' · 时间化故事板',font=titlefont,fill='#202b34')
    draw.text((32,80),'人审稿 / 缺图明确标为未生成 / 非默认视频输入 / 静帧不验证运动与口型',font=font,fill='#795a1c')
    draw.text((32,120),boards[0]['board_id']+f" / {boards[0]['total_duration_sec']:g}秒 / 合同审批声明（未独立核验）：{doc['review']['user']}",font=font,fill='#334452')
    y=175
    for x,label in zip(cols,['TIME','SHOT / ACTION','DIALOGUE','NOTES / VISUALS']):
        if x==cols[-1]: break
        draw.text((x+10,y+10),label,font=font,fill='#202b34')
    y+=55;offset=0
    def put(lines,x,y):
        for line in lines: draw.text((x,y),line,font=font,fill='#23313b');y+=32
        return y
    for s,rows,action,dialogue,notes,h in layouts:
        for x in cols: draw.line((x,y,x,y+h),fill='#65727b',width=2)
        draw.line((cols[0],y,cols[-1],y),fill='#65727b',width=2)
        put(wrap(f"{offset:g}–{offset+s['duration_sec']:g}s\n{s['shot_id']}\n原镜{s['source_shot_no']}",cols[1]-cols[0]-18),cols[0]+8,y+12)
        yy=y+12;cwidth=(cols[2]-cols[1]-42)//2
        for row in rows:
            rh=max(c[2] for c in row)
            for j,(k,lines,ch) in enumerate(row):
                x=cols[1]+12+j*(cwidth+12)
                raw=local_image(root,k.get('image_path'))
                draw.rectangle((x,yy,x+cwidth,yy+rh),outline='#b3b8ba',width=1)
                if raw:
                    with Image.open(io.BytesIO(raw[0])) as inp:
                        rgb=inp.convert('RGB');rgb.thumbnail((cwidth-12,288));im.paste(rgb,(x+(cwidth-rgb.width)//2,yy+6+(288-rgb.height)//2))
                else:
                    draw.rectangle((x+6,yy+6,x+cwidth-6,yy+294),fill='#e6e3d9')
                    draw.text((x+26,yy+118),'计划关键帧 · 未生成',font=font,fill='#795a1c')
                put(lines,x+8,yy+302)
            yy+=rh+12
        put(action,cols[1]+12,yy+8);put(dialogue,cols[2]+12,y+12);put(notes,cols[3]+12,y+12)
        offset+=s['duration_sec'];y+=h
    draw.line((cols[0],y,cols[-1],y),fill='#65727b',width=2)
    draw.text((32,y+15),'参考素材清单及完整审阅信息请查看同批 HTML；此 PNG 不代表已生成或已提交视频。',font=font,fill='#795a1c')
    out=Path(out);out.parent.mkdir(parents=True,exist_ok=True)
    with out.open('wb' if overwrite else 'xb') as f: im.save(f,format='PNG')


def frame_jobs(doc,root):
    checked(doc);aset={a['id']:a for a in doc['assets']};jobs=[]
    for s in doc['shots']:
        for k in s['keyframes']:
            refs=[dict(aset[a]) for a in k['reference_asset_ids']]
            missing=check_files(refs,root)
            prompt=f"{doc['project']['aspect_ratio']}，{doc['project']['style']['zh']}\n这是镜头{s['shot_id']}在{k['time_sec']:g}秒的单一画面状态，而不是整段动作的拼贴。\n{k['visible_state']['zh']}\n只绘制这一时刻可见的角色、道具与构图；参考图片按清单中职责使用。输出纯净画面，不绘制故事板表格、编号、边框、字幕、三视图或人物设定拼贴。\n"
            # Deliberately do not append the entire shot ending or future outcomes to every frame.
            jobs.append({'job_id':k['id'],'shot_id':s['shot_id'],'time_sec':k['time_sec'],
                         'purpose':'clean_video_keyframe','prompt_zh':prompt,'input_assets':refs,
                         'output_path':k.get('image_path') or f"frames/{s['shot_id']}/{k['id']}.png",
                         'contract_sha256':digest(doc),'missing_assets':missing,
                         'status':'blocked_missing_references' if missing else 'planned_not_executed',
                         'tool_call_id':None,'executed':False,'visual_review':'unreviewed'})
    return {'schema_version':VERSION,'jobs':jobs,'warning':'Job plans only. Filenames and planned labels do not upload references or prove generation. A real image tool must be invoked and its result reviewed.'}


def continuity_graph(doc):
    checked(doc);edges=[]
    for a,b in zip(doc['shots'],doc['shots'][1:]):
        ac,bc=a['continuity'],b['continuity']
        common=set(ac['exit_state'])&set(bc['entry_state'])
        edges.append({'from':a['shot_id'],'to':b['shot_id'],'same_scene':a['scene_id']==b['scene_id'],
                      'matching_state_keys':sorted(k for k in common if ac['exit_state'][k]==bc['entry_state'][k]),
                      'changed_state_keys':sorted(k for k in common if ac['exit_state'][k]!=bc['entry_state'][k]),
                      'requires_visual_comparison':True,'exceptions':bc['exceptions']})
    return {'schema_version':VERSION,'nodes':[{'shot_id':s['shot_id'],'scene_id':s['scene_id'],'axis_id':s['continuity']['axis_id'],'axis_side':s['continuity']['axis_side'],'entry':s['continuity']['entry_state'],'exit':s['continuity']['exit_state'],'lookahead_source_shots':s['continuity']['lookahead_source_shots']} for s in doc['shots']], 'edges':edges,'status':'explicit_state_graph_not_visual_proof'}
