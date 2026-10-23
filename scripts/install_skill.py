#!/usr/bin/env python3
"""Install JingStudio (jingstudio) for Codex/ZCode/Claude Code; never migrate older skills.

Python 3.10+, standard library only. Run from an extracted staging directory.
No network, provider calls, dependency installs or host configuration edits.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import tempfile

NAME = 'jingstudio'
SOURCE = Path(__file__).resolve().parents[1]
PROTECTED_NAMES = frozenset({'shanyin-director-master', 'shanyin-director-master-2', 'shanyin-director-master-3', 'shanyin-director-master-v3'})
IGNORE = shutil.ignore_patterns('__pycache__', '*.pyc', '.pytest_cache')

def _package_copy_ignore(source: Path):
    def ignore(directory, names):
        excluded = set(IGNORE(directory, names))
        if Path(directory) == source and '.git' in names:
            excluded.add('.git')
        return excluded
    return ignore


def _linked(path: Path) -> bool:
    """Also reject Windows junctions/reparse points, including broken links."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 1024)
    )


def _safe_path(path: Path) -> Path:
    path = Path(os.path.abspath(path.expanduser()))
    for node in (path, *path.parents):
        if _linked(node):
            raise ValueError(f'Symlink/junction/reparse path is not supported by this installer: {node}')
    return path


def _overlap(a: Path, b: Path) -> bool:
    return a == b or a.is_relative_to(b) or b.is_relative_to(a)


def _snapshot(root: Path, *, ignore_cache: bool = False) -> dict[str, str]:
    result = {}
    for directory, dirs, files in os.walk(root, followlinks=False):
        base = Path(directory)
        for name in dirs + files:
            p = base / name
            if _linked(p):
                raise ValueError(f'Refusing linked member: {p}')
        if ignore_cache:
            dirs[:] = [x for x in dirs if x not in ('__pycache__', '.pytest_cache')
                       and not (base == root and x == '.git')]
        for name in files:
            if ignore_cache and (name.endswith('.pyc') or (base == root and name == '.git')):
                continue
            p = base / name
            if not p.is_file():
                raise ValueError(f'Not a regular file: {p}')
            result[p.relative_to(root).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return result


def _frontmatter(path: Path) -> tuple[dict[str, str], str]:
    text = path.read_text(encoding='utf-8-sig')
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != '---':
        raise ValueError(f'Missing SKILL frontmatter: {path}')
    stop = next((i for i in range(1, len(lines)) if lines[i].strip() == '---'), None)
    if stop is None:
        raise ValueError(f'Unclosed SKILL frontmatter: {path}')
    fields = {}
    for line in lines[1:stop]:
        match = re.match(r'^(name|description):\s*(.*?)\s*$', line)
        if match:
            key, value = match.groups()
            if key in fields:
                raise ValueError(f'Duplicate frontmatter {key}: {path}')
            if len(value) > 1 and value[0] == value[-1] and value[0] in '\"\'':
                value = value[1:-1]
            fields[key] = value
    if fields.get('name') != NAME:
        raise ValueError(f'Skill identity mismatch: expected {NAME}, got {fields.get("name")!r}')
    description = fields.get('description', '')
    body = ''.join(lines[stop + 1:])
    if not description or description in ('>', '|') or len(description) > 1024:
        raise ValueError('This package requires a nonempty one-line description <=1024 characters.')
    if len(body.encode('utf-8')) > 100_000:
        raise ValueError('SKILL body exceeds the conservative 100KB host limit.')
    return fields, body


def check_package(source: Path) -> dict:
    source = _safe_path(Path(source))
    required = ('SKILL.md', 'VERSION', 'PACKAGE_MANIFEST.json', 'agents/openai.yaml',
                'scripts/director_pipeline.py', 'schemas/director-contract.schema.json')
    for rel in required:
        if not (source / rel).is_file():
            raise ValueError(f'Incomplete skill package: {rel}')
    _frontmatter(source / 'SKILL.md')
    snapshot = _snapshot(source, ignore_cache=True)
    entries = [p for p in snapshot if PurePosixPath(p).name == 'SKILL.md']
    if entries != ['SKILL.md']:
        raise ValueError(f'Expected exactly one active SKILL.md, found: {entries}')
    manifest = json.loads((source / 'PACKAGE_MANIFEST.json').read_text(encoding='utf-8'))
    version = (source / 'VERSION').read_text(encoding='utf-8').strip()
    if manifest.get('skill_name') != NAME or manifest.get('version') != version:
        raise ValueError('Package manifest identity/version mismatch.')
    declared = {}
    for item in manifest['files']:
        rel = item['path']
        path = PurePosixPath(rel)
        if (not rel or '\\' in rel or ':' in rel or path.is_absolute()
                or '..' in path.parts or path.as_posix() != rel or rel in declared
                or rel == 'PACKAGE_MANIFEST.json'):
            raise ValueError(f'Unsafe or duplicate manifest member: {rel!r}')
        p = source / rel
        if not p.is_file() or p.stat().st_size != item['size_bytes']:
            raise ValueError(f'Missing/incorrectly sized package member: {rel}')
        declared[rel] = item['sha256']
    actual = {k: v for k, v in snapshot.items() if k != 'PACKAGE_MANIFEST.json'}
    if declared != actual or len(declared) != manifest.get('file_count_excluding_manifest'):
        raise ValueError('Package checksum/file-set mismatch; do not install a partial or edited package.')
    metadata = (source / 'agents/openai.yaml').read_text(encoding='utf-8')
    if f'${NAME}' not in metadata or 'allow_implicit_invocation: false' not in metadata:
        raise ValueError('Codex metadata must invoke the unified skill identity explicitly.')
    return {'skill_name': NAME, 'version': version, 'files': snapshot}


def _prepare(source: Path, home: Path, agent: str, target_root, upgrade: bool, verified: dict) -> dict:
    if agent not in ('codex', 'zcode', 'claude'):
        raise ValueError(f'Unsupported agent: {agent}')
    folder = {'codex': '.agents', 'zcode': '.zcode', 'claude': '.claude'}[agent]
    root = _safe_path(Path(target_root) if target_root is not None else home / folder / 'skills')
    if any(part.casefold() in PROTECTED_NAMES or part.casefold() == NAME for part in root.parts):
        raise ValueError('Pass the skill collection root, never an existing skill directory or its subtree.')
    for ancestor in (root, *root.parents):
        if (ancestor / 'SKILL.md').is_file():
            raise ValueError(f'Refusing to install inside another skill: {ancestor}')
    target = _safe_path(root / NAME)
    backup_root = _safe_path(home / '.jingstudio-skill-backups')
    if _overlap(source, target) or _overlap(source, backup_root) or _overlap(root, backup_root):
        raise ValueError('Source, target and backup trees must be separate; run from an extracted staging folder.')
    if target.exists() and not target.is_dir():
        raise ValueError(f'Destination is not a directory: {target}')
    # Only inspect alternate unified skill installations for the same client, not other named skills.
    if agent == 'codex':
        for alternate in (home / '.agents/skills' / NAME, home / '.codex/skills' / NAME):
            if alternate != target and (alternate.exists() or _linked(alternate)):
                raise ValueError(f'Another Codex unified skill copy exists at {alternate}. Resolve it manually; nothing is migrated.')
    before = _snapshot(target) if target.exists() else None
    if before is not None:
        # A wrongly renamed old skill must never be overwritten, even with --upgrade.
        _frontmatter(target / 'SKILL.md')
    identical = before is not None and _snapshot(target, ignore_cache=True) == verified['files']
    if before is not None and not identical and not upgrade:
        raise ValueError(f'Different unified skill destination already exists: {target}. Use --upgrade to back up ONLY this unified skill.')
    return {'agent': agent, 'root': root, 'target': target, 'before': before,
            'action': 'already_identical' if identical else ('upgrade' if before is not None else 'install')}


def install_selected(source=SOURCE, target_root=None, home=None, upgrade=False, dry_run=False, agent='codex'):
    """Preflight all selected hosts; back up changed unified skill targets; rollback ordinary failures."""
    if agent not in ('codex', 'zcode', 'claude', 'both'):
        raise ValueError(f'Unsupported agent: {agent}')
    if agent == 'both' and target_root is not None:
        raise ValueError('--target-root is only allowed with a single --agent.')
    source = _safe_path(Path(source))
    home = _safe_path(Path(home) if home is not None else Path.home())
    verified = check_package(source)
    agents = ('codex', 'zcode') if agent == 'both' else (agent,)
    plans = [_prepare(source, home, a, target_root, upgrade, verified) for a in agents]
    output = {'skill_name': NAME, 'version': verified['version'], 'dry_run': dry_run,
              'older_skill_policy': 'never_modify_or_migrate', 'host_detection': 'not_tested',
              'source': str(source), 'results': []}
    for p in plans:
        output['results'].append({'agent': p['agent'], 'target': str(p['target']), 'action': p['action'],
                                  'installed': False, 'verified': False, 'backups': []})
    if dry_run:
        return output
    changes = [p for p in plans if p['action'] != 'already_identical']
    if not changes:
        for item in output['results']:
            item['verified'] = True
        return output
    home.mkdir(parents=True, exist_ok=True)
    lock_path = _safe_path(home / f'.{NAME}-install.lock')
    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise ValueError(f'Installer lock exists: {lock_path}. Check for another install; after a crash, inspect before removing it.') from error
    os.close(lock_fd)
    backups = {}
    touched = []
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    backup_root = home / '.jingstudio-skill-backups' / stamp
    try:
        with tempfile.TemporaryDirectory(prefix='jingstudio-stage-', dir=home) as temporary:
            stage_root = Path(temporary)
            for p in changes:
                stage = stage_root / p['agent'] / NAME
                shutil.copytree(source, stage, ignore=_package_copy_ignore(source))
                check_package(stage)
                p['stage'] = stage
            # Copy and verify all needed backups before touching any destination.
            for p in changes:
                target = p['target']
                _safe_path(target)
                current = _snapshot(target) if target.exists() else None
                if current != p['before']:
                    raise ValueError(f'Destination changed after preflight: {target}')
                if current is not None:
                    backup = backup_root / p['agent'] / NAME
                    _safe_path(backup)
                    shutil.copytree(target, backup)
                    if _snapshot(backup) != current:
                        raise ValueError(f'Backup verification failed: {backup}')
                    backups[p['agent']] = backup
            for p in changes:
                target = p['target']
                _safe_path(target)
                current = _snapshot(target) if target.exists() else None
                if current != p['before']:
                    raise ValueError(f'Destination changed before commit: {target}')
                p['root'].mkdir(parents=True, exist_ok=True)
                touched.append(p)
                if target.exists():
                    shutil.rmtree(target)  # only this unified skill, with a verified backup
                shutil.move(str(p['stage']), str(target))
                if check_package(target)['files'] != verified['files']:
                    raise ValueError(f'Installed file verification failed: {target}')
        for item in output['results']:
            item['installed'] = item['action'] != 'already_identical'
            item['verified'] = True
            if item['agent'] in backups:
                item['backups'] = [str(backups[item['agent']])]
        return output
    except Exception as error:
        recovery_errors = []
        for p in reversed(touched):
            try:
                target = _safe_path(p['target'])
                if target.exists():
                    shutil.rmtree(target)
                if p['before'] is not None:
                    backup = backups[p['agent']]
                    shutil.copytree(backup, target)
                    if _snapshot(target) != p['before']:
                        raise ValueError('Restored destination hash mismatch')
            except Exception as recovery:
                recovery_errors.append(f'{p["target"]}: {recovery}')
        if recovery_errors:
            raise RuntimeError(f'{error}; rollback incomplete: {recovery_errors}; backups retained at {backup_root}') from error
        raise
    finally:
        lock_path.unlink(missing_ok=True)


def install(source=SOURCE, target_root=None, home=None, upgrade=False, dry_run=False, agent='codex'):
    """Single-host convenience API for offline tests and local integrations."""
    if agent == 'both':
        raise ValueError('Use install_selected for both agents.')
    result = install_selected(source, target_root, home, upgrade, dry_run, agent)
    return {**result['results'][0], 'skill_name': NAME, 'version': result['version'], 'dry_run': dry_run,
            'host_detection': result['host_detection'], 'older_skill_policy': result['older_skill_policy']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--agent', choices=('codex', 'zcode', 'claude', 'both'), default='codex',
                        help='Target host; both means Codex and ZCode only (legacy behavior).')
    parser.add_argument('--target-root', help='Override the collection root for ONE agent, not a skill directory.')
    parser.add_argument('--upgrade', action='store_true', help='Back up and replace ONLY an existing different unified skill copy.')
    parser.add_argument('--dry-run', action='store_true', help='Validate and show plans without writing any files.')
    parser.add_argument('--verify-package', action='store_true', help='Verify the extracted package only; install nothing.')
    args = parser.parse_args(argv)
    try:
        if args.verify_package:
            result = check_package(SOURCE)
            print(json.dumps({'skill_name': NAME, 'version': result['version'], 'verified': True,
                              'file_count': len(result['files']), 'installed': False}, ensure_ascii=False, indent=2))
        else:
            result = install_selected(target_root=args.target_root, upgrade=args.upgrade, dry_run=args.dry_run, agent=args.agent)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
        print(f'INSTALL ERROR: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
