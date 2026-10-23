from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from install_skill import NAME, check_package, install, install_selected, _snapshot

OLD = 'shanyin-director-master-2'


def old_skill(home, folder, name=OLD):
    p = Path(home) / folder / 'skills' / name
    p.mkdir(parents=True, exist_ok=True)
    (p / 'SKILL.md').write_text(f'---\nname: {name}\ndescription: original\n---\nKEEP OLD\n', encoding='utf-8')
    (p / 'do-not-touch.txt').write_text('original custom file 中文', encoding='utf-8')
    return p


def temp_source(parent, name=NAME):
    dst = Path(parent) / name
    cache_ignore = shutil.ignore_patterns('__pycache__', '*.pyc', '.pytest_cache')
    def ignore(directory, names):
        excluded = set(cache_ignore(directory, names))
        if Path(directory) == ROOT and '.git' in names:
            excluded.add('.git')
        return excluded
    shutil.copytree(ROOT, dst, ignore=ignore)
    return dst


class IdentityTests(unittest.TestCase):
    def test_canonical_name(self):
        self.assertEqual(NAME, 'jingstudio')
        self.assertEqual(json.loads((ROOT / 'PACKAGE_MANIFEST.json').read_text(encoding='utf-8'))['skill_name'], NAME)
        text = (ROOT / 'SKILL.md').read_text(encoding='utf-8')
        self.assertIn(f'\nname: {NAME}\n', text)
        self.assertIn(f'${NAME}', text)
        self.assertIn(f'/{NAME}', text)
        self.assertNotIn(f'${OLD}', text)

    def test_single_active_entry(self):
        self.assertEqual([str(p.relative_to(ROOT)) for p in ROOT.rglob('SKILL.md')], ['SKILL.md'])

    def test_default_prompt_new_identity_and_explicit_invocation(self):
        text = (ROOT / 'agents/openai.yaml').read_text(encoding='utf-8')
        self.assertIn(f'${NAME}', text)
        self.assertNotIn(f'${OLD}', text)
        self.assertIn('allow_implicit_invocation: false', text)

    def test_manifest_and_package_version(self):
        info = check_package(ROOT)
        self.assertEqual(info['skill_name'], NAME)
        self.assertEqual(info['version'], '4.5.0')
        self.assertIn('README.zh-CN.md', info['files'])

    def test_schema_version_not_blindly_renamed(self):
        schema = json.loads((ROOT / 'schemas/director-contract.schema.json').read_text(encoding='utf-8'))
        sample = json.loads((ROOT / 'examples/hall-shot-09/director-contract.json').read_text(encoding='utf-8'))
        self.assertEqual(schema['properties']['schema_version']['const'], '3.0.0')
        self.assertEqual(sample['schema_version'], '3.0.0')

    def test_legacy_hashes_preserved(self):
        data = json.loads((ROOT / 'docs/ORIGINAL_PRESERVATION.json').read_text(encoding='utf-8'))
        self.assertEqual(len(data['files']), 20)
        for entry in data['files']:
            with self.subTest(path=entry['archived_path']):
                raw = (ROOT / entry['archived_path']).read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(), entry['sha256'])

    def test_yaml_with_optional_parser(self):
        try:
            import yaml
        except ImportError:
            self.skipTest('Optional PyYAML absent; package has standard-library identity checks.')
        entry = (ROOT / 'SKILL.md').read_text(encoding='utf-8').split('---', 2)
        self.assertEqual(yaml.safe_load(entry[1])['name'], NAME)
        meta = yaml.safe_load((ROOT / 'agents/openai.yaml').read_text(encoding='utf-8'))
        self.assertIs(meta['policy']['allow_implicit_invocation'], False)

    def test_frontmatter_wrong_name_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            src = temp_source(t)
            p = src / 'SKILL.md'
            p.write_text(p.read_text(encoding='utf-8').replace('name: ' + NAME, 'name: ' + OLD), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'identity'):
                check_package(src)

    def test_git_checkout_verify_install_excludes_root_metadata(self):
        with tempfile.TemporaryDirectory() as t:
            src = temp_source(t)
            git = src / '.git'; git.mkdir()
            (git / 'config').write_text('local repository metadata', encoding='utf-8')
            self.assertEqual(check_package(src)['skill_name'], 'jingstudio')
            target = Path(install(src, home=Path(t) / 'home')['target'])
            self.assertFalse((target / '.git').exists())
            self.assertTrue((target / '.gitignore').is_file())
            extra = src / 'untracked-secret.txt'; extra.write_text('untracked')
            self.assertRaises(ValueError, check_package, src)

    def test_arbitrary_checkout_name_installs_canonical_identity(self):
        with tempfile.TemporaryDirectory() as t:
            src = temp_source(t, 'custom-checkout-name')
            git = src / '.git'; git.mkdir()
            (git / 'config').write_text('fixture metadata', encoding='utf-8')
            self.assertNotEqual(src.name, NAME)
            self.assertEqual(check_package(src)['skill_name'], NAME)
            home = Path(t) / 'isolated-home'
            result = install(src, home=home)
            target = Path(result['target'])
            self.assertEqual(target, home / '.agents/skills' / NAME)
            self.assertTrue(result['verified'])
            self.assertFalse((target / '.git').exists())
            self.assertEqual(check_package(target)['skill_name'], NAME)

    def test_git_worktree_pointer_excluded(self):
        with tempfile.TemporaryDirectory() as t:
            src = temp_source(t)
            (src / '.git').write_text('gitdir: /not/read/or/followed', encoding='utf-8')
            target = Path(install(src, home=Path(t) / 'home')['target'])
            self.assertFalse((target / '.git').exists())

    def test_root_git_symlink_still_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            src = temp_source(t)
            try:
                (src / '.git').symlink_to(Path(t) / 'missing-git')
            except (OSError, NotImplementedError):
                self.skipTest('Symlinks unavailable')
            with self.assertRaisesRegex(ValueError, 'linked'):
                check_package(src)

    def test_nested_git_not_silently_ignored(self):
        with tempfile.TemporaryDirectory() as t:
            src = temp_source(t)
            nested = src / 'references/.git'; nested.mkdir()
            (nested / 'config').write_text('unexpected')
            self.assertRaises(ValueError, check_package, src)

    def test_changed_file_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            src = temp_source(t)
            (src / 'references/director-language-engine.md').write_text('tamper', encoding='utf-8')
            self.assertRaises(ValueError, check_package, src)

    def test_missing_file_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            src = temp_source(t)
            (src / 'scripts/director_core.py').unlink()
            self.assertRaises(ValueError, check_package, src)

    def test_extra_active_skill_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            src = temp_source(t)
            extra = src / 'nested/SKILL.md'
            extra.parent.mkdir()
            extra.write_text('anything', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'exactly one'):
                check_package(src)

    def test_unsafe_manifest_member_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            src = temp_source(t)
            p = src / 'PACKAGE_MANIFEST.json'
            data = json.loads(p.read_text(encoding='utf-8'))
            data['files'][0]['path'] = '../escape.txt'
            p.write_text(json.dumps(data), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Unsafe'):
                check_package(src)

    def test_broken_manifest_name_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            src = temp_source(t)
            p = src / 'PACKAGE_MANIFEST.json'
            data = json.loads(p.read_text(encoding='utf-8')); data['skill_name'] = OLD
            p.write_text(json.dumps(data), encoding='utf-8')
            self.assertRaises(ValueError, check_package, src)

    def test_extra_untracked_file_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            src = temp_source(t)
            (src / 'unexpected.sh').write_text('do not run', encoding='utf-8')
            self.assertRaises(ValueError, check_package, src)

    def test_version_cli_reports_package_and_schema_separately(self):
        r = subprocess.run([sys.executable, str(ROOT / 'scripts/director_pipeline.py'), '--version'], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f'{NAME} 4.5.0', r.stdout)
        self.assertIn('contract schema 3.0.0', r.stdout)


class InstallationTests(unittest.TestCase):
    def test_both_dry_run_no_changes(self):
        with tempfile.TemporaryDirectory() as t:
            before = sorted(Path(t).iterdir())
            result = install_selected(ROOT, home=t, agent='both', dry_run=True)
            self.assertEqual(len(result['results']), 2)
            self.assertTrue(all(not x['installed'] for x in result['results']))
            self.assertEqual(before, sorted(Path(t).iterdir()))

    def test_single_codex_install(self):
        with tempfile.TemporaryDirectory() as t:
            result = install(ROOT, home=t)
            self.assertEqual(Path(result['target']), Path(t) / '.agents/skills' / NAME)
            self.assertTrue(result['verified'])
            self.assertEqual(check_package(Path(result['target']))['files'], check_package(ROOT)['files'])
            self.assertEqual(result['host_detection'], 'not_tested')

    def test_single_zcode_install(self):
        with tempfile.TemporaryDirectory() as t:
            result = install(ROOT, home=t, agent='zcode')
            self.assertEqual(Path(result['target']), Path(t) / '.zcode/skills' / NAME)
            self.assertTrue(result['verified'])
            self.assertFalse((Path(t) / '.agents').exists())

    def test_both_targets_complete(self):
        with tempfile.TemporaryDirectory() as t:
            result = install_selected(ROOT, home=t, agent='both')
            self.assertTrue(all(x['installed'] and x['verified'] for x in result['results']))
            for item in result['results']:
                self.assertEqual(check_package(Path(item['target']))['files'], check_package(ROOT)['files'])

    def test_old_names_unchanged_on_install_and_unified_upgrade(self):
        with tempfile.TemporaryDirectory() as t:
            old = [old_skill(t, folder, name) for folder in ('.agents', '.codex', '.zcode', '.claude')
                   for name in ('shanyin-director-master', OLD, 'shanyin-director-master-3', 'shanyin-director-master-v3')]
            before = {str(p): _snapshot(p) for p in old}
            result = install_selected(ROOT, home=t, agent='both')
            for item in result['results']:
                (Path(item['target']) / 'custom-note.txt').write_text('back me up', encoding='utf-8')
            updated = install_selected(ROOT, home=t, agent='both', upgrade=True)
            self.assertTrue(all(x['backups'] for x in updated['results']))
            for p in old:
                self.assertEqual(_snapshot(p), before[str(p)])

    def test_all_legacy_names_protected_even_without_entry(self):
        from install_skill import PROTECTED_NAMES
        expected = {'shanyin-director-master', 'shanyin-director-master-2',
                    'shanyin-director-master-3', 'shanyin-director-master-v3'}
        self.assertEqual(PROTECTED_NAMES, expected)
        with tempfile.TemporaryDirectory() as t:
            for name in expected:
                root = Path(t) / name
                root.mkdir()
                with self.assertRaisesRegex(ValueError, 'collection root'):
                    install(ROOT, home=t, target_root=root, upgrade=True)
                self.assertEqual(list(root.iterdir()), [])

    def test_repeat_upgrade_backs_up_only_jingstudio(self):
        with tempfile.TemporaryDirectory() as t:
            old = old_skill(t, '.claude', 'shanyin-director-master')
            original = _snapshot(old)
            target = Path(install(ROOT, home=t, agent='claude')['target'])
            backups = []
            for value in ('first custom state', 'second custom state'):
                (target / 'user-note.txt').write_text(value, encoding='utf-8')
                before = _snapshot(target)
                result = install(ROOT, home=t, agent='claude', upgrade=True)
                backup = Path(result['backups'][0])
                self.assertTrue(backup.is_relative_to(Path(t) / '.jingstudio-skill-backups'))
                self.assertEqual(backup.name, 'jingstudio')
                self.assertEqual(_snapshot(backup), before)
                self.assertEqual(_snapshot(old), original)
                backups.append(backup)
            self.assertNotEqual(*backups)
            self.assertEqual((backups[0] / 'user-note.txt').read_text(), 'first custom state')

    def test_identical_reinstall_is_noop(self):
        with tempfile.TemporaryDirectory() as t:
            install_selected(ROOT, home=t, agent='both')
            result = install_selected(ROOT, home=t, agent='both')
            self.assertTrue(all(x['action'] == 'already_identical' and not x['installed'] and x['verified'] for x in result['results']))
            self.assertFalse((Path(t) / '.jingstudio-skill-backups').exists())

    def test_cache_files_do_not_force_upgrade(self):
        with tempfile.TemporaryDirectory() as t:
            target = Path(install(ROOT, home=t)['target'])
            cache = target / 'scripts/__pycache__'; cache.mkdir(exist_ok=True)
            (cache / 'example.pyc').write_bytes(b'cache')
            self.assertEqual(install(ROOT, home=t)['action'], 'already_identical')

    def test_different_unified_skill_refused_without_upgrade(self):
        with tempfile.TemporaryDirectory() as t:
            target = Path(install(ROOT, home=t)['target'])
            custom = target / 'custom-note.txt'; custom.write_text('keep me', encoding='utf-8')
            self.assertRaises(ValueError, install, ROOT, home=t)
            self.assertEqual(custom.read_text(encoding='utf-8'), 'keep me')

    def test_upgrade_backups_and_verifies_only_unified_skill(self):
        with tempfile.TemporaryDirectory() as t:
            target = Path(install(ROOT, home=t)['target'])
            (target / 'custom-note.txt').write_text('keep me', encoding='utf-8')
            before = _snapshot(target)
            result = install(ROOT, home=t, upgrade=True)
            backup = Path(result['backups'][0])
            self.assertEqual(_snapshot(backup), before)
            self.assertFalse(backup.is_relative_to(Path(t) / '.agents/skills'))
            self.assertNotIn('custom-note.txt', _snapshot(target))

    def test_old_identity_in_new_directory_not_overwritten(self):
        with tempfile.TemporaryDirectory() as t:
            target = old_skill(t, '.agents', NAME)
            p = target / 'SKILL.md'; p.write_text(f'---\nname: {OLD}\ndescription: original\n---\nKEEP', encoding='utf-8')
            before = _snapshot(target)
            self.assertRaises(ValueError, install, ROOT, home=t, upgrade=True)
            self.assertEqual(_snapshot(target), before)

    def test_both_preflight_before_any_install(self):
        with tempfile.TemporaryDirectory() as t:
            target = old_skill(t, '.zcode', NAME)
            before = _snapshot(target)
            self.assertRaises(ValueError, install_selected, ROOT, home=t, agent='both')
            self.assertFalse((Path(t) / '.agents').exists())
            self.assertEqual(_snapshot(target), before)

    def test_failed_backup_never_deletes_target(self):
        with tempfile.TemporaryDirectory() as t:
            target = Path(install(ROOT, home=t)['target'])
            (target / 'custom.txt').write_text('original', encoding='utf-8')
            before = _snapshot(target)
            original_copy = shutil.copytree
            def fail_backup(src, dst, *args, **kwargs):
                if '.jingstudio-skill-backups' in Path(dst).parts:
                    raise OSError('simulated backup failure')
                return original_copy(src, dst, *args, **kwargs)
            with patch('install_skill.shutil.copytree', side_effect=fail_backup):
                self.assertRaises(OSError, install, ROOT, home=t, upgrade=True)
            self.assertEqual(_snapshot(target), before)
            self.assertFalse((Path(t) / f'.{NAME}-install.lock').exists())

    def test_second_host_failure_rolls_back_both_new_targets(self):
        with tempfile.TemporaryDirectory() as t:
            old = old_skill(t, '.codex'); before = _snapshot(old)
            move = shutil.move
            def fail_second(src, dst, *args, **kwargs):
                if '.zcode' in Path(dst).parts:
                    raise OSError('simulated second host failure')
                return move(src, dst, *args, **kwargs)
            with patch('install_skill.shutil.move', side_effect=fail_second):
                self.assertRaises(OSError, install_selected, ROOT, home=t, agent='both')
            self.assertFalse((Path(t) / '.agents/skills' / NAME).exists())
            self.assertFalse((Path(t) / '.zcode/skills' / NAME).exists())
            self.assertEqual(_snapshot(old), before)

    def test_failed_upgrade_restores_original_unified_files(self):
        with tempfile.TemporaryDirectory() as t:
            installed = install_selected(ROOT, home=t, agent='both')
            before = {}
            for item in installed['results']:
                p = Path(item['target']); (p / 'note.txt').write_text(item['agent'], encoding='utf-8')
                before[str(p)] = _snapshot(p)
            move = shutil.move
            def fail_second(src, dst, *args, **kwargs):
                if '.zcode' in Path(dst).parts:
                    raise OSError('simulated upgrade failure')
                return move(src, dst, *args, **kwargs)
            with patch('install_skill.shutil.move', side_effect=fail_second):
                self.assertRaises(OSError, install_selected, ROOT, home=t, agent='both', upgrade=True)
            for item in installed['results']:
                p = Path(item['target']); self.assertEqual(_snapshot(p), before[str(p)])

    def test_refuse_install_inside_old_skill(self):
        with tempfile.TemporaryDirectory() as t:
            old = old_skill(t, '.codex'); before = _snapshot(old)
            self.assertRaises(ValueError, install, ROOT, home=t, target_root=old, upgrade=True)
            self.assertEqual(_snapshot(old), before)

    def test_refuse_source_target_overlap(self):
        with tempfile.TemporaryDirectory() as t:
            src = temp_source(t)
            before = _snapshot(src)
            self.assertRaises(ValueError, install, src, home=Path(t) / 'home', target_root=src.parent)
            self.assertEqual(_snapshot(src), before)
            self.assertFalse((Path(t) / 'home').exists())

    def test_single_custom_collection_root(self):
        with tempfile.TemporaryDirectory() as t:
            old = old_skill(t, '.codex'); before = _snapshot(old)
            root = Path(t) / '.codex/skills'
            result = install(ROOT, home=t, target_root=root)
            self.assertEqual(Path(result['target']), root / NAME)
            self.assertEqual(_snapshot(old), before)

    def test_alternate_codex_unified_copy_blocks_without_migration(self):
        with tempfile.TemporaryDirectory() as t:
            result = install(ROOT, home=t, target_root=Path(t) / '.codex/skills')
            target = Path(result['target']); before = _snapshot(target)
            self.assertRaises(ValueError, install, ROOT, home=t)
            self.assertEqual(_snapshot(target), before)

    def test_both_custom_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertRaises(ValueError, install_selected, ROOT, home=t, agent='both', target_root=Path(t) / 'custom')

    def test_existing_lock_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            lock = Path(t) / f'.{NAME}-install.lock'; lock.write_text('existing lock', encoding='utf-8')
            self.assertRaises(ValueError, install, ROOT, home=t)
            self.assertEqual(lock.read_text(encoding='utf-8'), 'existing lock')
            self.assertFalse((Path(t) / '.agents').exists())

    def test_target_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            old = old_skill(t, '.codex'); before = _snapshot(old)
            target = Path(t) / '.agents/skills' / NAME; target.parent.mkdir(parents=True)
            try:
                target.symlink_to(old, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest('This environment cannot create test symlinks.')
            self.assertRaises(ValueError, install, ROOT, home=t, upgrade=True)
            self.assertEqual(_snapshot(old), before)

    def test_legacy_migration_flag_not_accepted(self):
        p = subprocess.run([sys.executable, str(ROOT / 'scripts/install_skill.py'), '--migrate-legacy'], capture_output=True, text=True)
        self.assertEqual(p.returncode, 2)
        self.assertIn('unrecognized arguments', p.stderr)

    def test_verify_package_cli_is_read_only(self):
        p = subprocess.run([sys.executable, str(ROOT / 'scripts/install_skill.py'), '--verify-package'], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        data = json.loads(p.stdout)
        self.assertFalse(data['installed'])
        self.assertEqual(data['skill_name'], NAME)

    def test_empty_existing_target_refused(self):
        with tempfile.TemporaryDirectory() as t:
            target = Path(t) / '.agents/skills' / NAME; target.mkdir(parents=True)
            with self.assertRaises((ValueError, OSError)):
                install(ROOT, home=t, upgrade=True)
            self.assertTrue(target.is_dir())


if __name__ == '__main__':
    unittest.main()

