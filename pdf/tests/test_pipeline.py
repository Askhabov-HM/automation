"""Behavioral checks; all approvals and mutations stay in temporary test modules."""
from pathlib import Path
import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE / 'scripts'))
from pdf_engine import make_pdf, validate_pdf, prepare_image


class PipelineTests(unittest.TestCase):
    def test_reference_example_keeps_cyrillic(self):
        example = json.loads((MODULE / 'examples/demo.json').read_text(encoding='utf-8'))
        self.assertEqual(example['title'], 'Форма и данные')
        self.assertNotIn('???', json.dumps(example, ensure_ascii=False))

    def setUp(self):
        parent = MODULE / 'tmp'; parent.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix='test-', dir=parent)
        self.root = Path(self.temporary.name).resolve()
        # Verify the cleanup target before TemporaryDirectory can remove it.
        self.assertTrue(self.root.is_relative_to(parent.resolve()))
        shutil.copytree(MODULE / 'templates', self.root / 'templates')
        shutil.copytree(MODULE / 'assets/fonts', self.root / 'assets/fonts')
        shutil.copy2(MODULE / 'requirements.txt', self.root / 'requirements.txt')
        self.input = self.root / 'example.json'
        self.content = {'title': 'Тестовый документ', 'cover': False, 'sections': [
            {'title': 'Первая часть', 'blocks': [{'type': 'paragraph', 'text': 'Первоначальный текст для проверки сохранения содержимого.'}]},
            {'title': 'Вторая часть', 'page_break': True, 'blocks': [{'type': 'paragraph', 'text': 'Эта страница остаётся прежней при редактировании первой.'}]},
        ]}

    def tearDown(self): self.temporary.cleanup()

    def command(self, *args, ok=True):
        process = subprocess.run([sys.executable, str(MODULE / 'scripts/pdf_tool.py'), '--root', str(self.root), *args], cwd=self.root.parent, capture_output=True, encoding='utf-8')
        value = json.loads(process.stdout)
        self.assertEqual(process.stderr, '', process.stderr)
        self.assertEqual(process.returncode, 0 if ok else 1, value)
        self.assertEqual(len(process.stdout.strip().splitlines()), 1)
        return value

    def build(self, content=None, mode='technical', ok=True, extra=()):
        self.input.write_text(json.dumps(self.content if content is None else content, ensure_ascii=False), encoding='utf-8')
        return self.command('build', str(self.input), '--name', 'example', '--mode', mode, '--renderer', 'pdfium', '--font-dir', str(self.root / 'assets/fonts'), *extra, ok=ok)

    def approve(self, run, pages='all', ok=True, extra=()):
        return self.command('approve', '--name', 'example', '--mode', 'technical', '--run', run['run_id'], '--reviewed-pages', pages, *extra, ok=ok)

    def test_review_cache_and_single_page_change(self):
        first = self.build()
        self.assertEqual(first['status'], 'needs_visual_review')
        self.assertEqual(first['review_pages'], [1, 2])
        pointer = self.root / 'baselines/example/technical/current.json'
        self.assertFalse(pointer.exists())
        rejected = self.approve(first, '1', ok=False)
        self.assertEqual(rejected['errors'][0]['code'], 'review_incomplete')
        self.assertFalse(pointer.exists())
        self.approve(first)
        approved_pointer = pointer.read_bytes()
        second = self.build()
        self.assertEqual(second['status'], 'passed')
        self.assertTrue(second['cache']['render_hit'])
        self.assertEqual(second['review_pages'], [])
        self.assertEqual(pointer.read_bytes(), approved_pointer)
        changed = copy.deepcopy(self.content)
        changed['sections'][0]['blocks'][0]['text'] = 'Изменённый текст только на первой странице документа.'
        third = self.build(changed)
        self.assertEqual(third['review_pages'], [1])
        self.assertEqual(len(third['files']['diffs']), 1)
        self.assertEqual(pointer.read_bytes(), approved_pointer)
        self.assertEqual(self.approve(third, '2', ok=False)['errors'][0]['code'], 'review_incomplete')
        self.approve(third, '1')

    def test_page_removal_requires_acknowledgement(self):
        original = self.build(); self.approve(original)
        shorter = copy.deepcopy(self.content); shorter['sections'].pop()
        changed = self.build(shorter)
        self.assertEqual(changed['removed_pages'], [2])
        self.assertEqual(self.approve(changed, ok=False)['errors'][0]['code'], 'removed_pages_unreviewed')
        self.approve(changed, extra=('--acknowledge-removed-pages',))

    def test_corrupt_render_cache_is_rebuilt(self):
        self.build()
        cached = next((self.root / '.cache/renders').glob('*/page-001.png'))
        cached.write_bytes(b'not a PNG')
        rebuilt = self.build()
        self.assertFalse(rebuilt['cache']['render_hit'])
        from PIL import Image
        with Image.open(cached) as image: image.verify()

    def test_render_settings_change_requires_full_review(self):
        original = self.build(); self.approve(original)
        changed = self.build(extra=('--dpi', '120'))
        self.assertEqual(changed['status'], 'needs_visual_review')
        self.assertEqual(changed['review_pages'], [1, 2])

    def test_template_change_requires_full_review(self):
        original = self.build(); self.approve(original)
        style_file = self.root / 'templates/technical/style.json'
        style = json.loads(style_file.read_text(encoding='utf-8'))
        style['accent'] = '#222222'
        style_file.write_text(json.dumps(style), encoding='utf-8')
        changed = self.build()
        self.assertEqual(changed['review_pages'], [1, 2])
        report = json.loads((self.root / changed['files']['report']).read_text(encoding='utf-8'))
        self.assertFalse(report['comparison']['comparable'])

    def test_baseline_tampering_is_detected(self):
        original = self.build(); self.approve(original)
        baseline = next((self.root / 'baselines/example/technical').glob('*/document.pdf'))
        baseline.write_bytes(b'changed')
        failed = self.build(ok=False)
        self.assertEqual(failed['errors'][0]['code'], 'baseline_invalid')

    def test_draft_constraints_and_structured_failure(self):
        result = self.build(mode='economy')
        self.assertTrue(result['checks_passed'])
        report = json.loads((self.root / result['files']['report']).read_text(encoding='utf-8'))
        self.assertTrue(all(p['images'] == 0 for p in report['validation']['page_details']))
        bad = copy.deepcopy(self.content)
        bad['sections'][0]['blocks'] = [{'type': 'table', 'columns': ['A','B'], 'rows': [['one']]}]
        self.assertEqual(self.build(bad, ok=False)['errors'][0]['code'], 'invalid_rows')
        missing = self.command('build', str(self.input), '--pdftoppm', str(self.root / 'absent.exe'), ok=False)
        self.assertEqual(missing['errors'][0]['code'], 'renderer_missing')
        invalid = self.command('build', str(self.input), '--name', '../escape', ok=False)
        self.assertEqual(invalid['errors'][0]['code'], 'invalid_identifier')

    def test_long_table_repeats_header_and_keeps_wrapped_text(self):
        from pypdf import PdfReader
        rows = [[f'{i:03d}', f'Запись {i:03d}: подробное описание с переносом на несколько строк в узкой колонке.', str(1000+i)] for i in range(70)]
        content = {'title': 'Длинная таблица', 'cover': False, 'sections': [{'title': 'Каталог', 'blocks': [{'type': 'table', 'columns': ['Номер','Описание','Цена'], 'rows': rows, 'widths': [1,4,1]}]}]}
        target = self.root / 'long.pdf'
        make_pdf(self.root, content, self.root, 'technical', target, self.root / 'assets/fonts', {'image_hits':0,'image_misses':0})
        validation = validate_pdf(target, content, 'technical')
        self.assertGreater(validation['pages'], 2)
        for page in PdfReader(target).pages:
            self.assertIn('Описание', page.extract_text())

    def test_image_cache_uses_content_and_repairs_changed_files(self):
        from PIL import Image
        source = self.root / 'image.png'
        Image.new('RGB',(50,50),'red').save(source)
        stats = {'image_hits':0,'image_misses':0}
        first = prepare_image(self.root, 'image.png', self.root, stats)
        self.assertEqual(prepare_image(self.root, 'image.png', self.root, stats), first)
        self.assertEqual(stats, {'image_hits':1,'image_misses':1})
        Image.new('RGB',(50,50),'blue').save(first)
        prepare_image(self.root, 'image.png', self.root, stats)
        self.assertEqual(stats['image_misses'], 2)
        Image.new('RGB',(50,50),'green').save(source)
        self.assertNotEqual(prepare_image(self.root, 'image.png', self.root, stats), first)


if __name__ == '__main__': unittest.main()
