"""Offline method-sidecar planning, not a provider adapter or approval authority.

Contract 3.0 remains the sole source of shot facts. No command mutates it.
The dependency-free shape walker supports only our bundled schema vocabulary.
"""
from __future__ import annotations
import argparse
import copy
from decimal import Decimal
import html
import json
from pathlib import Path
import re
import sys
from director_core import ContractError, digest, load_json, num, validate as validate_contract

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 16 * 1024 * 1024
DEPARTMENTS = ('camera', 'lighting', 'color', 'performance', 'editing', 'sound')
CAPABILITIES = ('text_to_video', 'first_frame', 'last_frame', 'timestamped_multisegment')
SHAPES = {'S1': ('first_frame',), 'S2': ('text_to_video',), 'S3': ('first_frame', 'last_frame'), 'S4': ('timestamped_multisegment',)}


def _bounded(value):
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError, RecursionError) as exc:
        raise ContractError('Non-JSON or non-finite input') from exc
    if len(encoded.encode('utf-8')) > MAX_BYTES:
        raise ContractError('Method input exceeds 16 MiB')
    def depth(v, n=0):
        if n > 50:
            raise ContractError('Method input exceeds depth 50')
        if isinstance(v, dict):
            for x in v.values(): depth(x, n+1)
        elif isinstance(v, list):
            for x in v: depth(x, n+1)
    depth(value)


def _shape(value, rule, path='$'):
    errors = []
    def fail(msg): errors.append({'code':'METHOD_SHAPE', 'where':path, 'message':msg})
    if 'anyOf' in rule:
        if not any(not _shape(value,r,path) for r in rule['anyOf']): fail('No schema alternative matches')
        return errors
    types = {'object':lambda v:isinstance(v,dict),'array':lambda v:isinstance(v,list),
             'string':lambda v:isinstance(v,str),'integer':lambda v:isinstance(v,int) and not isinstance(v,bool),
             'number':num,'null':lambda v:v is None,'boolean':lambda v:isinstance(v,bool)}
    expected=rule.get('type',[])
    if isinstance(expected,str): expected=[expected]
    if expected and not any(types[t](value) for t in expected):
        fail('Expected '+ '/'.join(expected)); return errors
    if 'const' in rule and (type(value) is not type(rule['const']) or value != rule['const']): fail('Unexpected constant')
    if 'enum' in rule and value not in rule['enum']: fail('Unsupported value')
    if isinstance(value,dict):
        for k in rule.get('required',[]):
            if k not in value: fail('Missing '+k)
        for k,v in value.items():
            if k in rule.get('properties',{}): errors.extend(_shape(v,rule['properties'][k],path+'.'+k))
            elif rule.get('additionalProperties') is False: fail('Unknown field '+k)
    elif isinstance(value,list):
        if len(value)>rule.get('maxItems',10000): fail('Too many items')
        for i,v in enumerate(value): errors.extend(_shape(v,rule.get('items',{}),f'{path}[{i}]'))
    elif isinstance(value,str):
        if not rule.get('minLength',0)<=len(value)<=rule.get('maxLength',1000000): fail('String length outside bounds')
        if 'pattern' in rule and not re.search(rule['pattern'],value): fail('Pattern mismatch')
    elif num(value):
        if not rule.get('minimum',-float('inf'))<=value<=rule.get('maximum',float('inf')): fail('Number outside bounds')
    return errors


def _frames(seconds, fps):
    n=Decimal(str(seconds))*fps
    return int(n) if n==n.to_integral_value() else None


def _unknown(): return {'classification':'unknown','text':'','evidence':[]}


def scaffold(contract, fps=24):
    """Return a new draft; never round time or invent performance instructions."""
    _bounded(contract)
    if not isinstance(fps,int) or isinstance(fps,bool) or not 1<=fps<=120: raise ContractError('fps must be integer 1..120')
    baseline=validate_contract(contract)
    if not baseline['ok']: raise ContractError('Invalid canonical contract: '+json.dumps(baseline['errors'],ensure_ascii=False))
    pack={'method_schema_version':'1.0.0','contract_sha256':digest(contract),'fps':fps,
          'director_book':{d:{'rules':[]} for d in DEPARTMENTS},'shots':[],'change_requests':[]}
    cursor=0
    for shot in contract['shots']:
        n=_frames(shot['duration_sec'],fps)
        end=cursor+n if cursor is not None and n is not None else None
        pack['shots'].append({'shot_id':shot['shot_id'],'scene_id':shot['scene_id'],
            'role_ids':copy.deepcopy(shot['subjects']),'locked_source':copy.deepcopy(shot),
            'performance':[], 'repair':{'shot_attempt_budget':12,'same_design_failure_limit':3,'attempts':[]},
            'capability':{'requested_shape':'unknown','capabilities':{k:'unknown' for k in CAPABILITIES},'evidence':[],
                          'first_frame_ref':None,'last_frame_ref':None,'execution_ready':False},
            'sound':{'source_dialogue':copy.deepcopy(shot['dialogue']),
                     'source_soundscape':copy.deepcopy(shot['soundscape']),'source_music':copy.deepcopy(shot['music']),'cues':[]},
            'edit':{'source_in_frame':0,'source_out_frame':n,'program_in_frame':cursor,'program_out_frame':end,'transition':'cut','retime':False}})
        cursor=end
    return pack


def _pointer(contract, pointer):
    if not pointer.startswith('/'): raise ValueError('Absolute JSON pointer required')
    v=contract
    for part in pointer[1:].split('/'):
        part=part.replace('~1','/').replace('~0','~')
        if isinstance(v,list):
            if not re.fullmatch(r'0|[1-9][0-9]*',part): raise ValueError('Invalid index')
            v=v[int(part)]
        else: v=v[part]
    return v


def validate_pack(contract, pack):
    """Validate planning structure and bindings, not aesthetic/video quality."""
    _bounded(contract); _bounded(pack)
    errors=_shape(pack,load_json(ROOT/'schemas/director-method-pack.schema.json'))
    blockers=[]; derived={'shots':[]}
    def err(code,where,msg): errors.append({'code':code,'where':where,'message':msg})
    def block(code,where,msg): blockers.append({'code':code,'where':where,'message':msg})
    def report(): return {'method_schema_version':'1.0.0','structurally_valid':not errors,
        'status':'blocked' if errors else 'draft','execution_ready':False,
        'artistic_approval':False,'errors':errors,'blockers':blockers,'derived':derived}
    baseline=validate_contract(contract)
    if not baseline['ok']: err('CONTRACT_INVALID','$',json.dumps(baseline['errors'],ensure_ascii=False))
    if errors: return report()
    if pack['contract_sha256']!=digest(contract): err('STALE_CONTRACT','contract_sha256','Sidecar does not bind this exact canonical contract')
    expected=[s['shot_id'] for s in contract['shots']]
    actual=[s['shot_id'] for s in pack['shots']]
    if actual!=expected: err('SHOT_COVERAGE','shots','Require exact shot coverage and canonical order; no omissions, extras, duplicates or recut')
    canonical={s['shot_id']:s for s in contract['shots']}; fps=pack['fps']; cursor=0
    block('PLANNING_ONLY','$','Offline sidecars never certify execution, human approval or video quality')
    block('SOURCE_BASELINE_NOT_AUTHENTICATED','$','Hash binds the supplied canonical contract, not an independently authenticated original source; existing production evidence gates remain required')
    def evidence(items,where):
        for e in items:
            try:
                if digest(_pointer(contract,e['pointer']))!=digest(e['value']): raise ValueError('Evidence quote differs')
            except (KeyError,IndexError,TypeError,ValueError): err('SOURCE_EVIDENCE',where,'Unresolvable or changed contract evidence')
    def note(n,where):
        evidence(n['evidence'],where)
        if n['classification']=='source':
            if not n['evidence']: err('SOURCE_EVIDENCE',where,'Source assertion requires exact evidence')
            elif not any(isinstance(e['value'],str) and n['text']==e['value'] for e in n['evidence']): err('SOURCE_PARAPHRASE',where,'Source text must equal a quoted source string; classify interpretation as inference')
        elif n['classification']=='unknown':
            if n['text']: err('UNKNOWN_WITH_TEXT',where,'Unknown cannot carry an instruction')
            block('METHOD_UNKNOWN',where,'No instruction supplied')
        else: block('INFERENCE_UNAPPROVED',where,'Inference is advisory and not authorized to change source')
    for dept,card in pack['director_book'].items():
        ids=[]
        for r in card['rules']:
            w='director_book.'+dept+'.'+r['rule_id'];ids.append(r['rule_id'])
            if not r['shot_ids'] or len(r['shot_ids'])!=len(set(r['shot_ids'])) or not set(r['shot_ids'])<=set(expected): err('RULE_SCOPE',w,'Explicit valid unique shot scope required')
            note(r['preference'],w)
            if r['conflict']=='unresolved': block('STYLE_CONFLICT',w,'Resolve conflict without overriding source')
        if len(ids)!=len(set(ids)):err('DUPLICATE_RULE',dept,'Rule IDs must be unique within department')
    for m in pack['shots']:
        sid=m['shot_id']; w='shots.'+sid
        if sid not in canonical: continue
        s=canonical[sid]; n=_frames(s['duration_sec'],fps)
        if digest(m['locked_source'])!=digest(s): err('SOURCE_DRIFT',w,'Locked source cannot be changed by style, approval flag or sidecar proposal')
        if m['scene_id']!=s['scene_id']:err('SCENE_DRIFT',w,'Scene identity changed')
        if m['role_ids']!=s['subjects']:err('ROLE_COVERAGE',w,'Exact canonical subject coverage/order required; groups are not expanded by inference')
        seen=[]
        for p in m['performance']:
            key=(p['role_id'],p['beat_index']);seen.append(key)
            if p['role_id'] not in s['subjects']:err('PERFORMANCE_ROLE',w,'Unknown source role')
            if p['beat_index']>=len(s['beats']):err('PERFORMANCE_BEAT',w,'Unknown source beat index (zero based)')
            for k in ('task','attention','trigger','weight_support','contact_feedback','end_state'):note(p[k],w+'.performance.'+k)
        if len(seen)!=len(set(seen)):err('PERFORMANCE_DUPLICATE',w,'Duplicate role/beat record')
        if s['subjects'] and not m['performance']:block('PERFORMANCE_UNPLANNED',w,'No performance method annotations; source beats remain intact')
        repair=m['repair'];total=0;failures={};ids=[]
        for a in repair['attempts']:
            ids.append(a['attempt_id']);total+=a['batch_size']
            if a['repair_level'].endswith('_proposal'):err('PROPOSAL_NOT_ATTEMPT',w,'Redesign/edit/delete belong in inactive change_requests, not execution records')
            if a['outcome']=='failed' and not a['failure_codes']:err('FAILURE_CODE_REQUIRED',w,'Failed manual record requires diagnostic code')
            if len(a['failure_codes'])!=len(set(a['failure_codes'])):err('DUPLICATE_FAILURE_CODE',w,'Duplicate failure classification')
            if a['outcome']=='failed' and a['repair_level']!='video_to_video': failures[a['design_id']]=failures.get(a['design_id'],0)+a['batch_size']
        if len(ids)!=len(set(ids)):err('DUPLICATE_ATTEMPT',w,'Attempt IDs must be unique')
        if total>=repair['shot_attempt_budget']:block('SHOT_BUDGET_EXHAUSTED',w,'Manual attempt-unit budget exhausted; no automatic further generation')
        if total>repair['shot_attempt_budget']:err('SHOT_BUDGET_EXCEEDED',w,'Recorded attempt units exceed configured shot budget')
        for design,count in failures.items():
            if count>=repair['same_design_failure_limit']:block('DESIGN_FAILURE_LIMIT',w,'Design '+design+' reached failure limit; no automatic recut or deletion')
        cap=m['capability'];shape=cap['requested_shape']; missing=[]
        for k,v in cap['capabilities'].items():
            if v!='unknown' and not any(e['capability']==k and e['claim']==v and e['source'].strip() and e['observed_at'].strip() for e in cap['evidence']):err('CAPABILITY_EVIDENCE',w,'Capability claim lacks manual source and observation date: '+k)
            claims={e['claim'] for e in cap['evidence'] if e['capability']==k}
            if len(claims)>1:err('CAPABILITY_CONFLICT',w,'Conflicting capability evidence: '+k)
        for k in SHAPES.get(shape,()):
            if cap['capabilities'][k]!='supported':missing.append(k)
        if shape=='unknown':missing.append('prompt_shape')
        if shape in ('S1','S3') and not cap['first_frame_ref']:missing.append('first_frame_ref')
        if shape=='S3' and not cap['last_frame_ref']:missing.append('last_frame_ref')
        if missing:block('CAPABILITY_BLOCKED',w,'Unknown/unsupported/missing: '+', '.join(missing))
        else:block('CAPABILITY_MANUAL_ONLY',w,'Capability records and asset references are unverified planning claims, not API proof')
        snd=m['sound']
        for key,src in [('source_dialogue','dialogue'),('source_soundscape','soundscape'),('source_music','music')]:
            if digest(snd[key])!=digest(s[src]):err('SOUND_SOURCE_DRIFT',w+'.sound.'+key,'Preserve exact source audio facts')
        cueids=[]
        for cue in snd['cues']:
            cueids.append(cue['cue_id']);note(cue['description'],w+'.sound');note(cue['space']['position'],w+'.space')
            if n is None or not 0<=cue['start_frame']<cue['end_frame']<=n:err('CUE_TIME',w,'Cue frames must be within exact shot duration, exclusive out')
            if cue['space']['role_id'] is not None and cue['space']['role_id'] not in s['subjects']:err('CUE_ROLE',w,'Unknown sound-space source role')
            if cue['layer']=='DIALOGUE' and cue['description']['classification']!='source':err('DIALOGUE_INFERENCE',w,'No inferred dialogue allowed; preserve canonical dialogue and cite exact text')
            if cue['layer']=='DIALOGUE':
                matching=[d for d in s['dialogue'] if d['text']==cue['description']['text']]
                if not matching:err('DIALOGUE_ADDED',w,'Dialogue cue text must exist in canonical dialogue')
                elif not any(cue['space']['role_id']==d['speaker_id'] and cue['start_frame']==_frames(d['start_sec'],fps) and cue['end_frame']==_frames(d['end_sec'],fps) and cue['space']['relation']==({'voiceover':'nondiegetic'}.get(d['mode'],d['mode'])) for d in matching):err('DIALOGUE_BINDING',w,'Dialogue speaker, timing and spatial mode must exactly match the source; no silent re-attribution or retime')
        if len(cueids)!=len(set(cueids)):err('DUPLICATE_CUE',w,'Duplicate cue IDs')
        if not snd['cues']:block('SOUND_UNPLANNED',w,'No cue plan; source audio preserved separately')
        end=cursor+n if cursor is not None and n is not None else None
        expected_edit={'source_in_frame':0,'source_out_frame':n,'program_in_frame':cursor,'program_out_frame':end,'transition':'cut','retime':False}
        if m['edit']!=expected_edit:err('EDIT_DRIFT',w,'Exact source duration, canonical sequence and no retime required')
        if n is None:block('FRAME_UNREPRESENTABLE',w,'Duration cannot be represented at selected integer fps; no rounding performed')
        derived['shots'].append({'shot_id':sid,'attempt_units':total,'design_failures':failures,'prompt_shape_plannable':not missing,'duration_frames':n})
        cursor=end
    for c in pack['change_requests']:
        if not c['shot_ids'] or not set(c['shot_ids'])<=set(expected):err('CHANGE_SCOPE','change_requests','Proposal requires existing shot scope')
        block('INACTIVE_CHANGE_REQUEST',c['request_id'],'Proposal never mutates or authorizes source facts')
    derived['total_frames']=cursor
    return report()


def render_review(contract,pack):
    """Static, escaped diagnostic dashboard; raw evidence stays available below."""
    report=validate_pack(contract,pack)
    summary_pack=pack if isinstance(pack,dict) else {}
    def esc(x):return html.escape(str(x))
    def dump(x):return esc(json.dumps(x,ensure_ascii=False,indent=2))
    def table(headers,rows):
        return '<table><thead><tr>'+''.join('<th>'+esc(h)+'</th>' for h in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+esc(v)+'</td>' for v in row)+'</tr>' for row in rows)+'</tbody></table>' if rows else '<p class="muted">未填写 / no planning records</p>'
    def nt(n):
        refs='; '.join(e['pointer'] for e in n['evidence'])
        return '['+n['classification']+'] '+(n['text'] or 'unknown')+(' | evidence: '+refs if refs else '')
    parts=['<!doctype html><html lang="zh"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'">',
        '<title>Director methods — offline planning review</title><style>body{max-width:1200px;margin:2em auto;padding:0 1em;font:16px sans-serif;line-height:1.5;color:#24303b}pre{white-space:pre-wrap;overflow-wrap:anywhere}h1,.warning{color:#943a00}table{border-collapse:collapse;width:100%;margin:1em 0;table-layout:fixed}td,th{border:1px solid #ccd3da;padding:.5em;text-align:left;vertical-align:top;overflow-wrap:anywhere}th{background:#eef2f6}section{border-top:3px solid #73879a;margin-top:2em}.muted{color:#596671}details{margin:1em 0}summary{cursor:pointer;font-weight:bold}</style>',
        '<h1>离线方法规划 / 非生成结果、非人工批准</h1>',
        '<p class="warning">结构校验通过不等于可执行或制作批准。CLI exit 0 仅表示 structurally_valid=true；status=draft 仍可能存在阻断项。status=blocked 表示结构或合同约束错误。</p>',
        '<p>未能精确换算帧数时保留 null 并列出 FRAME_UNREPRESENTABLE，不做舍入；此时草案不能用于执行。图示角色颜色不代表服装或影片调色。</p>',
        table(['结构有效','规划状态','执行就绪','艺术批准','帧率'],[[report['structurally_valid'],report['status'],False,False,summary_pack.get('fps','unknown')]]),
        '<p>Canonical contract SHA-256: '+esc(summary_pack.get('contract_sha256',''))+'</p>',
        '<h2>错误与阻断项</h2>',table(['级别','代码','位置','说明'],[['ERROR',x['code'],x['where'],x['message']] for x in report['errors']]+[['BLOCKER',x['code'],x['where'],x['message']] for x in report['blockers']])]
    # Invalid shapes are reviewable as diagnostics, but are never indexed as valid records.
    if not report['errors'] or not any(x['code']=='METHOD_SHAPE' for x in report['errors']):
        parts.append('<h2>部门导演参数卡</h2>')
        for dept,card in pack['director_book'].items():
            parts.extend(['<h3>'+esc(dept)+'</h3>',table(['规则','镜头范围','偏好与证据','反例','冲突 / 优先级'],[[r['rule_id'],', '.join(r['shot_ids']),nt(r['preference']),r['counterexample'],r['conflict']+' / '+str(r['priority'])] for r in card['rules']])])
        derived={s['shot_id']:s for s in report['derived']['shots']}
        for shot in pack['shots']:
            sid=shot['shot_id'];d=derived.get(sid,{})
            parts.extend(['<section><h2>镜头 '+esc(sid)+' / 场景 '+esc(shot['scene_id'])+'</h2>',
                '<p>合同主体引用（可包含群组；不是独立人物覆盖计数）：'+esc(', '.join(shot['role_ids']))+'</p>',
                '<h3>表演方法：来源 / 推断 / 未知</h3>',table(['主体 / 节拍索引','任务','注意对象','触发','重心支撑','接触反馈','终态'],[[p['role_id']+' / '+str(p['beat_index']),*[nt(p[k]) for k in ('task','attention','trigger','weight_support','contact_feedback','end_state')]] for p in shot['performance']]),
                '<h3>修复账本：人工记录，不是供应商回执</h3>',table(['累计尝试单位 / 预算','各设计失败单位','同设计限制'],[[str(d.get('attempt_units','unknown'))+' / '+str(shot['repair']['shot_attempt_budget']),json.dumps(d.get('design_failures',{}),ensure_ascii=False),shot['repair']['same_design_failure_limit']]]),
                table(['尝试 / 设计','批量','结果','故障分类','修复层级','备注'],[[a['attempt_id']+' / '+a['design_id'],a['batch_size'],a['outcome'],', '.join(a['failure_codes']),a['repair_level'],a['note']] for a in shot['repair']['attempts']]),
                '<h3>能力与提示词形态：仅规划，不接通 API</h3>',table(['请求形态','能力声明','首帧引用','末帧引用','执行就绪'],[[shot['capability']['requested_shape'],json.dumps(shot['capability']['capabilities'],ensure_ascii=False),shot['capability']['first_frame_ref'],shot['capability']['last_frame_ref'],False]]),
                table(['能力','声明','人工来源','记录时间'],[[e['capability'],e['claim'],e['source'],e['observed_at']] for e in shot['capability']['evidence']]),
                '<h3>声音 Cue 与声源空间（出点不含）</h3>',table(['Cue / 层','帧范围','内容与分类','空间关系 / 主体','位置','素材引用'],[[c['cue_id']+' / '+c['layer'],str(c['start_frame'])+'–'+str(c['end_frame']),nt(c['description']),c['space']['relation']+' / '+str(c['space']['role_id']),nt(c['space']['position']),c['asset_ref']] for c in shot['sound']['cues']]),
                '<details><summary>保留的原始对白、环境声、音乐</summary><pre>'+dump({k:v for k,v in shot['sound'].items() if k!='cues'})+'</pre></details>',
                '<h3>剪辑帧计划：无重定时，固定切换</h3>',table(['源入 / 出帧','节目入 / 出帧','转场','重定时'],[[str(shot['edit']['source_in_frame'])+' / '+str(shot['edit']['source_out_frame']),str(shot['edit']['program_in_frame'])+' / '+str(shot['edit']['program_out_frame']),shot['edit']['transition'],shot['edit']['retime']]]),'</section>'])
        parts.extend(['<h2>未生效变更建议</h2>',table(['编号','范围','原因','建议','状态'],[[c['request_id'],', '.join(c['shot_ids']),c['reason'],c['proposed_change'],c['state']] for c in pack['change_requests']])])
    parts.extend(['<details><summary>完整校验报告 JSON</summary><pre>'+dump(report)+'</pre></details>',
        '<details><summary>完整方法包 JSON（含锁定源快照和证据）</summary><pre>'+dump(pack)+'</pre></details>',
        '<p class="muted">Evidence pointers and asset references are text only. No scripts, external requests, generation or approval authority.</p></html>'])
    return ''.join(parts)


def _read(path):
    p=Path(path)
    if p.stat().st_size>MAX_BYTES:raise ContractError('Input exceeds 16 MiB')
    def pairs(items):
        out={}
        for k,v in items:
            if k in out:raise ContractError('Duplicate JSON key: '+k)
            out[k]=v
        return out
    def invalid(value):raise ContractError('Non-finite JSON: '+value)
    v=json.loads(p.read_text(encoding='utf-8-sig'),object_pairs_hook=pairs,parse_constant=invalid)
    _bounded(v);return v


def _fresh_dir(path, inputs):
    p=Path(path)
    if any(x.is_symlink() for x in [p,*p.parents]):raise ContractError('Symlink output path rejected')
    if p.exists() and (not p.is_dir() or any(p.iterdir())):raise ContractError('Output directory must be absent or empty')
    for src in inputs:
        if p.resolve()==Path(src).resolve():raise ContractError('Output aliases input')
    p.mkdir(parents=True,exist_ok=True);return p


def _write(path,data):
    p=Path(path)
    if any(x.is_symlink() for x in [p,*p.parents]):raise ContractError('Symlink output rejected')
    with p.open('x',encoding='utf-8') as f:f.write(data)


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__);sub=ap.add_subparsers(dest='command',required=True)
    for command in ('scaffold','validate','review'):
        p=sub.add_parser(command);p.add_argument('--contract',required=True)
        if command!='scaffold':p.add_argument('--pack',required=True)
        if command!='validate':p.add_argument('--out',required=True)
        else:p.add_argument('--report')
        if command=='scaffold':p.add_argument('--fps',type=int,default=24)
    args=ap.parse_args(argv)
    try:
        contract=_read(args.contract)
        pack=scaffold(contract,args.fps) if args.command=='scaffold' else _read(args.pack)
        report=validate_pack(contract,pack)
        if args.command in ('scaffold','review'):
            out=_fresh_dir(args.out,[args.contract]+([args.pack] if args.command=='review' else []))
            if args.command=='scaffold':_write(out/'method-pack.json',json.dumps(pack,ensure_ascii=False,indent=2)+'\n')
            else:_write(out/'method-review.html',render_review(contract,pack))
            _write(out/'method-report.json',json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        elif args.report:_write(Path(args.report),json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(report,ensure_ascii=False,indent=2))
        return 0 if report['structurally_valid'] else 2
    except (OSError,ValueError,TypeError,KeyError,RecursionError) as exc:
        print('Method error: '+str(exc),file=sys.stderr);return 2

if __name__=='__main__':sys.exit(main())
