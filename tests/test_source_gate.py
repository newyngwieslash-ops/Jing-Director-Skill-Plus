"""Offline source-baseline regression specifications; no provider calls.

Fixtures are synthetic declarations, not evidence of real human approval.
"""
from __future__ import annotations
import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from director_core import ContractError, compiler, digest, load_json, validate
from director_pipeline import main

EXAMPLE = ROOT / 'examples/hall-shot-09/director-contract.json'
SOURCE = ROOT / 'examples/hall-shot-09/source-excerpt.json'


def codes(report, field='errors'):
    return {item['code'] for item in report[field]}


def reviewed_no_speech():
    doc, source = load_json(EXAMPLE), load_json(SOURCE)
    source['shots'][0]['dialogue_baseline'] = {
        'status': 'reviewed', 'reviewed_by': 'TEST_ONLY',
        'evidence': 'Synthetic classification fixture; not actual review.', 'lines': []}
    doc['source_shots'] = copy.deepcopy(source['shots'])
    return doc, source


class SourceGateTests(unittest.TestCase):
    def test_original_external_source_matches(self):
        report = validate(load_json(EXAMPLE), source=load_json(SOURCE))
        self.assertTrue(report['ok'], report)

    def test_compatibility_plan_has_unverified_source_warning(self):
        report = validate(load_json(EXAMPLE))
        self.assertTrue(report['ok'], report)
        self.assertTrue(any('SOURCE' in code for code in codes(report, 'warnings')), report)

    def test_production_requires_independent_source(self):
        report = validate(load_json(EXAMPLE), stage='production')
        self.assertFalse(report['ok'])
        self.assertIn('SOURCE_BASELINE_REQUIRED', codes(report))

    def test_simultaneous_embedded_source_and_director_edit_cannot_pass_baseline(self):
        doc, source = reviewed_no_speech()
        doc['source_shots'][0]['action'] = 'Rewritten source action'
        doc['shots'][0]['opening']['zh'] = 'Rewritten director action'
        report = validate(doc, source=source)
        self.assertIn('SOURCE_SNAPSHOT_CHANGED', codes(report))
        with self.assertRaises(ContractError):
            compiler(doc, 'minimax-h3', 'T2VA', '.', source=source)

    def test_changed_source_hash_rejected(self):
        doc, source = reviewed_no_speech()
        doc['project']['source_sha256'] = '0' * 64
        self.assertIn('SOURCE_SNAPSHOT_CHANGED', codes(validate(doc, source=source)))

    def test_mutated_ledger_rejected_against_independent_copy(self):
        doc, source = reviewed_no_speech()
        doc['source_shots'][0]['dialogue_baseline']['evidence'] = 'Changed evidence'
        self.assertIn('SOURCE_SNAPSHOT_CHANGED', codes(validate(doc, source=source)))

    def test_malformed_source_does_not_count_as_baseline(self):
        report = validate(load_json(EXAMPLE), source={})
        self.assertFalse(report['ok'], report)

    def test_draft_does_not_bypass_explicit_source_mismatch(self):
        doc, source = reviewed_no_speech()
        doc['source_shots'][0]['sound'] = 'silently replaced'
        with self.assertRaises(ContractError):
            compiler(doc, 'minimax-h3', 'T2VA', '.', draft=True, source=source)

    def test_matching_reviewed_baseline_keeps_offline_status(self):
        doc, source = reviewed_no_speech()
        _, manifest = compiler(doc, 'minimax-h3', 'T2VA', '.', source=source)
        self.assertFalse(manifest['submitted'])
        self.assertFalse(manifest['video_verified'])
        self.assertIn('offline', manifest['status'])
        self.assertTrue(manifest['source_snapshot_verified'])
        self.assertEqual(manifest['source_snapshot_sha256'], digest(source))
        self.assertEqual(manifest['contract_sha256'], digest(doc))

    def test_non_draft_compile_requires_source(self):
        with self.assertRaisesRegex(ContractError, 'SOURCE_BASELINE_REQUIRED'):
            compiler(load_json(EXAMPLE), 'minimax-h3', 'T2VA', '.')

    def test_non_draft_compile_requires_reviewed_dialogue_classification(self):
        with self.assertRaises(ContractError):
            compiler(load_json(EXAMPLE), 'minimax-h3', 'T2VA', '.', source=load_json(SOURCE))

    def test_draft_without_source_remains_explicitly_unverified(self):
        _, manifest = compiler(load_json(EXAMPLE), 'minimax-h3', 'T2VA', '.', draft=True)
        self.assertFalse(manifest['submitted'])
        self.assertIn('draft', manifest['status'])
        self.assertFalse(manifest['source_snapshot_verified'])
        self.assertIsNone(manifest['source_snapshot_sha256'])
        self.assertTrue(any('SOURCE' in item['code'] for item in manifest['warnings']))

    def test_missing_required_project_style_rejected_without_optional_schema(self):
        doc = load_json(EXAMPLE)
        del doc['project']['style']
        report = validate(doc)
        self.assertFalse(report['ok'], report)
        with self.assertRaises(ContractError):
            compiler(doc, 'minimax-h3', 'T2VA', '.')


class SourceGateCliTests(unittest.TestCase):
    def call(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            result = main([str(arg) for arg in args])
        return result, out.getvalue(), err.getvalue()

    def test_compile_accepts_source_and_writes_only_offline_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / 'bundle'
            doc, source = reviewed_no_speech()
            contract_path, source_path = Path(directory) / 'contract.json', Path(directory) / 'source.json'
            contract_path.write_text(json.dumps(doc), encoding='utf-8')
            source_path.write_text(json.dumps(source), encoding='utf-8')
            status, _, error = self.call('compile', contract_path, '--source', source_path,
                '--profile', 'minimax-h3', '--mode', 'T2VA', '--asset-root', directory,
                '--out-dir', out)
            self.assertEqual(status, 0, error)
            manifest = json.loads((out / 'manifest.json').read_text(encoding='utf-8'))
            self.assertFalse(manifest['submitted'])
            self.assertFalse(manifest['video_verified'])

    def test_compile_source_mismatch_writes_no_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            doc = load_json(EXAMPLE)
            doc['source_shots'][0]['action'] = 'tampered'
            path = Path(directory) / 'contract.json'
            path.write_text(json.dumps(doc), encoding='utf-8')
            out = Path(directory) / 'bundle'
            status, _, error = self.call('compile', path, '--source', SOURCE,
                '--profile', 'minimax-h3', '--mode', 'T2VA', '--asset-root', directory,
                '--out-dir', out, '--draft')
            self.assertEqual(status, 2)
            self.assertIn('SOURCE_SNAPSHOT_CHANGED', error)
            self.assertFalse((out / 'prompt.txt').exists())
            self.assertFalse((out / 'manifest.json').exists())

    def test_validate_source_gate_shared_with_library(self):
        status, output, error = self.call('validate', EXAMPLE, '--source', SOURCE)
        self.assertEqual(status, 0, error)
        self.assertTrue(json.loads(output)['ok'])


if __name__ == '__main__':
    unittest.main()
