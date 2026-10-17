"""Exercise the installed package outside its repository and without Poppler."""
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest

PACKAGE = Path(__file__).resolve().parents[1]


class PortableSkillTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='pdf-skill-portability-')
        self.base = Path(self.temporary.name).resolve()
        self.assertTrue(self.base.is_relative_to(Path(tempfile.gettempdir()).resolve()))
        self.skills = self.base / 'personal-skills'
        self.work = self.base / 'unrelated-project'; self.work.mkdir()
        self.installed = self.skills / 'pdf-documents'

    def tearDown(self): self.temporary.cleanup()

    def install(self, *extra, ok=True):
        process = subprocess.run([sys.executable, str(PACKAGE / 'scripts/install_skill.py'), '--skills-dir', str(self.skills), *extra], cwd=self.work, capture_output=True, encoding='utf-8')
        result = json.loads(process.stdout)
        self.assertEqual(process.returncode, 0 if ok else 1, result)
        self.assertEqual(process.stderr, '')
        return result

    def run_build(self, mode=None):
        command = [sys.executable, str(self.installed / 'scripts/pdf_tool.py'), 'build', str(self.installed / 'examples/demo.json'), '--name', 'portable-proof', '--renderer', 'pdfium', '--font-dir', str(self.installed / 'assets/fonts')]
        if mode: command += ['--mode', mode]
        process = subprocess.run(command, cwd=self.work, capture_output=True, encoding='utf-8')
        result = json.loads(process.stdout)
        self.assertEqual(process.returncode, 0, result)
        self.assertEqual(process.stderr, '')
        return result

    def test_independent_copy_generates_both_modes_and_defaults_to_economy(self):
        self.install()
        self.assertFalse(self.installed.is_symlink())
        for excluded in ['.venv', '.cache', 'output', 'inputs', 'baselines', 'tmp']:
            self.assertFalse((self.installed / excluded).exists())
        self.assertEqual(len(list((self.installed / 'assets/fonts').glob('*.ttf'))), 8)
        self.assertEqual(self.install('--check')['status'], 'in_sync')
        economy = self.run_build()
        self.assertEqual(economy['mode'], 'economy')
        technical = self.run_build('technical')
        self.assertEqual(technical['mode'], 'technical')
        self.assertEqual(self.run_build('technical')['cache']['render_hit'], True)
        for result in [economy, technical]:
            file = self.installed / result['files']['pdf']
            self.assertTrue(file.is_file())
            self.assertTrue(file.resolve().is_relative_to(self.installed))
            report = json.loads((self.installed / result['files']['report']).read_text(encoding='utf-8'))
            self.assertEqual(report['signature']['renderer']['backend'], 'pdfium')
            self.assertTrue(all(report['validation']['checks'].values()))
        self.assertEqual(self.install('--check')['status'], 'in_sync')

    def test_update_preserves_runtime_and_stops_on_manual_source_changes(self):
        self.install()
        personal = self.installed / 'inputs/private.md'; personal.parent.mkdir(); personal.write_text('private draft', encoding='utf-8')
        self.install('--update')
        self.assertEqual(personal.read_text(encoding='utf-8'), 'private draft')
        skill = self.installed / 'SKILL.md'
        skill.write_text(skill.read_text(encoding='utf-8') + '\nManual local change.\n', encoding='utf-8')
        self.assertEqual(self.install('--check', ok=False)['status'], 'different')
        self.assertEqual(self.install('--update', ok=False)['status'], 'failed')
        self.assertIn('Manual local change.', skill.read_text(encoding='utf-8'))

    def test_unmanaged_existing_skill_is_not_overwritten(self):
        self.installed.mkdir(parents=True)
        original = self.installed / 'SKILL.md'; original.write_text('existing skill', encoding='utf-8')
        self.assertEqual(self.install('--update', ok=False)['status'], 'failed')
        self.assertEqual(original.read_text(encoding='utf-8'), 'existing skill')


if __name__ == '__main__': unittest.main()
