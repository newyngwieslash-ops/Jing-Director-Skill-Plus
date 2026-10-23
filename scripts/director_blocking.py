"""Source-bound blocking sidecar: deterministic SVG, never automatic story approval."""
from __future__ import annotations
import argparse
from collections import Counter
from html import escape
import json
import math
from pathlib import Path
import re
import sys
import textwrap

from director_core import ContractError, EPS, digest, load_json, num, text, validate


def same_point(a, b):
    return all(abs(x - y) <= EPS for x, y in zip(a, b))


def _validate_blocking_geometry(spec, contract):
    report = dict(ok=False, errors=[], warnings=[], source_sha256=None, spec_sha256=None,
                  review_status='needs_manual_review', collision_check='centerline_approximation')
    def issue(code, where, message, warning=False):
        report['warnings' if warning else 'errors'].append(dict(code=code, where=where, message=message))
    def objects(value, where):
        if not isinstance(value, list) or any(not isinstance(v, dict) for v in value):
            issue('TYPE', where, 'Expected array of objects'); return []
        return value
    def indexed(items, key, where):
        result = {}
        for item in items:
            ident = item.get(key)
            if not text(ident) or ident in result:
                issue('ID', where, f'Missing or duplicate {key}'); continue
            result[ident] = item
        return result
    try:
        report['source_sha256'] = digest(contract)
        report['spec_sha256'] = digest(spec)
    except (TypeError, ValueError, OverflowError):
        issue('JSON', '$', 'Only finite JSON values are supported')
        return report
    try:
        base = validate(contract, stage='plan')
    except (TypeError, ValueError, KeyError, AttributeError):
        issue('CONTRACT', '$', 'Malformed source contract'); return report
    if not base['ok']:
        issue('CONTRACT', '$', 'Source contract must pass plan validation')
        report['errors'].extend(base['errors']); return report
    if not isinstance(spec, dict):
        issue('TYPE', '$', 'Expected object'); return report
    if spec.get('schema_version') != '1.0': issue('VERSION', '$', 'Expected blocking schema_version 1.0')
    if spec.get('contract_sha256') != report['source_sha256']:
        issue('SOURCE_HASH', '$', 'Contract changed; revise the blocking sidecar')
    locations = indexed(objects(spec.get('locations'), 'locations'), 'id', 'locations')
    cast = indexed(objects(spec.get('cast'), 'cast'), 'id', 'cast')
    scenes = objects(spec.get('scenes'), 'scenes')
    scene_map = indexed(scenes, 'scene_id', 'scenes')
    for cid, person in cast.items():
        if not text(person.get('name')) or not isinstance(person.get('color'), str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', person['color']):
            issue('CAST', cid, 'Name and six-digit hex color required')
    def point(value, loc, where):
        if not isinstance(value, (list, tuple)) or len(value) != 2 or not all(num(v) for v in value):
            issue('POINT', where, 'Expected two finite coordinates'); return False
        bounds = loc['bounds']; x, y = value
        if not (bounds['x'] <= x <= bounds['x'] + bounds['w'] and bounds['y'] <= y <= bounds['y'] + bounds['h']):
            issue('BOUNDS', where, 'Point outside location bounds'); return False
        return True
    for lid, loc in locations.items():
        if not text(loc.get('name')) or not text(loc.get('basis')):
            issue('LOCATION', lid, 'Location name and measurement/estimate basis required')
        if (loc.get('coordinate_mode'), loc.get('units')) not in [('schematic', 'relative'), ('measured', 'm')]:
            issue('UNITS', lid, 'Use schematic/relative or measured/m')
        b = loc.get('bounds')
        if not isinstance(b, dict) or any(not num(b.get(k)) for k in ['x', 'y', 'w', 'h']) or b.get('w', 0) <= 0 or b.get('h', 0) <= 0:
            issue('BOUNDS', lid, 'Finite bounds with positive width and height required'); continue
        landmarks = objects(loc.get('landmarks'), lid + '.landmarks')
        indexed(landmarks, 'id', lid + '.landmarks')
        for mark in landmarks:
            if not text(mark.get('label')) or not isinstance(mark.get('blocking'), bool) or any(not num(mark.get(k)) for k in ['x', 'y', 'w', 'h']) or mark.get('w', 0) <= 0 or mark.get('h', 0) <= 0:
                issue('LANDMARK', lid, 'Named rectangle with positive size and explicit blocking flag required'); continue
            point([mark['x'] - mark['w'] / 2, mark['y'] - mark['h'] / 2], loc, lid)
            point([mark['x'] + mark['w'] / 2, mark['y'] + mark['h'] / 2], loc, lid)
        walls = loc.get('walls')
        if not isinstance(walls, list): issue('WALL', lid, 'Expected wall segment array'); continue
        for wall in walls:
            if not isinstance(wall, list) or len(wall) != 2: issue('WALL', lid, 'Expected two endpoints'); continue
            for p in wall: point(p, loc, lid)
    # Only inspect dependent coordinates after the map itself is valid.
    if report['errors']: return report
    source_shots = {s['source_shot_no']: s for s in contract['source_shots']}
    expected = {s['shot_id']: s for s in contract['shots']}
    expected_scenes = list(dict.fromkeys(s['scene_id'] for s in contract['shots']))
    if list(scene_map) != expected_scenes:
        issue('SCENE_COVERAGE', 'scenes', 'Cover each scene once, in first source appearance order')
    observed = []
    for scene in scenes:
        sid = scene['scene_id']; lid = scene.get('location_id')
        if not isinstance(lid, str) or lid not in locations:
            issue('LOCATION_REF', sid, 'Unknown location'); continue
        loc = locations[lid]
        ids = scene.get('cast_ids')
        if not isinstance(ids, list) or any(not isinstance(i, str) or i not in cast for i in ids) or len(set(ids)) != len(ids):
            issue('CAST_IDS', sid, 'Unique known scene cast IDs required'); continue
        shots = objects(scene.get('shots'), sid + '.shots')
        valid_shots = []
        for shot in shots:
            shid = shot.get('shot_id')
            if not isinstance(shid, str) or shid not in expected:
                issue('SHOT_REF', sid, 'Unknown shot ID'); continue
            observed.append(shid); valid_shots.append(shid)
            original = expected[shid]; where = f'{sid}/{shid}'
            if original['scene_id'] != sid or shot.get('source_shot_no') != original['source_shot_no'] or not num(shot.get('duration_sec')) or shot['duration_sec'] != original['duration_sec']:
                issue('SHOT_BINDING', where, 'Scene, original shot number and duration must exactly match the contract')
            evidence = objects(shot.get('evidence'), where + '.evidence')
            if not evidence: issue('EVIDENCE', where, 'At least one source excerpt required')
            source = source_shots[original['source_shot_no']]
            for ref in evidence:
                field, quote = ref.get('field'), ref.get('quote')
                if field not in ('action', 'notes', 'narrative_intent') or not text(quote) or not isinstance(source.get(field), str) or quote not in source[field]:
                    issue('EVIDENCE', where, 'Quote must be a nonempty exact excerpt of this original shot field')
            transition = shot.get('transition')
            if transition is not None:
                if not isinstance(transition, dict) or transition.get('kind') not in ('time_jump', 'scene_return') or not text(transition.get('evidence')):
                    issue('TRANSITION', where, 'Transition requires kind and source explanation')
                else: issue('TRANSITION_REVIEW', where, 'Transition evidence needs manual source review: ' + transition['evidence'], True)
            chars = indexed(objects(shot.get('characters'), where + '.characters'), 'id', where)
            if set(chars) != set(ids): issue('CAST_COVERAGE', where, 'Every scene cast member must have entry and exit states, including offscreen')
            for cid, char in chars.items():
                for phase in ('entry', 'exit'):
                    state = char.get(phase)
                    if not isinstance(state, dict): issue('STATE', where, f'{cid}/{phase} must be an object'); continue
                    point([state.get('x'), state.get('y')], loc, where)
                    if not num(state.get('facing_deg')) or state.get('visibility') not in ('in_frame', 'offscreen'):
                        issue('STATE', where, 'Finite facing angle and explicit visibility required')
            cameras = objects(shot.get('cameras'), where + '.cameras')
            indexed(cameras, 'id', where + '.cameras')
            for cam in cameras:
                point([cam.get('x'), cam.get('y')], loc, where)
                if not num(cam.get('facing_deg')): issue('CAMERA', where, 'Finite facing angle required')
            trajectories = objects(shot.get('trajectories'), where + '.trajectories')
            for route in trajectories:
                who, bi = route.get('who'), route.get('beat_index')
                if not isinstance(who, str) or who not in chars: issue('ROUTE_CAST', where, 'Unknown moving character')
                a, z = route.get('start_sec'), route.get('end_sec')
                if not isinstance(bi, int) or isinstance(bi, bool) or not 0 <= bi < len(original['beats']):
                    issue('BEAT', where, 'Valid integer beat_index required')
                else:
                    beat = original['beats'][bi]
                    if not num(a) or not num(z) or not beat['start_sec'] <= a < z <= beat['end_sec']:
                        issue('ROUTE_TIME', where, 'Trajectory must advance within its cited beat')
                if not text(route.get('reason')): issue('ROUTE_REASON', where, 'Source-linked movement explanation required')
                points = route.get('points')
                if not isinstance(points, list) or len(points) < 2: issue('ROUTE_POINTS', where, 'At least two points required')
                else:
                    for p in points: point(p, loc, where)
            if report['errors']: continue
            for cid, char in chars.items():
                routes = sorted((r for r in trajectories if r['who'] == cid), key=lambda r: r['start_sec'])
                current = [char['entry']['x'], char['entry']['y']]; end = 0
                for route in routes:
                    if route['start_sec'] < end: issue('ROUTE_OVERLAP', where, f'{cid}: overlapping trajectories')
                    if not same_point(current, route['points'][0]): issue('ROUTE_CHAIN', where, f'{cid}: disconnected route start')
                    current = route['points'][-1]; end = route['end_sec']
                    if crosses_obstacle(route['points'], loc): issue('OBSTACLE_REVIEW', where, f'{cid}: path centerline touches a wall or blocking landmark; review contact/clearance', True)
                if not same_point(current, [char['exit']['x'], char['exit']['y']]):
                    issue('ROUTE_END', where, f'{cid}: routes must connect entry to exit; no silent displacement')
        if valid_shots != [s['shot_id'] for s in contract['shots'] if s['scene_id'] == sid]:
            issue('SHOT_ORDER', sid, 'Scene shots must preserve contract order with no omissions or duplicates')
    if Counter(observed) != Counter(expected.keys()): issue('SHOT_COVERAGE', 'scenes', 'Every contract shot must occur exactly once')
    if report['errors']: return report
    rendered_shots = {s['shot_id']: s for scene in scenes for s in scene['shots']}
    seen_scenes = set()
    for i, original in enumerate(contract['shots']):
        sid = original['scene_id']; current = rendered_shots[original['shot_id']]
        previous = contract['shots'][i - 1] if i else None
        if previous and previous['scene_id'] == sid:
            prior = {c['id']: c['exit'] for c in rendered_shots[previous['shot_id']]['characters']}
            for char in current['characters']:
                a, b = prior[char['id']], char['entry']
                angle = abs((a['facing_deg'] - b['facing_deg'] + 180) % 360 - 180)
                if not same_point([a['x'], a['y']], [b['x'], b['y']]) or angle > EPS:
                    if current.get('transition') is None: issue('CONTINUITY', original['shot_id'], f"{char['id']}: previous exit differs from entry without an explained transition")
        elif sid in seen_scenes:
            issue('SCENE_RETURN_REVIEW', original['shot_id'], 'Scene returns after another scene; review elapsed time and blocking against the earlier exit', True)
        seen_scenes.add(sid)
    issue('MANUAL_REVIEW', '$', 'Source excerpts prove traceability only. Story relevance, cast completeness, sightlines, camera axis, offscreen logic, and rendered diagram readability require manual review. Collision checks use centerlines only; body clearance, speed and 3D geometry are not simulated.', True)
    report['ok'] = not report['errors']
    return report


def validate_blocking(spec, contract, roster=None, identity_registry=None):
    """Return a fail-closed report even for malformed external JSON shapes."""
    try:
        return _validate_blocking_complete(spec, contract, roster, identity_registry=identity_registry)
    except (TypeError, ValueError, KeyError, AttributeError, OverflowError) as exc:
        return dict(ok=False, errors=[dict(code='BLOCKING_INPUT', where='$',
                    message='Malformed blocking, contract or roster input: ' + str(exc))],
                    warnings=[], source_sha256=None, spec_sha256=None,
                    review_status='needs_manual_review', collision_check='centerline_approximation',
                    coverage=dict(schema_version='1.0', status='blocked', classification_status='blocked',
                                  contract_sha256=None, roster_sha256=None, expected_scene_ids=[],
                                  actual_scene_ids=[], scenes=[], review_status='needs_manual_review'))


def _validate_blocking_complete(spec, contract, roster=None, identity_registry=None):
    """Strict 4.4 gate. Classification is declared evidence, never semantic approval.

    A roster is deliberately separate from the blocking spec, so deleting a person
    from both the scene and its shots cannot make the completeness check pass.
    """
    report = _validate_blocking_geometry(spec, contract)
    coverage = dict(schema_version='1.0', status='blocked', contract_sha256=report['source_sha256'],
                    roster_sha256=None, expected_scene_ids=[], actual_scene_ids=[], scenes=[],
                    classification_status='blocked', review_status='needs_manual_review')
    report['coverage'] = coverage
    def issue(code, where, message):
        report['errors'].append(dict(code=code, where=where, message=message))
    def array(value):
        return value if isinstance(value, list) else []
    def records(value):
        return [v for v in array(value) if isinstance(v, dict)]
    def ids(value):
        return isinstance(value, list) and all(text(i) for i in value) and len(set(value)) == len(value)
    def count(value):
        return isinstance(value, int) and not isinstance(value, bool) and value >= 0
    def roster_keys(value, allowed, where):
        # Match the standalone schema: misspellings and invented approval fields
        # must not silently pass the strict gate.
        extra = set(value) - set(allowed)
        if extra: issue('ROSTER_FIELDS', where, 'Unknown roster fields: ' + ', '.join(sorted(extra)))
    def valid_expansion(item):
        members, n, kind = item.get('member_ids'), item.get('expected_count'), item.get('kind')
        if not ids(members) or not count(n) or n != len(members): return False
        return ((kind == 'individual' and n == 1) or (kind == 'group' and n >= 2)
                or (kind == 'non_character' and n == 0))
    if not isinstance(contract, dict) or not isinstance(spec, dict) or not isinstance(contract.get('shots'), list):
        report['ok'] = False
        return report
    shots = records(contract['shots'])
    source = {s.get('source_shot_no'): s for s in records(contract.get('source_shots'))}
    subjects = {i for s in shots for i in array(s.get('subjects')) if isinstance(i, str)}
    scene_ids = list(dict.fromkeys(s.get('scene_id') for s in shots if text(s.get('scene_id'))))
    coverage['expected_scene_ids'] = scene_ids
    scene_records = records(spec.get('scenes'))
    coverage['actual_scene_ids'] = [s.get('scene_id') for s in scene_records]
    scene_map = {s.get('scene_id'): s for s in scene_records if text(s.get('scene_id'))}
    roster = roster if isinstance(roster, dict) else None
    classifications = {}
    roster_scenes = {}
    classification_start = len(report['errors'])
    if roster is None:
        issue('ROSTER_REQUIRED', 'roster', 'Strict completeness requires a source-bound typed roster; legacy geometry alone is not completeness validation')
    else:
        roster_keys(roster, ('schema_version', 'contract_sha256', 'subjects', 'scenes'), 'roster')
        try: coverage['roster_sha256'] = digest(roster)
        except (TypeError, ValueError, OverflowError): issue('ROSTER_JSON', 'roster', 'Roster must contain finite JSON values')
        if roster.get('schema_version') != '1.0': issue('ROSTER_VERSION', 'roster', 'Expected roster schema_version 1.0')
        if roster.get('contract_sha256') != report['source_sha256']:
            issue('ROSTER_SOURCE_HASH', 'roster', 'Roster must bind to the exact source contract')
        if not isinstance(roster.get('subjects'), list): issue('ROSTER_SUBJECTS', 'roster', 'Explicit subject classification array required, including empty array')
        owners = {}
        for item in array(roster.get('subjects')):
            if not isinstance(item, dict): issue('ROSTER_TYPE', 'roster.subjects', 'Expected subject object'); continue
            sid = item.get('subject_id'); where = 'roster.subjects/' + str(sid)
            roster_keys(item, ('subject_id', 'kind', 'member_ids', 'expected_count', 'evidence'), where)
            if not text(sid) or sid in classifications:
                issue('ROSTER_SUBJECT_ID', where, 'Unique nonempty subject ID required'); continue
            classifications[sid] = item
            kind, members, expected_count = item.get('kind'), item.get('member_ids'), item.get('expected_count')
            if kind not in ('individual', 'group', 'non_character'):
                issue('ROSTER_CLASSIFICATION', where, 'Explicit individual, group or non_character classification required')
            if not ids(members) or not count(expected_count) or expected_count != len(array(members)):
                issue('ROSTER_MEMBER_COUNT', where, 'Unique member IDs and explicit matching nonnegative expected_count required')
            if kind == 'individual' and expected_count != 1: issue('ROSTER_INDIVIDUAL', where, 'Individual must expand to exactly one person')
            if kind == 'group' and (not count(expected_count) or expected_count < 2): issue('ROSTER_GROUP', where, 'Group must explicitly expand to at least two individual IDs')
            if kind == 'non_character' and (expected_count != 0 or members != []): issue('ROSTER_NON_CHARACTER', where, 'Non-character must explicitly declare zero people')
            for member in array(members):
                if not isinstance(member, str): continue
                if member in owners: issue('ROSTER_MEMBER_DUPLICATE', where, 'Individual ID is already owned by subject ' + owners[member])
                owners[member] = sid
            evidence = item.get('evidence')
            if not isinstance(evidence, list) or not evidence: issue('ROSTER_EVIDENCE', where, 'Classification requires raw source evidence')
            relevant = {s.get('source_shot_no') for s in shots if sid in array(s.get('subjects'))}
            for ref in array(evidence):
                if not isinstance(ref, dict): issue('ROSTER_EVIDENCE', where, 'Expected evidence object'); continue
                roster_keys(ref, ('source_shot_no', 'field', 'quote'), where + '.evidence')
                original = source.get(ref.get('source_shot_no'), {})
                field, quote = ref.get('field'), ref.get('quote')
                if ref.get('source_shot_no') not in relevant or field not in ('action', 'notes', 'narrative_intent') or not text(quote) or not isinstance(original.get(field), str) or quote not in original[field]:
                    issue('ROSTER_EVIDENCE', where, 'Quote must exactly match a relevant original shot field; existence is not semantic authentication')
        if set(classifications) != subjects:
            issue('ROSTER_SUBJECT_COVERAGE', 'roster.subjects', 'Classify every contract subject exactly once; missing=' + str(sorted(subjects-set(classifications))) + '; extra=' + str(sorted(set(classifications)-subjects)))
        if not isinstance(roster.get('scenes'), list): issue('ROSTER_SCENES', 'roster', 'Explicit scene declarations required')
        for scene in array(roster.get('scenes')):
            if not isinstance(scene, dict): issue('ROSTER_TYPE', 'roster.scenes', 'Expected scene object'); continue
            sid = scene.get('scene_id')
            roster_keys(scene, ('scene_id', 'cast_ids', 'expected_count'), 'roster.scenes/' + str(sid))
            if not text(sid) or sid in roster_scenes: issue('ROSTER_SCENE_ID', 'roster.scenes', 'Unique scene IDs required'); continue
            roster_scenes[sid] = scene
        if list(roster_scenes) != scene_ids: issue('ROSTER_SCENE_COVERAGE', 'roster.scenes', 'Declare every scene in source order, including explicit zero-person scenes')
    classification_ok = len(report['errors']) == classification_start and roster is not None
    coverage['classification_status'] = 'complete' if classification_ok else 'blocked'
    coverage['unclassified_subject_ids'] = sorted(subjects - set(classifications))
    all_expected = set()
    for sid in scene_ids:
        original_shots = [s for s in shots if s.get('scene_id') == sid]
        scene_subjects = {i for s in original_shots for i in array(s.get('subjects')) if isinstance(i, str)}
        expanded = sorted({m for subject in scene_subjects for m in array(classifications.get(subject, {}).get('member_ids')) if isinstance(m, str)})
        all_expected.update(expanded)
        declared = roster_scenes.get(sid, {})
        if not ids(declared.get('cast_ids')) or set(array(declared.get('cast_ids'))) != set(expanded) or not count(declared.get('expected_count')) or declared.get('expected_count') != len(expanded):
            issue('ROSTER_SCENE_MEMBERS', sid, 'Declare exactly the expanded scene members and explicit matching expected_count, including zero')
        actual_scene = scene_map.get(sid, {})
        actual_ids = array(actual_scene.get('cast_ids'))
        scene_start = len(report['errors'])
        if not ids(actual_scene.get('cast_ids')) or set(actual_ids) != set(expanded):
            issue('SCENE_CAST_COVERAGE', sid, 'Scene cast must exactly match source roster expansion')
        unresolved = sorted(subject for subject in scene_subjects if not valid_expansion(classifications.get(subject, {})))
        row = dict(scene_id=sid, subject_ids=sorted(scene_subjects), unresolved_subject_ids=unresolved, expected_count=None if unresolved else len(expanded), expected_cast_ids=expanded,
                   actual_cast_ids=actual_ids, expected_shot_ids=[s.get('shot_id') for s in original_shots],
                   actual_shot_ids=[s.get('shot_id') for s in records(actual_scene.get('shots'))], shots=[], status='blocked')
        actual_shots = {s.get('shot_id'): s for s in records(actual_scene.get('shots')) if text(s.get('shot_id'))}
        for shot in original_shots:
            shid = shot.get('shot_id'); actual = actual_shots.get(shid, {})
            chars = {c.get('id'): c for c in records(actual.get('characters')) if text(c.get('id'))}
            shot_start = len(report['errors'])
            if not actual: issue('SHOT_COVERAGE', sid + '/' + str(shid), 'Missing contract shot')
            if set(chars) != set(expanded): issue('SHOT_CAST_COVERAGE', str(shid), 'Every expanded scene member requires both states in every shot, including offscreen')
            states = []; path_coverage = []
            for cid in expanded:
                char = chars.get(cid, {})
                phases = {}
                for phase in ('entry', 'exit'):
                    state = char.get(phase)
                    good = isinstance(state, dict) and all(num(state.get(k)) for k in ('x', 'y', 'facing_deg')) and state.get('visibility') in ('in_frame', 'offscreen')
                    phases[phase] = dict(status='present' if good else 'missing_or_invalid', state=state)
                    if not good: issue('FRAME_COVERAGE', str(shid) + '/' + cid + '/' + phase, 'Complete explicit position, facing and visibility required')
                states.append(dict(id=cid, **phases))
                routes = [r for r in records(actual.get('trajectories')) if r.get('who') == cid]
                entry, end = char.get('entry'), char.get('exit')
                static = isinstance(entry, dict) and isinstance(end, dict) and all(num(s.get(k)) for s in (entry, end) for k in ('x', 'y')) and same_point([entry['x'], entry['y']], [end['x'], end['y']])
                path_status = 'routes_declared' if routes else ('stationary' if static else 'missing')
                if path_status == 'missing': issue('PATH_COVERAGE', str(shid) + '/' + cid, 'Movement must have a trajectory; unchanged coordinates explicitly represent stationary blocking')
                path_coverage.append(dict(id=cid, status=path_status, trajectory_count=len(routes)))
            row['shots'].append(dict(shot_id=shid, source_shot_no=shot.get('source_shot_no'), expected_cast_ids=expanded,
                actual_cast_ids=list(chars), missing_cast_ids=sorted(set(expanded)-set(chars)), extra_cast_ids=sorted(set(chars)-set(expanded)),
                frame_states=states, path_coverage=path_coverage, status='complete' if classification_ok and len(report['errors']) == shot_start else 'blocked'))
        row['status'] = 'complete' if classification_ok and len(report['errors']) == scene_start and row['expected_shot_ids'] == row['actual_shot_ids'] else 'blocked'
        coverage['scenes'].append(row)
    cast_ids = [c.get('id') for c in records(spec.get('cast'))]
    if set(cast_ids) != all_expected: issue('GLOBAL_CAST_COVERAGE', 'cast', 'Global cast must exactly match expanded source roster individual IDs')
    from director_identity import validate_identity
    identity = validate_identity(spec, identity_registry)
    report['identity'] = identity
    report['errors'].extend(identity['errors']); report['warnings'].extend(identity['warnings'])
    coverage['identity_registry_sha256'] = identity['registry_sha256']
    coverage['identity_status'] = identity['status']
    report['ok'] = not report['errors']
    coverage['status'] = 'complete' if report['ok'] else 'blocked'
    if not report['ok']:
        # Geometry/continuity failures must not leave green shot rows in an invalid package.
        for scene in coverage['scenes']:
            scene['status'] = 'blocked'
            for shot in scene['shots']: shot['status'] = 'blocked'
    return report


def crosses_obstacle(points, location):
    # ponytail: centerline intersection only; add body radii only for surveyed staging needs.
    def cross(a, b, c): return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    def intersects(a, b, c, d):
        return (max(min(a[0], b[0]), min(c[0], d[0])) <= min(max(a[0], b[0]), max(c[0], d[0])) + EPS
            and max(min(a[1], b[1]), min(c[1], d[1])) <= min(max(a[1], b[1]), max(c[1], d[1])) + EPS
            and cross(a, b, c) * cross(a, b, d) <= EPS and cross(c, d, a) * cross(c, d, b) <= EPS)
    walls = list(location['walls'])
    for mark in location['landmarks']:
        if not mark['blocking']: continue
        x, y, w, h = (mark[k] for k in ('x', 'y', 'w', 'h'))
        x -= w / 2; y -= h / 2
        if any(x <= p[0] <= x + w and y <= p[1] <= y + h for p in points): return True
        corners = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
        walls.extend(zip(corners, corners[1:] + corners[:1]))
    return any(intersects(a, b, c, d) for a, b in zip(points, points[1:]) for c, d in walls)


def render_scene(scene, location, cast, kind):
    """Historical aggregate renderer, retired from the strict 4.4 publisher.

    New deliveries use director_blocking_output shared identity-aware geometry.
    """
    bounds = location['bounds']; panel_w = 600
    panel_h = max(280, min(1000, panel_w * bounds['h'] / bounds['w']))
    columns = 2 if kind == 'positions' else 1
    width = columns * (panel_w + 36) + 40
    parts = []
    def label(x, y, value, size=14, color='#172033'):
        parts.append(f'<text x="{x:g}" y="{y:g}" font-size="{size}" fill="{color}">{escape(str(value))}</text>')
    def wrapped(y, value, color='#172033'):
        for line in textwrap.wrap(str(value), max(24, int((width - 80) / 14)), replace_whitespace=True) or ['']:
            label(24, y, line, color=color); y += 22
        return y
    y = 32
    y = wrapped(y, f"{scene['scene_id']} / {location['name']} / {'角色站位图' if kind == 'positions' else '角色走位图'}")
    y = wrapped(y, f"{'示意坐标' if location['coordinate_mode'] == 'schematic' else '实测坐标'} ({location['units']})；依据：{location['basis']}")
    y = wrapped(y, 'needs_manual_review / 待人工审核：剧情关联、连续性及图面可读性。N 为图面北向；x 向右，y 向上；朝向 0°=东，90°=北。')
    y = wrapped(y, '图例：实心=入镜状态，空心=出镜状态，虚线圈=画外；箭头=移动方向；CAM=机位。')
    for cid in scene['cast_ids']:
        person = cast[cid]; y = wrapped(y, f"{cid}: {person['name']}", color=person['color'])
    for i, mark in enumerate(location['landmarks'], 1):
        y = wrapped(y, f"地标 {i}: {mark['label']} ({mark['id']})")
    if not scene['cast_ids']: y = wrapped(y, '空镜 / 无角色')
    for shot in scene['shots']:
        y += 16
        y = wrapped(y, f"原镜 {shot['source_shot_no']} | {shot['shot_id']} | {shot['duration_sec']:g}s")
        for ref in shot['evidence']: y = wrapped(y, f"依据 [{ref['field']}] {ref['quote']}")
        if shot.get('transition'): y = wrapped(y, f"转场待审 [{shot['transition']['kind']}] {shot['transition']['evidence']}")
        top = y + 24
        scale = min((panel_w - 72) / bounds['w'], (panel_h - 72) / bounds['h'])
        for col in range(columns):
            left = 24 + col * (panel_w + 36)
            ox = left + (panel_w - bounds['w'] * scale) / 2
            oy = top + (panel_h - bounds['h'] * scale) / 2
            def xy(x, yy): return ox + (x - bounds['x']) * scale, oy + (bounds['y'] + bounds['h'] - yy) * scale
            label(left, top - 10, ('ENTRY / 起始站位' if col == 0 else 'EXIT / 结束站位') if kind == 'positions' else 'MOVEMENT / 全镜走位')
            parts.append(f'<rect x="{ox:g}" y="{oy:g}" width="{bounds["w"] * scale:g}" height="{bounds["h"] * scale:g}" fill="#fbfcff" stroke="#6b7280"/>')
            label(left + panel_w - 28, top + 12, 'N ↑')
            for mark_index, mark in enumerate(location['landmarks'], 1):
                px, py = xy(mark['x'] - mark['w'] / 2, mark['y'] + mark['h'] / 2)
                parts.append(f'<rect x="{px:g}" y="{py:g}" width="{mark["w"] * scale:g}" height="{mark["h"] * scale:g}" fill="#dce2eb" stroke="#657086"/>')
                label(px + 3, py + 15, str(mark_index), 12)
            for wall in location['walls']:
                a, b = xy(*wall[0]), xy(*wall[1])
                parts.append(f'<path d="M {a[0]:g},{a[1]:g} L {b[0]:g},{b[1]:g}" stroke="#172033" stroke-width="4"/>')
            def token(state, ident, color, hollow=False, camera=False):
                px, py = xy(state['x'], state['y']); rad = math.radians(state['facing_deg'] % 360)
                dash = ' stroke-dasharray="3 2"' if state.get('visibility') == 'offscreen' else ''
                parts.append(f'<circle cx="{px:g}" cy="{py:g}" r="9" fill="{"white" if hollow else color}" stroke="{color}" stroke-width="2"{dash}/>')
                parts.append(f'<path d="M {px:g},{py:g} l {19 * math.cos(rad):g},{-19 * math.sin(rad):g}" stroke="{color}" stroke-width="2" marker-end="url(#arrow)"/>')
                label(px + 12, py - 11 if not hollow else py + 22, ('CAM ' if camera else '') + ident, 12, color)
            if kind == 'movement':
                for route in shot['trajectories']:
                    points = ' '.join(f'{x:g},{yy:g}' for x, yy in (xy(*p) for p in route['points']))
                    color = cast[route['who']]['color']
                    parts.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="3" marker-mid="url(#arrow)" marker-end="url(#arrow)"/>')
                    px, py = xy(*route['points'][len(route['points']) // 2])
                    label(px + 8, py + 38, f"{route['start_sec']:g}–{route['end_sec']:g}s", 12, color)
            for char in shot['characters']:
                color = cast[char['id']]['color']
                if kind == 'positions': token(char['entry' if col == 0 else 'exit'], char['id'], color, col == 1)
                else:
                    token(char['entry'], char['id'], color)
                    token(char['exit'], char['id'], color, True)
            for cam in shot['cameras']: token(cam, cam['id'], '#4b5563', camera=True)
        y = top + panel_h + 24
        if kind == 'movement':
            for char in shot['characters']:
                routes = [r for r in shot['trajectories'] if r['who'] == char['id']]
                if not routes: y = wrapped(y, f"{char['id']}：原地无位移（可有朝向变化），0–{shot['duration_sec']:g}s")
                for route in routes: y = wrapped(y, f"{route['who']} / beat {route['beat_index']} / {route['start_sec']:g}–{route['end_sec']:g}s：{route['reason']}")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:g}" height="{y + 20:g}" viewBox="0 0 {width:g} {y + 20:g}" role="img">'
            '<title>场景角色站位与走位待审图</title><defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#475569"/></marker></defs>'
            '<rect width="100%" height="100%" fill="white"/><g font-family="Microsoft YaHei,Noto Sans CJK SC,sans-serif">' + ''.join(parts) + '</g></svg>')


def build(spec, contract, out_dir, overwrite=False, roster=None, font_path=None, identity_registry=None):
    from director_blocking_output import publish
    report = validate_blocking(spec, contract, roster, identity_registry=identity_registry)
    if not report['ok']:
        raise ContractError(json.dumps(report['errors'], ensure_ascii=False, allow_nan=False))
    return publish(spec, contract, roster, report, out_dir, render_scene, font_path, identity_registry=identity_registry)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('spec'); parser.add_argument('--contract', required=True)
    parser.add_argument('--roster', required=True); parser.add_argument('--font')
    parser.add_argument('--identity-registry', required=True)
    parser.add_argument('--out-dir', required=True); parser.add_argument('--overwrite', action='store_true')
    args = parser.parse_args()
    try:
        report = build(load_json(args.spec), load_json(args.contract), args.out_dir, args.overwrite, roster=load_json(args.roster), font_path=args.font, identity_registry=load_json(args.identity_registry))
    except (ContractError, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr); return 1
    print(json.dumps(report, ensure_ascii=False, indent=2)); return 0


if __name__ == '__main__':
    raise SystemExit(main())
