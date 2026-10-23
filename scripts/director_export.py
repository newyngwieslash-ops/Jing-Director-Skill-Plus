"""Deterministic canonical XLSX export from an independently retained ingest snapshot.

This preserves raw mapped cells when available, not the original workbook layout.
Legacy snapshots lacking raw cells can only preserve their normalized values.
A successful roundtrip is structural evidence, never human or visual approval.
"""
from __future__ import annotations

from decimal import Decimal
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET
import zipfile

from director_core import ContractError, digest, duration, ingest, load_json, map_headers, xlsx_tables

EXPORTER_VERSION = '1.0.0'
COLUMNS = [('source_shot_no', '镜号', 6), ('duration_sec', '时长', 14),
           ('angle', '摄影角度', 12), ('shot_size', '景别', 10),
           ('action', '画面内容', 50), ('scene', '场景', 14),
           ('sound', '声音', 40), ('notes', '备注', 25),
           ('narrative_intent', '叙事目的', 50)]
PROMPT = ('video_prompt', '视频提示词', 110)
NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
PKG = 'http://schemas.openxmlformats.org/package/2006/relationships'


def _xml(node):
    # XML parsers normalize literal CR; a character reference preserves original CRLF.
    return ET.tostring(node, encoding='utf-8', xml_declaration=True).replace(b'\r', b'&#13;')


def _safe_text(value, location):
    if not isinstance(value, str):
        raise ContractError(f'{location}: expected text, not {type(value).__name__}')
    if any(not (ch in '\t\n\r' or 0x20 <= ord(ch) <= 0xD7FF or
                0xE000 <= ord(ch) <= 0xFFFD or 0x10000 <= ord(ch) <= 0x10FFFF) for ch in value):
        raise ContractError(f'{location}: illegal XML character')
    # Excel interprets ST_Xstring escape tokens after XML decoding. Our existing
    # reader does not decode them; reject rather than claim a false roundtrip or
    # mutate source literals. Supporting these requires coordinated reader support.
    if re.search(r'_x[0-9a-f]{4}_', value, re.I):
        raise ContractError(f'{location}: reserved OOXML escape sequence _xHHHH_ is unsupported; source not modified')
    if len(value.encode('utf-16-le')) // 2 > 32767:
        raise ContractError(f'{location}: exceeds Excel 32767 UTF-16 code units; no truncation')
    return value


def _sheet_name(value):
    _safe_text(value, 'sheet name')
    value = re.sub(r'[\[\]:*?/\\]', '_', value).strip("'")[:31].strip("'")
    return value if value.strip() else '分镜表'


def _seconds(value):
    duration(value)  # Reject ambiguous, non-finite and non-positive values.
    return format(Decimal(str(duration(value))).normalize(), 'f')


def _prepare(source, report):
    if not isinstance(source, dict) or 'project' in source or not isinstance(source.get('shots'), list):
        raise ContractError('Expected an independent ingest source snapshot with shots; not a director contract')
    if not source['shots']:
        raise ContractError('Source snapshot has no shots')
    if len(source['shots']) > 99999:
        raise ContractError('Source exceeds roundtrip reader row limit')
    if not re.fullmatch(r'[a-f0-9]{64}', str(source.get('source_sha256', ''))):
        raise ContractError('Source snapshot requires original source_sha256')
    ignored = source.get('ignored_rows', [])
    if not isinstance(ignored, list) or any(not isinstance(r, dict) for r in ignored):
        raise ContractError('Source ignored_rows must be an array of objects')
    if any(r.get('reason') != 'explicit_total_row' for r in ignored):
        raise ContractError('Ignored source rows require an explicit lossless mapping before export')
    headers = source.get('headers', [])
    if not isinstance(headers, list) or any(not isinstance(h, str) for h in headers):
        raise ContractError('Source headers must be a list of strings')
    effective_headers = [h or f'column_{i + 1}' for i, h in enumerate(headers)]
    if len(set(effective_headers)) != len(effective_headers):
        raise ContractError('Duplicate source headers cannot be exported losslessly from raw_cells')
    mapped = map_headers(headers)
    if any(not isinstance(s, dict) for s in source['shots']):
        raise ContractError('Every source shot must be an object')
    include_prompt = 'video_prompt' in mapped or any(
        s.get('video_prompt') or ('video_prompt' in map_headers(list(s.get('raw_cells', {}))))
        for s in source['shots'] if isinstance(s.get('raw_cells', {}), dict))
    columns = COLUMNS + ([PROMPT] if include_prompt else [])
    rows = []
    unknown = {effective_headers[i]: {'column': effective_headers[i], 'nonempty_source_rows': []}
               for i in range(len(headers)) if i not in mapped.values()}
    normalized = []
    for index, shot in enumerate(source['shots']):
        if not isinstance(shot, dict):
            raise ContractError(f'Source shot {index + 1} must be an object')
        raw = shot.get('raw_cells', {})
        if not isinstance(raw, dict):
            raise ContractError(f'Source shot {index + 1}: raw_cells must be an object')
        if any(not isinstance(h, str) for h in raw):
            raise ContractError(f'Source shot {index + 1}: raw column names must be strings')
        if any(h not in raw for h in unknown):
            report['unmapped_columns'] = list(unknown.values())
            raise ContractError('Unmapped columns have missing original cells; cannot prove empty values')
        raw_headers = list(raw)
        raw_map = map_headers(raw_headers)
        for h, v in raw.items():
            if h not in [raw_headers[i] for i in raw_map.values()]:
                entry = unknown.setdefault(h, {'column': h, 'nonempty_source_rows': []})
                if v is not None and str(v) != '':
                    entry['nonempty_source_rows'].append(shot.get('source_row', index + 2))
        row = []
        for field, title, _ in columns:
            location = f'shot {shot.get("source_shot_no", index + 1)!r}, column {title}'
            value = shot.get(field, '')
            if field in raw_map:
                original = raw[raw_headers[raw_map[field]]]
                original = '' if original is None else original
                if field == 'duration_sec':
                    if duration(original) != duration(value):
                        raise ContractError(f'{location}: raw/normalized duration mismatch')
                    value = original if isinstance(original, str) else _seconds(original)
                else:
                    original = str(original)
                    if original.strip() != str(value).strip():
                        raise ContractError(f'{location}: raw/normalized text mismatch')
                    value = original
            else:
                normalized.append({'source_shot_index': index, 'field': field})
                if field == 'duration_sec':
                    value = _seconds(value)
            row.append(_safe_text(value, location))
        rows.append(row)
    report['unmapped_columns'] = list(unknown.values())
    report['normalized_fallback_fields'] = normalized
    if any(item['nonempty_source_rows'] for item in unknown.values()):
        raise ContractError('Nonempty unmapped custom columns require explicit mapping: ' + ', '.join(
            item['column'] for item in unknown.values() if item['nonempty_source_rows']))
    report['column_mapping'] = [{'field': k, 'header': h} for k, h, _ in columns]
    return columns, rows


def _workbook(path, columns, rows, sheet_name):
    workbook = ET.Element('workbook', xmlns=NS, attrib={'xmlns:r': REL})
    ET.SubElement(ET.SubElement(workbook, 'sheets'), 'sheet', name=sheet_name, sheetId='1', attrib={'r:id': 'rId1'})
    sheet = ET.Element('worksheet', xmlns=NS)
    view = ET.SubElement(ET.SubElement(sheet, 'sheetViews'), 'sheetView', workbookViewId='0')
    ET.SubElement(view, 'pane', ySplit='1', topLeftCell='A2', activePane='bottomLeft', state='frozen')
    widths = ET.SubElement(sheet, 'cols')
    for i, (_, _, width) in enumerate(columns, 1):
        ET.SubElement(widths, 'col', min=str(i), max=str(i), width=str(width), customWidth='1')
    data = ET.SubElement(sheet, 'sheetData')
    for ri, values in enumerate([[h for _, h, _ in columns]] + rows, 1):
        row = ET.SubElement(data, 'row', r=str(ri))
        for ci, value in enumerate(values):
            cell = ET.SubElement(row, 'c', r=f'{chr(65 + ci)}{ri}', t='inlineStr',
                                 s='1' if ri == 1 else ('2' if ci == 0 else '0'))
            ET.SubElement(ET.SubElement(cell, 'is'), 't', attrib={'xml:space': 'preserve'}).text = value
    ET.SubElement(sheet, 'autoFilter', ref=f'A1:{chr(64 + len(columns))}{len(rows) + 1}')
    styles = ET.Element('styleSheet', xmlns=NS)
    fonts = ET.SubElement(styles, 'fonts', count='2')
    for bold in (False, True):
        font = ET.SubElement(fonts, 'font')
        ET.SubElement(font, 'sz', val='11'); ET.SubElement(font, 'name', val='Calibri')
        if bold: ET.SubElement(font, 'b')
    fills = ET.SubElement(styles, 'fills', count='3')
    for pattern in ('none', 'gray125', 'solid'):
        fill = ET.SubElement(ET.SubElement(fills, 'fill'), 'patternFill', patternType=pattern)
        if pattern == 'solid': ET.SubElement(fill, 'fgColor', rgb='FFE7E6E6')
    border = ET.SubElement(ET.SubElement(styles, 'borders', count='1'), 'border')
    for edge in ('left', 'right', 'top', 'bottom'):
        ET.SubElement(ET.SubElement(border, edge, style='thin'), 'color', auto='1')
    ET.SubElement(border, 'diagonal')
    ET.SubElement(ET.SubElement(styles, 'cellStyleXfs', count='1'), 'xf', numFmtId='0', fontId='0', fillId='0', borderId='0')
    xfs = ET.SubElement(styles, 'cellXfs', count='3')
    for i in range(3):
        xf = ET.SubElement(xfs, 'xf', numFmtId='49', fontId='1' if i == 1 else '0',
                           fillId='2' if i == 1 else '0', borderId='0', xfId='0', applyAlignment='1')
        ET.SubElement(xf, 'alignment', vertical='top', wrapText='1', horizontal='center' if i == 2 else 'left')
    ET.SubElement(ET.SubElement(styles, 'cellStyles', count='1'), 'cellStyle', name='Normal', xfId='0', builtinId='0')
    types = ET.Element('Types', xmlns='http://schemas.openxmlformats.org/package/2006/content-types')
    for ext, mime in [('rels', 'application/vnd.openxmlformats-package.relationships+xml'), ('xml', 'application/xml')]:
        ET.SubElement(types, 'Default', Extension=ext, ContentType=mime)
    for name, mime in [('workbook', 'sheet.main'), ('worksheets/sheet1', 'worksheet'), ('styles', 'styles')]:
        ET.SubElement(types, 'Override', PartName=f'/xl/{name}.xml', ContentType=f'application/vnd.openxmlformats-officedocument.spreadsheetml.{mime}+xml')
    root_rels = ET.Element('Relationships', xmlns=PKG)
    ET.SubElement(root_rels, 'Relationship', Id='rId1', Type=REL + '/officeDocument', Target='xl/workbook.xml')
    rels = ET.Element('Relationships', xmlns=PKG)
    for i, (kind, target) in enumerate([('worksheet', 'worksheets/sheet1.xml'), ('styles', 'styles.xml')], 1):
        ET.SubElement(rels, 'Relationship', Id=f'rId{i}', Type=REL + '/' + kind, Target=target)
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_STORED) as z:
        for name, node in [('[Content_Types].xml', types), ('_rels/.rels', root_rels),
                           ('xl/workbook.xml', workbook), ('xl/_rels/workbook.xml.rels', rels),
                           ('xl/styles.xml', styles), ('xl/worksheets/sheet1.xml', sheet)]:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 0; info.external_attr = 0x20
            z.writestr(info, _xml(node))


def _same(a, b):
    return a.resolve() == b.resolve() or (a.exists() and b.exists() and os.path.samefile(a, b))


def _publish(temp, target, overwrite):
    if overwrite:
        os.replace(temp, target)
    else:
        # Atomic exclusive creation prevents a check/use race overwriting another file.
        os.link(temp, target)
        temp.unlink()


def _write_report(target, report, overwrite):
    with tempfile.NamedTemporaryFile(dir=target.parent, suffix='.json', delete=False) as f:
        temp = Path(f.name)
    try:
        temp.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
        _publish(temp, target, overwrite)
    finally:
        temp.unlink(missing_ok=True)


def export_xlsx(source, out, report_out, sheet_name='分镜表', overwrite=False):
    """Publish only after real ingest and exact cell readback; report is published last.

    Accepts an ingest snapshot dict or a path to its JSON. Caller is responsible
    for retaining/authenticating that independent snapshot. Never approves reviews.
    """
    out, report_out = Path(out), Path(report_out)
    source_path = Path(source) if isinstance(source, (str, os.PathLike)) else None
    source = load_json(source_path) if source_path else source
    protected = [source_path] if source_path else []
    if source_path and isinstance(source, dict) and source.get('source_file'):
        protected.append(source_path.parent / source['source_file'])
    if out.suffix.lower() != '.xlsx':
        raise ContractError('XLSX output requires .xlsx suffix')
    if _same(out, report_out) or any(_same(p, t) for p in protected for t in (out, report_out)):
        raise ContractError('Source, XLSX and report paths must be distinct; input overwrite forbidden')
    for target in (out, report_out):
        if target.is_symlink() or (target.exists() and (not overwrite or not target.is_file())):
            raise ContractError(f'Refusing existing/unsafe output: {target}')
        target.parent.mkdir(parents=True, exist_ok=True)
    report = {'schema_version': 'xlsx-export-1', 'exporter_version': EXPORTER_VERSION,
              'source_sha256': source.get('source_sha256') if isinstance(source, dict) else None,
              'source_snapshot_sha256': digest(source), 'xlsx_sha256': None,
              'requested_sheet_name': sheet_name, 'roundtrip_status': 'failed',
              'visual_review': 'needs_manual_review', 'checks': {}, 'differences': [],
              'fidelity_scope': 'Canonical columns only; raw mapped cells preferred; normalized fallbacks listed. No workbook layout/formula semantics copied.',
              'layout_limits': 'Row height is host-dependent; long rows require visual review.'}
    temp = None
    published = False
    backups = {}
    existing_targets = {target for target in (out, report_out) if target.exists()}
    try:
        # Ordinary-error rollback, not a cross-file/power-loss atomic transaction.
        # Back up both existing artifacts before any validation or publication.
        for target in (out, report_out):
            if target.exists():
                with tempfile.NamedTemporaryFile(dir=target.parent, suffix='.backup', delete=False) as f:
                    backup = Path(f.name)
                try:
                    shutil.copy2(target, backup)
                except OSError:
                    backup.unlink(missing_ok=True)
                    raise
                backups[target] = backup
        report['sheet_name'] = _sheet_name(sheet_name)
        columns, rows = _prepare(source, report)
        with tempfile.NamedTemporaryFile(dir=out.parent, suffix='.xlsx', delete=False) as f:
            temp = Path(f.name)
        _workbook(temp, columns, rows, report['sheet_name'])
        actual = ingest(temp, sheet_name=report['sheet_name'])
        actual_rows = [r for _, r in xlsx_tables(temp)[report['sheet_name']]][1:]
        expected_order = [row[0].strip() for row in rows]
        expected_durations = [Decimal(str(duration(row[1]))) for row in rows]
        actual_durations = [Decimal(str(s['duration_sec'])) for s in actual['shots']]
        field_comparisons = [{'source_shot_index': i, 'field': field,
                              'equal': i < len(actual_rows) and ci < len(actual_rows[i]) and
                              actual_rows[i][ci] == row[ci]}
                             for i, row in enumerate(rows)
                             for ci, (field, _, _) in enumerate(columns)]
        normalized_match = len(actual['shots']) == len(rows) and all(
            actual['shots'][i].get(field) == row[ci].strip()
            for i, row in enumerate(rows) for ci, (field, _, _) in enumerate(columns)
            if field != 'duration_sec')
        report['field_comparisons'] = field_comparisons
        checks = {'shot_count': len(actual['shots']) == len(rows),
                  'shot_order': [s['source_shot_no'] for s in actual['shots']] == expected_order,
                  'exact_raw_fields': actual_rows == rows,
                  'normalized_ingest_fields': normalized_match,
                  'duration_per_shot': actual_durations == expected_durations,
                  'total_duration': sum(actual_durations) == sum(expected_durations)}
        report['checks'] = checks
        report['shot_count'] = len(rows)
        report['total_duration_sec'] = str(sum(expected_durations))
        report['differences'] = [k for k, passed in checks.items() if not passed]
        if report['differences']:
            raise ContractError('XLSX roundtrip mismatch: ' + ', '.join(report['differences']))
        report['xlsx_sha256'] = digest(temp.read_bytes())
        report['roundtrip_status'] = 'passed'
        _publish(temp, out, overwrite)
        published = True
        _write_report(report_out, report, overwrite)
        return report
    except (ContractError, OSError, ValueError, TypeError, KeyError) as exc:
        report['roundtrip_status'] = 'failed'
        report['error'] = str(exc)
        rollback_errors = []
        for target in (out, report_out):
            try:
                if target in backups:
                    os.replace(backups[target], target)
                elif target == out and published:
                    target.unlink(missing_ok=True)
            except OSError as restore_exc:
                rollback_errors.append(f'{target}: {restore_exc}; backup={backups.get(target)}')
        # Never overwrite a restored prior report with this attempt's failure.
        if report_out not in existing_targets and not rollback_errors:
            try:
                _write_report(report_out, report, overwrite)
            except OSError:
                pass
        if rollback_errors:
            # Retain any remaining backups for explicit recovery if rollback fails.
            backups = {}
            raise ContractError(str(exc) + '; rollback failed: ' + '; '.join(rollback_errors)) from exc
        raise ContractError(str(exc)) from exc
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
        for backup in backups.values():
            backup.unlink(missing_ok=True)
