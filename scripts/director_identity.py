"""Project-stable diagram identity. Pure validation; never allocates or approves colors."""
from __future__ import annotations
import itertools
import math
import re
from director_core import digest

SCHEMA = 'character-identity-1'
MAX_CHARACTERS = 10000
SHAPES = ('circle', 'square', 'diamond', 'triangle')
PATH_STYLES = ('solid', 'dashed', 'dotted')
HEX = re.compile(r'#[0-9a-fA-F]{6}\Z')
CODE = re.compile(r'[A-Z][A-Z0-9]{0,7}\Z')


def registry_binding(registry):
    return {'project_id':registry['project_id'], 'revision':registry['revision'],
            'registry_sha256':digest(registry)}


def identity_legend(cast, registry, ids=None):
    people = {x['character_id']:x for x in registry['characters']}
    names = {x['id']:x['name'] for x in cast}
    return [dict(people[cid], name=names[cid]) for cid in (ids if ids is not None else names)]


def rgb(color):
    return tuple(int(color[i:i+2], 16)/255 for i in (1,3,5))


def luminance(color):
    channels = [v/12.92 if v <= .04045 else ((v+.055)/1.055)**2.4 for v in rgb(color)]
    return sum(a*b for a,b in zip(channels,(.2126,.7152,.0722)))


def contrast(a,b):
    a,b = sorted((luminance(a),luminance(b)))
    return (b+.05)/(a+.05)


def validate_identity(spec, registry):
    report = {'status':'blocked','errors':[],'warnings':[], 'registry_sha256':None,
              'project_id':None,'revision':None,'legend':[],
              'checks':'Structural and heuristic only; final-size visual/manual review required'}
    def issue(code,where,message,warning=False):
        report['warnings' if warning else 'errors'].append(dict(code=code,where=where,message=message))
    def string(value,limit=128):
        return isinstance(value,str) and 0<len(value.strip())<=limit and value==value.strip() and all(ord(c)>=32 for c in value)
    if not isinstance(registry,dict):
        issue('IDENTITY_REQUIRED','identity_registry','Project identity registry is required; never infer identity from scene order')
        return report
    try:
        report['registry_sha256'] = digest(registry)
    except (TypeError,ValueError,OverflowError):
        issue('IDENTITY_JSON','identity_registry','Only finite JSON values are supported'); return report
    if set(registry) != {'schema_version','project_id','revision','characters'}:
        issue('IDENTITY_FIELDS','identity_registry','Exactly schema_version, project_id, revision and characters are required')
    if registry.get('schema_version') != SCHEMA: issue('IDENTITY_VERSION','identity_registry','Unsupported identity registry schema')
    if not string(registry.get('project_id')): issue('IDENTITY_PROJECT','identity_registry','A bounded, nonempty project ID is required')
    revision = registry.get('revision')
    if not isinstance(revision,int) or isinstance(revision,bool) or not 1<=revision<=2147483647:
        issue('IDENTITY_REVISION','identity_registry','Revision must be an integer from 1 to 2147483647')
    entries=registry.get('characters')
    if not isinstance(entries,list) or len(entries)>MAX_CHARACTERS:
        issue('IDENTITY_CHARACTERS','identity_registry','Explicit character array of at most 10000 records required'); return report
    people={}; codes=set()
    for i,p in enumerate(entries):
        where=f'identity_registry.characters[{i}]'
        if not isinstance(p,dict): issue('IDENTITY_CHARACTER',where,'Expected character object'); continue
        if set(p) != {'character_id','short_code','color','marker_shape','path_style'}:
            issue('IDENTITY_CHARACTER_FIELDS',where,'Exactly character_id, short_code, color, marker_shape, path_style required')
        cid=p.get('character_id'); code=p.get('short_code'); color=p.get('color')
        if not string(cid) or cid in people:
            issue('IDENTITY_CHARACTER_ID',where,'Unique bounded character ID required')
        else: people[cid]=p
        if not isinstance(code,str) or not CODE.fullmatch(code) or code in codes:
            issue('IDENTITY_SHORT_CODE',where,'Unique project short code matching [A-Z][A-Z0-9]{0,7} required')
        else: codes.add(code)
        if not isinstance(color,str) or not HEX.fullmatch(color): issue('IDENTITY_COLOR',where,'Six-digit #RRGGBB color required')
        if p.get('marker_shape') not in SHAPES: issue('IDENTITY_SHAPE',where,'Unsupported marker shape')
        if p.get('path_style') not in PATH_STYLES: issue('IDENTITY_PATH_STYLE',where,'Unsupported path style')
    if report['errors']: return report
    report['project_id']=registry['project_id']; report['revision']=revision
    if not isinstance(spec,dict): issue('IDENTITY_SPEC','blocking','Expected blocking object'); return report
    binding=spec.get('identity_binding')
    if binding != registry_binding(registry):
        issue('IDENTITY_BINDING','identity_binding','Blocking identity binding must match current registry project, revision and canonical hash')
    cast=spec.get('cast')
    if not isinstance(cast,list): issue('IDENTITY_CAST','cast','Expected cast array'); return report
    usable=[]
    for p in cast:
        if not isinstance(p,dict) or not isinstance(p.get('id'),str):
            issue('IDENTITY_CAST','cast','Cast record requires character ID'); continue
        cid=p['id']
        if cid not in people:
            issue('IDENTITY_CHARACTER_MISSING',cid,'Character is absent from project identity registry'); continue
        if p.get('color') != people[cid]['color']:
            issue('IDENTITY_COLOR_MISMATCH',cid,'Cast color must exactly match project registry color, including canonical spelling')
        if not string(p.get('name'),256): issue('IDENTITY_NAME',cid,'Bounded nonempty character name required'); continue
        usable.append(p)
    report['legend']=identity_legend(usable,registry)
    # Pairwise visual ambiguity is bounded per scene, not across the entire project.
    scenes=spec.get('scenes')
    if not isinstance(scenes,list): issue('IDENTITY_SCENES','scenes','Expected scene array'); return report
    pair_checks=0
    for scene in scenes:
        if not isinstance(scene,dict) or not isinstance(scene.get('cast_ids'),list): continue
        scene_ids=scene['cast_ids']; where=str(scene.get('scene_id'))
        if len(scene_ids)>500:
            issue('IDENTITY_SCENE_LIMIT',where,'At most 500 individually diagrammed characters per scene'); continue
        present=[people[x] for x in scene_ids if isinstance(x,str) and x in people]
        for p in present:
            # Colored identity marks need enough distinction from the actual white/pale map background.
            if min(contrast(p['color'],bg) for bg in ('#ffffff','#fbfcff'))<3:
                issue('IDENTITY_LOW_CONTRAST',where+'/'+p['character_id'],'Identity mark has less than 3:1 contrast to map background; manual correction/review required',True)
        pairs=len(present)*(len(present)-1)//2
        pair_checks+=pairs
        if pair_checks>100000:
            issue('IDENTITY_PAIR_LIMIT',where,'At most 100000 co-present identity pair checks per build'); break
        for a,b in itertools.combinations(present,2):
            ca,cb=a['color'].lower(),b['color'].lower()
            pair=where+'/'+a['character_id']+'/'+b['character_id']
            if ca==cb and a['marker_shape']==b['marker_shape']:
                issue('IDENTITY_VISUAL_COLLISION',pair,'Co-present characters share color and marker shape; differing route styles cannot disambiguate entry/exit/static views')
            elif ca==cb:
                issue('IDENTITY_SHARED_COLOR',pair,'Shared color uses distinct marker shape; verify final-size and grayscale readability',True)
            elif math.dist(rgb(ca),rgb(cb))<.16:
                issue('IDENTITY_NEAR_COLOR',pair,'Colors are close under a simple RGB heuristic; verify visual discrimination (not a color-vision certification)',True)
    report['status']='complete' if not report['errors'] else 'blocked'
    return report
