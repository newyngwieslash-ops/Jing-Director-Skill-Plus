"""Portability and preservation checks for the unified package."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from install_skill import NAME, install, _snapshot


class MergedInstallTests(unittest.TestCase):
    def test_claude_install_and_repeat(self):
        with tempfile.TemporaryDirectory() as home:
            first = install(ROOT, home=home, agent='claude')
            self.assertEqual(Path(first['target']), Path(home) / '.claude/skills' / NAME)
            self.assertTrue(first['installed'] and first['verified'])
            self.assertEqual(install(ROOT, home=home, agent='claude')['action'], 'already_identical')
            self.assertFalse((Path(home) / '.agents').exists())

    def test_v3_is_preserved_and_cannot_be_collection_root(self):
        with tempfile.TemporaryDirectory() as home:
            old = Path(home) / '.agents/skills/shanyin-director-master-v3'
            old.mkdir(parents=True)
            (old / 'SKILL.md').write_text('user V3 instructions', encoding='utf-8')
            before = _snapshot(old)
            install(ROOT, home=home)
            self.assertEqual(_snapshot(old), before)
            with self.assertRaises(ValueError):
                install(ROOT, home=home, target_root=old, upgrade=True)
            self.assertEqual(_snapshot(old), before)
