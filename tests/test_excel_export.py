from __future__ import annotations
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from director_core import ContractError, digest, ingest, xlsx_tables
from director_export import COLUMNS, export_xlsx


class ExcelExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.input = self.root / 'table.json'
        self.headers = [h for _, h, _ in COLUMNS]
        self.rows = [['001', '0.1', '低角度', '近景', '  动作<&>\n\n第二行\r\n末行  ', '场景',
                      ' =SUM(A1)\n+不是公式\n-台词\n@人物 ', '', '叙事目的'],
                     ['中文镜号', '00:59:59-01:00:01', '', '', '第二镜', '', '', '', '']]
        self.source = self.make_source()
        self.out = self.root / 'out.xlsx'
        self.report = self.root / 'report.json'

    def make_source(self):
        self.input.write_text(json.dumps({'headers': self.headers, 'rows': self.rows}, ensure_ascii=False), encoding='utf-8')
        return ingest(self.input)

    def export(self, source=None, **kw):
        return export_xlsx(self.source if source is None else source, self.out, self.report, **kw)

    def test_exact_raw_roundtrip_and_deterministic_bytes(self):
        before = copy.deepcopy(self.source)
        original_hash = digest(self.input.read_bytes())
        report = self.export()
        result = [r for _, r in xlsx_tables(self.out)['分镜表']][1:]
        self.assertEqual(result, self.rows)
        first = self.out.read_bytes()
        second_report = export_xlsx(self.source, self.root / 'two.xlsx', self.root / 'two.json')
        self.assertEqual(first, (self.root / 'two.xlsx').read_bytes())
        self.assertEqual(report, second_report)
        self.assertEqual(report['xlsx_sha256'], digest(first))
        self.assertTrue(all(report['checks'].values()))
        self.assertEqual(report['total_duration_sec'], '2.1')
        self.assertEqual(report['visual_review'], 'needs_manual_review')
        self.assertEqual(self.source, before)
        self.assertEqual(digest(self.input.read_bytes()), original_hash)
        with zipfile.ZipFile(self.out) as z:
            for member in z.infolist():
                self.assertEqual(member.date_time, (1980, 1, 1, 0, 0, 0))
                self.assertEqual(member.compress_type, zipfile.ZIP_STORED)
                tree = ET.fromstring(z.read(member))
                self.assertFalse(any(n.tag.rsplit('}', 1)[-1] == 'f' for n in tree.iter()))
                self.assertNotIn(b'TargetMode="External"', z.read(member))

    def test_optional_prompt_even_empty_column(self):
        self.headers.append('视频提示词')
        self.rows[0].append(''); self.rows[1].append('')
        self.export(self.make_source())
        self.assertEqual(len(xlsx_tables(self.out)['分镜表'][0][1]), 10)

    def test_prompt_raw_column_without_top_level_headers(self):
        source = copy.deepcopy(self.source)
        source.pop('headers')
        source['shots'][1]['raw_cells']['视频提示词'] = '=提示词'
        source['shots'][1]['video_prompt'] = '=提示词'
        self.export(source)
        self.assertEqual(len(xlsx_tables(self.out)['分镜表'][1][1]), 10)

    def test_normalized_legacy_fallback_documented(self):
        source = copy.deepcopy(self.source)
        for shot in source['shots']:
            shot.pop('raw_cells')
        report = self.export(source)
        self.assertTrue(report['normalized_fallback_fields'])
        self.assertEqual(xlsx_tables(self.out)['分镜表'][1][1][4], self.rows[0][4].strip())

    def test_unknown_nonempty_columns_fail_with_report(self):
        self.headers.extend(['预算', '空列'])
        self.rows[0].extend(['0', '']); self.rows[1].extend(['', ''])
        with self.assertRaisesRegex(ContractError, 'unmapped'):
            self.export(self.make_source())
        self.assertFalse(self.out.exists())
        report = json.loads(self.report.read_text())
        self.assertEqual(report['roundtrip_status'], 'failed')
        self.assertEqual(report['unmapped_columns'], [
            {'column': '预算', 'nonempty_source_rows': [2]}, {'column': '空列', 'nonempty_source_rows': []}])

    def test_unknown_empty_column_listed(self):
        self.headers.append('空列')
        report = self.export(self.make_source())
        self.assertEqual(report['unmapped_columns'], [{'column': '空列', 'nonempty_source_rows': []}])

    def test_illegal_and_long_text_not_truncated(self):
        for text in ['bad\x00', 'x' * 32768, '😀' * 16384]:
            with self.subTest(text_length=len(text)):
                source = copy.deepcopy(self.source)
                source['shots'][0]['action'] = text
                source['shots'][0]['raw_cells']['画面内容'] = text
                with self.assertRaises(ContractError):
                    self.export(source, overwrite=True)
                self.assertFalse(self.out.exists())

    def test_reserved_ooxml_escape_literals_fail_without_mutation(self):
        for value in ('literal _x000D_', '_x0041_', '_Xabcd_', '_x005F_x0041_'):
            with self.subTest(value=value):
                source = copy.deepcopy(self.source)
                source['shots'][0]['action'] = value
                source['shots'][0]['raw_cells']['画面内容'] = value
                before = copy.deepcopy(source)
                self.report.unlink(missing_ok=True)
                with self.assertRaisesRegex(ContractError, 'reserved OOXML escape sequence'):
                    self.export(source)
                self.assertEqual(source, before)
                self.assertFalse(self.out.exists())
                self.assertEqual(json.loads(self.report.read_text())['roundtrip_status'], 'failed')
        self.report.unlink(missing_ok=True)
        with self.assertRaisesRegex(ContractError, 'reserved OOXML escape sequence'):
            self.export(sheet_name='_x0041_')

    def test_legal_sheet_name(self):
        report = self.export(sheet_name="'a[]:*?/\\" + '中' * 40 + "'")
        name = report['sheet_name']
        self.assertLessEqual(len(name), 31)
        self.assertNotRegex(name, r"[\[\]:*?/\\']")
        self.assertIn(name, xlsx_tables(self.out))

    def test_empty_sheet_name(self):
        self.assertEqual(self.export(sheet_name="''")['sheet_name'], '分镜表')

    def test_source_and_outputs_protected(self):
        source_path = self.root / 'snapshot.json'
        source_path.write_text(json.dumps(self.source), encoding='utf-8')
        before = source_path.read_bytes()
        with self.assertRaises(ContractError):
            export_xlsx(source_path, self.out, source_path, overwrite=True)
        with self.assertRaises(ContractError):
            export_xlsx(source_path, self.out, self.input, overwrite=True)
        self.assertEqual(source_path.read_bytes(), before)
        self.export()
        first = self.out.read_bytes()
        with self.assertRaises(ContractError): self.export()
        self.assertEqual(self.out.read_bytes(), first)
        with self.assertRaises(ContractError):
            export_xlsx(self.source, self.out, self.out, overwrite=True)

    def test_hardlink_and_symlink_protected(self):
        source_path = self.root / 'snapshot.json'
        source_path.write_text(json.dumps(self.source), encoding='utf-8')
        self.out.hardlink_to(source_path)
        with self.assertRaises(ContractError):
            export_xlsx(source_path, self.out, self.report, overwrite=True)
        self.out.unlink()
        self.out.symlink_to(self.input)
        with self.assertRaises(ContractError): self.export(overwrite=True)

    def test_real_ingest_called_and_mismatch_blocks(self):
        with patch('director_export.ingest', wraps=ingest) as reader:
            self.export()
            self.assertEqual(reader.call_count, 1)
        wrong = copy.deepcopy(self.source)
        wrong['shots'].reverse()
        with patch('director_export.ingest', return_value=wrong):
            with self.assertRaisesRegex(ContractError, 'roundtrip mismatch'):
                self.export(overwrite=True)
        # A failed overwrite keeps the previous successful pair intact.
        self.assertEqual(json.loads(self.report.read_text())['roundtrip_status'], 'passed')

    def test_raw_normalized_conflict_and_ambiguous_duration(self):
        for field, value in [('画面内容', 'changed'), ('时长', '结束')]:
            source = copy.deepcopy(self.source)
            source['shots'][0]['raw_cells'][field] = value
            with self.assertRaises(ContractError): self.export(source, overwrite=True)
            self.assertFalse(self.out.exists())

    def test_snapshot_path_and_reject_contract(self):
        path = self.root / 'snapshot.json'
        path.write_text(json.dumps(self.source), encoding='utf-8')
        self.assertEqual(self.export(path)['roundtrip_status'], 'passed')
        with self.assertRaisesRegex(ContractError, 'independent'):
            self.export({'project': {}, 'shots': []}, overwrite=True)

    def test_repeated_headers_blocked(self):
        source = copy.deepcopy(self.source)
        source['ignored_rows'] = [{'row': 5, 'reason': 'repeated_header'}]
        with self.assertRaisesRegex(ContractError, 'Ignored source rows'):
            self.export(source)

    def test_custom_columns_without_raw_and_duplicate_headers_block(self):
        source = copy.deepcopy(self.source)
        source['headers'].append('未知列')
        with self.assertRaisesRegex(ContractError, 'missing original cells'):
            self.export(source)
        source = copy.deepcopy(self.source)
        source['headers'].extend(['自定义', '自定义'])
        with self.assertRaisesRegex(ContractError, 'Duplicate source headers'):
            self.export(source, overwrite=True)

    def test_normalized_ingest_field_mismatch_blocks(self):
        wrong = copy.deepcopy(self.source)
        wrong['shots'][0]['sound'] = 'changed'
        with patch('director_export.ingest', return_value=wrong):
            with self.assertRaisesRegex(ContractError, 'normalized_ingest_fields'):
                self.export()
        self.assertFalse(self.out.exists())

    def test_failed_overwrite_restores_both_previous_files(self):
        self.out.write_bytes(b'OLD XLSX')
        self.report.write_bytes(b'OLD REPORT')
        with patch('director_export._write_report', side_effect=OSError('disk full')):
            with self.assertRaisesRegex(ContractError, 'disk full'):
                self.export(overwrite=True)
        self.assertEqual(self.out.read_bytes(), b'OLD XLSX')
        self.assertEqual(self.report.read_bytes(), b'OLD REPORT')
        self.assertFalse(list(self.root.glob('*.backup')))

    def test_failed_backup_preserves_previous_pair(self):
        self.out.write_bytes(b'OLD XLSX')
        self.report.write_bytes(b'OLD REPORT')
        with patch('director_export.shutil.copy2', side_effect=OSError('backup failed')):
            with self.assertRaisesRegex(ContractError, 'backup failed'):
                self.export(overwrite=True)
        self.assertEqual(self.out.read_bytes(), b'OLD XLSX')
        self.assertEqual(self.report.read_bytes(), b'OLD REPORT')

    def test_failed_partial_report_publication_restores_pair(self):
        self.out.write_bytes(b'OLD XLSX')
        self.report.write_bytes(b'OLD REPORT')
        def partial_write(target, report, overwrite):
            target.write_bytes(b'PARTIAL NEW REPORT')
            raise OSError('publication failed')
        with patch('director_export._write_report', side_effect=partial_write):
            with self.assertRaisesRegex(ContractError, 'publication failed'):
                self.export(overwrite=True)
        self.assertEqual(self.out.read_bytes(), b'OLD XLSX')
        self.assertEqual(self.report.read_bytes(), b'OLD REPORT')

    def test_malformed_ignored_rows_produce_failure_report(self):
        for ignored in ([None], 'not an array', None):
            source = copy.deepcopy(self.source)
            source['ignored_rows'] = ignored
            self.report.unlink(missing_ok=True)
            with self.assertRaisesRegex(ContractError, 'ignored_rows must be an array of objects'):
                self.export(source)
            self.assertEqual(json.loads(self.report.read_text())['roundtrip_status'], 'failed')

    def test_publication_failure_does_not_leave_success(self):
        with patch('director_export._write_report', side_effect=OSError('test disk failure')):
            with self.assertRaisesRegex(ContractError, 'disk failure'): self.export()
        self.assertFalse(self.out.exists())


if __name__ == '__main__':
    unittest.main()
