"""Offline evidence-binding for MANUAL behavior grades; never a semantic/model oracle."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
from decimal import Decimal, ROUND_CEILING
from pathlib import Path

MAX_BYTES = 2 * 1024 * 1024
MAX_CASES = 200
VERSION = '1.0'

class EvalError(ValueError):
    pass

def check(ok, message):
    if not ok:
        raise EvalError(message)

def sha(data):
    return hashlib.sha256(data).hexdigest()

def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')

def read_bytes(path):
    path = Path(path)
    check(path.is_file() and not path.is_symlink(), 'not a regular non-symlink file: ' + str(path))
    check(path.stat().st_size <= MAX_BYTES, 'file exceeds resource limit')
    with path.open('rb') as stream:
        data = stream.read(MAX_BYTES + 1)
    check(len(data) <= MAX_BYTES, 'file exceeds resource limit')
    return data

def load(path):
    def pairs(items):
        out = {}
        for key, value in items:
            check(key not in out, 'duplicate JSON key: ' + key)
            out[key] = value
        return out
    def invalid(value):
        raise EvalError('non-finite number: ' + value)
    try:
        return json.loads(read_bytes(path).decode('utf-8'), object_pairs_hook=pairs, parse_constant=invalid)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise EvalError('invalid UTF-8 JSON') from exc

def fields(value, names):
    check(isinstance(value, dict) and set(value) == set(names.split()), 'unexpected or missing fields: ' + names)

def nonempty(value):
    return isinstance(value, str) and bool(value.strip())

def identifier(value):
    return isinstance(value, str) and re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,99}', value) is not None and '..' not in value

def bounded_list(value):
    check(isinstance(value, list) and len(value) <= MAX_CASES, 'invalid or excessive list')

def relative_file(root, name):
    check(isinstance(name, str) and nonempty(name) and '\\' not in name, 'invalid relative path')
    rel = Path(name)
    check(not rel.is_absolute() and '..' not in rel.parts and '.' != name, 'unsafe relative path')
    root = Path(root).resolve(strict=True)
    target = root / rel
    check(all(not (root.joinpath(*rel.parts[:i])).is_symlink() for i in range(1, len(rel.parts)+1)), 'symlink in artifact path')
    check(target.resolve().is_relative_to(root), 'artifact outside root')
    return target

def artifact(root, name):
    return {'path': name, 'sha256': sha(read_bytes(relative_file(root, name)))}

def verify_artifact(root, binding):
    fields(binding, 'path sha256')
    check(artifact(root, binding['path']) == binding, 'stale artifact hash: ' + str(binding['path']))
    return read_bytes(relative_file(root, binding['path']))

def validate_suite(suite):
    fields(suite, 'schema_version suite_id threshold_percent cases')
    check(suite['schema_version'] == VERSION and identifier(suite['suite_id']), 'invalid suite version/id')
    threshold = suite['threshold_percent']
    check(type(threshold) is int and 1 <= threshold <= 100, 'threshold must be integer 1..100')
    bounded_list(suite['cases'])
    check(bool(suite['cases']), 'empty suite')
    seen = set()
    for case in suite['cases']:
        fields(case, 'id prompt hard_fail assertions')
        check(identifier(case['id']) and case['id'] not in seen, 'duplicate/invalid case id')
        seen.add(case['id'])
        check(nonempty(case['prompt']) and len(case['prompt']) <= 32000 and type(case['hard_fail']) is bool, 'invalid case prompt/hard_fail')
        bounded_list(case['assertions'])
        check(1 <= len(case['assertions']) <= 20, 'assertion count outside 1..20')
        assertion_ids = set()
        for item in case['assertions']:
            fields(item, 'id text kind')
            check(identifier(item['id']) and item['id'] not in assertion_ids, 'duplicate/invalid assertion id')
            assertion_ids.add(item['id'])
            check(nonempty(item['text']) and item['kind'] in ('presence', 'absence', 'judgment'), 'invalid assertion')
    return suite

def required_count(total, threshold_percent):
    return int((Decimal(total) * Decimal(threshold_percent) / 100).to_integral_value(rounding=ROUND_CEILING))

def record(suite_path, root, specification):
    """Bind supplied response artifacts, not generate responses or grades."""
    suite = validate_suite(load(suite_path))
    fields(specification, 'run_id run_kind model_label sources responses')
    check(identifier(specification['run_id']), 'invalid run id')
    check(specification['run_kind'] in ('provided_model_run', 'synthetic_fixture'), 'invalid run kind')
    check(nonempty(specification['model_label']), 'model label required (self-reported)')
    bounded_list(specification['sources'])
    check(bool(specification['sources']), 'source snapshot artifacts required')
    check(all(isinstance(p, str) for p in specification['sources']) and len(set(specification['sources'])) == len(specification['sources']), 'duplicate source paths')
    sources = [artifact(root, name) for name in specification['sources']]
    cases = {c['id']: c for c in suite['cases']}
    bounded_list(specification['responses'])
    responses, seen, sessions = [], set(), set()
    for response in specification['responses']:
        fields(response, 'case_id path generator_session')
        cid, session = response['case_id'], response['generator_session']
        check(isinstance(cid, str) and cid in cases and cid not in seen, 'duplicate/unknown response case')
        check(identifier(session) and session not in sessions, 'generation requires unique per-case session ids')
        seen.add(cid); sessions.add(session)
        binding = artifact(root, response['path'])
        try:
            body = read_bytes(relative_file(root, response['path'])).decode('utf-8')
        except UnicodeError as exc:
            raise EvalError('response must be UTF-8') from exc
        check(nonempty(body), 'empty response')
        responses.append({'case_id': cid, 'prompt_sha256': sha(cases[cid]['prompt'].encode('utf-8')), 'artifact': binding, 'generator_session': session})
    return {'schema_version': VERSION, 'suite_sha256': sha(read_bytes(suite_path)), 'run_id': specification['run_id'], 'run_kind': specification['run_kind'], 'model_label': specification['model_label'], 'sources': sources, 'responses': responses}

def evaluate(suite_path, root, run=None, grades=None):
    suite = validate_suite(load(suite_path))
    count = len(suite['cases'])
    result = {'status': 'not_run', 'suite_sha256': sha(read_bytes(suite_path)), 'evaluation_type': 'manual_behavior_grades_structurally_checked', 'semantic_correctness_verified': False, 'model_identity_verified': False, 'video_quality_verified': False, 'release_ready': False, 'production_evidence': False, 'total_cases': count, 'required_passes': required_count(count, suite['threshold_percent']), 'passed_cases': 0, 'hard_failures': [], 'missing_responses': [], 'missing_grades': [], 'case_results': []}
    if run is None:
        check(grades is None, 'grades supplied without a run')
        return result
    fields(run, 'schema_version suite_sha256 run_id run_kind model_label sources responses')
    check(run['schema_version'] == VERSION and run['suite_sha256'] == sha(read_bytes(suite_path)), 'stale suite hash/version')
    # Rebuild the complete manifest from artifacts to verify every source, prompt and response hash.
    bounded_list(run['responses']); bounded_list(run['sources'])
    for source in run['sources']:
        fields(source, 'path sha256')
    for response in run['responses']:
        fields(response, 'case_id prompt_sha256 artifact generator_session')
        fields(response['artifact'], 'path sha256')
    rebuilt = record(suite_path, root, {'run_id': run['run_id'], 'run_kind': run['run_kind'], 'model_label': run['model_label'], 'sources': [s['path'] for s in run['sources']], 'responses': [{'case_id': r['case_id'], 'path': r['artifact']['path'], 'generator_session': r['generator_session']} for r in run['responses']]})
    check(rebuilt == run, 'stale source/prompt/response hash or invalid run')
    result['run_kind'] = run['run_kind']
    result['suite_sha256'] = run['suite_sha256']
    result['run_sha256'] = sha(encoded(run))
    cases = {c['id']: c for c in suite['cases']}
    responses = {r['case_id']: r for r in run['responses']}
    result['missing_responses'] = sorted(set(cases) - set(responses))
    if grades is None:
        result['status'] = 'incomplete'
        result['missing_grades'] = sorted(cases)
        return result
    fields(grades, 'schema_version run_sha256 reviewer_id grader_session manual_review_acknowledged grades')
    check(grades['schema_version'] == VERSION and grades['run_sha256'] == sha(encoded(run)), 'stale grade run hash/version')
    check(nonempty(grades['reviewer_id']) and identifier(grades['grader_session']), 'reviewer/session required')
    check(grades['grader_session'] not in {r['generator_session'] for r in run['responses']}, 'generation and grading sessions must differ')
    check(grades['manual_review_acknowledged'] is True, 'draft grades are not a completed manual review')
    bounded_list(grades['grades'])
    result['grades_sha256'] = sha(encoded(grades))
    seen = set()
    for grade in grades['grades']:
        fields(grade, 'case_id response_sha256 assertions')
        cid = grade['case_id']
        check(isinstance(cid, str) and cid in responses and cid not in seen, 'duplicate/unknown/unrecorded grade case')
        seen.add(cid)
        response = responses[cid]
        check(grade['response_sha256'] == response['artifact']['sha256'], 'stale grade response hash')
        body = verify_artifact(root, response['artifact']).decode('utf-8')
        expected = {a['id']: a for a in cases[cid]['assertions']}
        bounded_list(grade['assertions'])
        got, failed = set(), []
        for assertion in grade['assertions']:
            fields(assertion, 'id verdict quotes rationale')
            aid = assertion['id']
            check(isinstance(aid, str) and aid in expected and aid not in got, 'duplicate/unknown grade assertion')
            got.add(aid)
            check(assertion['verdict'] in ('pass', 'fail') and nonempty(assertion['rationale']), 'invalid verdict/rationale')
            bounded_list(assertion['quotes'])
            check(all(nonempty(q) and q in body for q in assertion['quotes']), 'evidence quote does not exist in response')
            if assertion['verdict'] == 'pass' and expected[aid]['kind'] != 'absence':
                check(bool(assertion['quotes']), 'positive pass requires exact response quote')
            if assertion['verdict'] == 'fail':
                failed.append(aid)
        missing = sorted(set(expected) - got)
        passed = not missing and not failed
        result['case_results'].append({'case_id': cid, 'passed': passed, 'failed_assertions': failed, 'missing_assertions': missing})
        if missing:
            result['missing_grades'].append(cid)
        if failed and cases[cid]['hard_fail']:
            result['hard_failures'].append(cid)
        result['passed_cases'] += int(passed)
    result['missing_grades'] = sorted(set(result['missing_grades']) | (set(cases) - seen))
    complete = not result['missing_responses'] and not result['missing_grades']
    meets_bar = complete and not result['hard_failures'] and result['passed_cases'] >= result['required_passes']
    result['status'] = ('incomplete' if not complete else 'manual_grades_pass' if meets_bar else 'manual_grades_fail')
    if complete and run['run_kind'] == 'synthetic_fixture':
        result['status'] = 'synthetic_fixture_pass' if meets_bar else 'synthetic_fixture_fail'
    # No behavior-only report grants production/release approval, even with genuine supplied responses.
    result['provided_model_response_evidence'] = complete and run['run_kind'] == 'provided_model_run'
    return result

def write_new(path, value):
    path = Path(path)
    check(not any(p.is_symlink() for p in [path, *path.parents]), 'symlink output path')
    check(path.parent.is_dir(), 'output parent must already exist')
    with path.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='command', required=True)
    validate = subs.add_parser('validate-cases'); validate.add_argument('--suite', required=True)
    rec = subs.add_parser('record'); rec.add_argument('--suite', required=True); rec.add_argument('--root', required=True); rec.add_argument('--input', required=True); rec.add_argument('--out', required=True)
    ev = subs.add_parser('evaluate'); ev.add_argument('--suite', required=True); ev.add_argument('--root', required=True); ev.add_argument('--run'); ev.add_argument('--grades'); ev.add_argument('--out', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'validate-cases':
            suite = validate_suite(load(args.suite))
            print(json.dumps({'status': 'cases_valid_not_run', 'cases': len(suite['cases']), 'suite_sha256': sha(read_bytes(args.suite))}))
        elif args.command == 'record':
            write_new(args.out, record(args.suite, args.root, load(args.input)))
        else:
            report = evaluate(args.suite, args.root, load(args.run) if args.run else None, load(args.grades) if args.grades else None)
            write_new(args.out, report)
            print(report['status'])
            return 0 if report['status'] in ('manual_grades_pass', 'synthetic_fixture_pass') else 1
        return 0
    except (EvalError, OSError, TypeError, KeyError, ValueError) as exc:
        parser.exit(2, 'evaluation blocked: ' + str(exc) + '\n')

if __name__ == '__main__':
    raise SystemExit(main())
