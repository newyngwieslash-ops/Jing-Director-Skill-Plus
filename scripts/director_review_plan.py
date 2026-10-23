"""Review-only, no-cut windows. Never an input to production frame jobs/compiler."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation
import json

from director_core import ContractError, digest, validate

TOL = Decimal('0.000000001')
# Capacity limits protect offline review tools, not a minimum source duration.
# Larger projects require explicitly scoped contracts, never automatic cuts.
MAX_WINDOWS = 10000
MAX_SEGMENTS = 10000


def _decimal(value):
    if isinstance(value, bool):
        raise ContractError('Review times must be finite numbers, not booleans')
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ContractError('Review times must be finite numbers') from None
    if not result.is_finite():
        raise ContractError('Review times must be finite numbers')
    return result


def _number(value):
    return int(value) if value == value.to_integral_value() else float(value)


def _metadata(shot, start, end, duration):
    result = {}
    frames = []
    for frame in shot.get('keyframes', []):
        at = _decimal(frame['time_sec'])
        if start <= at < end or (end == duration and at == duration):
            frames.append({**deepcopy(frame), 'context_only': False})
    result['keyframes'] = frames
    result['frame_status'] = ('has_generated_keyframes' if any(f.get('image_path') for f in frames)
                              else 'no_generated_keyframes_in_window')
    for field in ('beats', 'dialogue'):
        items = []
        for index, item in enumerate(shot.get(field, [])):
            a, z = _decimal(item['start_sec']), _decimal(item['end_sec'])
            if a < end and z > start:
                items.append({'source_index': index,
                              'source_item_id': item.get('id', f"{shot['shot_id']}:{field}:{index}"),
                              'original': deepcopy(item),
                              'overlap_start_sec': _number(max(start, a)),
                              'overlap_end_sec': _number(min(end, z)),
                              'continues_across_windows': a < start or z > end})
        result[field] = items
    return result


def _segment(shot, index, count, start, end):
    duration = _decimal(shot['duration_sec'])
    beat_ends = {_decimal(b['end_sec']) for b in shot['beats']}
    segment = {'source_shot_id': shot['shot_id'], 'source_shot_no': shot['source_shot_no'],
               'review_start_sec': _number(start), 'review_end_sec': _number(end),
               'original_shot_duration_sec': shot['duration_sec'],
               'duration_sec': _number(end - start),
               'continues_same_shot': start > 0 or end < duration,
               'cut_before': start == 0 and index > 0,
               'cut_after': end == duration and index < count - 1,
               'boundary_end_kind': ('shot_end' if end == duration else
                                     'beat_endpoint' if end in beat_ends else 'review_only')}
    if 'source_span_sec' in shot:
        segment['source_span_sec'] = deepcopy(shot['source_span_sec'])
        offset = _decimal(shot['source_span_sec'][0])
        segment['source_time_start_sec'] = _number(offset + start)
        segment['source_time_end_sec'] = _number(offset + end)
    segment.update(_metadata(shot, start, end, duration))
    return segment


def _auto_windows(shots, cap):
    # Even an ideal packing cannot fit more duration than this budget. Check
    # before iteration so tiny positive caps/huge durations fail immediately.
    if sum((_decimal(s['duration_sec']) for s in shots), Decimal(0)) > cap * MAX_WINDOWS + TOL:
        raise ContractError(f'Review plan exceeds capacity of {MAX_WINDOWS} windows')
    if len(shots) > MAX_SEGMENTS:
        raise ContractError(f'Review plan exceeds capacity of {MAX_SEGMENTS} segments')
    windows, pending, total, scene = [], [], Decimal(0), None
    segment_count = 0
    def check_budget():
        if len(windows) >= MAX_WINDOWS or segment_count >= MAX_SEGMENTS:
            raise ContractError(f'Review plan exceeds capacity ({MAX_WINDOWS} windows / {MAX_SEGMENTS} segments)')
    def flush():
        nonlocal pending, total
        if pending:
            windows.append({'segments': pending})
            pending, total = [], Decimal(0)
    for shot in shots:
        duration = _decimal(shot['duration_sec'])
        sid = shot['shot_id']
        if duration > cap + TOL:
            flush()
            start = Decimal(0)
            while start < duration:
                limit = min(start + cap, duration)
                if duration - limit <= TOL:
                    end = duration
                else:
                    ends = [_decimal(b['end_sec']) for b in shot['beats']]
                    candidates = [t for t in ends if start < t <= limit]
                    end = max(candidates) if candidates else limit
                check_budget()
                segment_count += 1
                windows.append({'segments': [{'source_shot_id': sid,
                    'review_start_sec': _number(start), 'review_end_sec': _number(end)}]})
                start = end
            scene = None
        else:
            if pending and (scene != shot['scene_id'] or total + duration > cap + TOL):
                flush()
            scene = shot['scene_id']
            check_budget()
            segment_count += 1
            pending.append({'source_shot_id': sid, 'review_start_sec': 0,
                            'review_end_sec': _number(duration)})
            total += duration
    flush()
    return windows


def plan_review(doc, windows=None):
    """Validate a contract and derive canonical review-only windows without mutation.

    Explicit windows are a list of {segments:[{source_shot_id, review_start_sec,
    review_end_sec}]} or a review-plan object. Metadata is always re-derived; caller
    metadata cannot invent frames, cuts, dialogue timing, or approval status.
    Capacity is limited to 10,000 windows and 10,000 segments; exceeding it
    fails rather than changing any source duration or making production cuts.
    """
    report = validate(doc)
    if not report['ok']:
        raise ContractError(json.dumps(report, ensure_ascii=False))
    contract_hash = digest(doc)
    cap = _decimal(doc['policy']['board_max_duration_sec'])
    shots = doc['shots']
    if isinstance(windows, dict):
        if windows.get('schema_version', 'review-plan-1') != 'review-plan-1':
            raise ContractError('Unknown review plan schema')
        if windows.get('contract_sha256', contract_hash) != contract_hash:
            raise ContractError('Review plan contract hash is stale')
        windows = windows.get('windows')
        if windows is None:
            raise ContractError('Explicit review plan requires windows')
    if windows is None:
        windows = _auto_windows(shots, cap)
    if not isinstance(windows, list) or not windows:
        raise ContractError('Review windows must be a nonempty array')
    if len(windows) > MAX_WINDOWS:
        raise ContractError(f'Review plan exceeds capacity of {MAX_WINDOWS} windows')
    segment_count = 0
    for window in windows:
        if isinstance(window, dict) and isinstance(window.get('segments'), list):
            segment_count += len(window['segments'])
            if segment_count > MAX_SEGMENTS:
                raise ContractError(f'Review plan exceeds capacity of {MAX_SEGMENTS} segments')
    output, shot_index, expected, total = [], 0, Decimal(0), Decimal(0)
    for window in windows:
        if not isinstance(window, dict) or not isinstance(window.get('segments'), list) or not window['segments']:
            raise ContractError('Each review window requires nonempty segments')
        segments, window_total, scene = [], Decimal(0), None
        for item in window['segments']:
            if not isinstance(item, dict) or shot_index >= len(shots):
                raise ContractError('Unexpected or duplicate review segment')
            shot = shots[shot_index]
            if item.get('source_shot_id') != shot['shot_id']:
                raise ContractError('Review windows must cover every shot once, in contract order')
            start = _decimal(item.get('review_start_sec'))
            end = _decimal(item.get('review_end_sec'))
            duration = _decimal(shot['duration_sec'])
            if abs(start - expected) > TOL:
                raise ContractError('Review windows have a gap, overlap, or reverse order')
            start = expected
            if abs(end - duration) <= TOL:
                end = duration
            if start < 0 or end <= start or end > duration or end - start > cap + TOL:
                raise ContractError('Review segment is empty, outside shot, or exceeds cap')
            if scene is not None and scene != shot['scene_id']:
                raise ContractError('Review windows cannot cross scene boundaries')
            scene = shot['scene_id']
            if 'scene_id' in window and window['scene_id'] != scene:
                raise ContractError('Review window scene does not match contract')
            segments.append(_segment(shot, shot_index, len(shots), start, end))
            window_total += end - start
            expected = end
            if end == duration:
                shot_index += 1
                expected = Decimal(0)
        if window_total > cap + TOL:
            raise ContractError('Review window total exceeds cap')
        if 'duration_sec' in window and abs(_decimal(window['duration_sec']) - window_total) > TOL:
            raise ContractError('Review window duration disagrees with its segments')
        number = len(output) + 1
        output.append({'window_id': f'RW-{number:03d}', 'board_id': f'EB-{number:03d}',
                       'scene_id': scene, 'duration_sec': _number(window_total), 'segments': segments})
        total += window_total
    if shot_index != len(shots) or expected:
        raise ContractError('Review windows do not cover the complete contract')
    return {'schema_version': 'review-plan-1', 'contract_sha256': contract_hash,
            'board_canvas_aspect_ratio': '16:9', 'total_duration_sec': _number(total),
            'windows': output, 'status': 'planned_not_visually_verified',
            'purpose': 'review_only_not_production_cuts'}
