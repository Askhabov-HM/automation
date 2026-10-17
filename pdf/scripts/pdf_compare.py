"""Exact raster comparison against explicitly approved, durable baselines."""
from pathlib import Path
import importlib.util
import importlib.metadata
import json
import shutil
import subprocess
import uuid
from pdf_engine import PdfError, digest, key_for, write_json


def renderer_path(root, explicit=None, backend='auto'):
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if path.is_file(): return path
        raise PdfError('renderer_missing', 'Explicit pdftoppm executable does not exist.', 'dependencies')
    if backend == 'pdfium':
        if importlib.util.find_spec('pypdfium2') is not None: return 'pdfium'
        raise PdfError('renderer_missing', 'Run setup to install the bundled Python PDFium renderer.', 'dependencies')
    local = root / '.cache/poppler/Library/bin/pdftoppm.exe'
    if local.is_file(): return local
    installed = shutil.which('pdftoppm')
    if installed: return Path(installed).resolve()
    cached = sorted((Path.home() / '.cache/codex/pdf-tools').glob('*/Library/bin/pdftoppm.exe'))
    if cached: return cached[-1]
    if backend == 'auto' and importlib.util.find_spec('pypdfium2') is not None: return 'pdfium'
    raise PdfError('renderer_missing', 'Run setup for PDFium or install Poppler and pass --pdftoppm.', 'dependencies')


def renderer_identity(path, log):
    if path == 'pdfium':
        import pypdfium2 as pdfium
        import pypdfium2_raw as raw
        folder = Path(raw.__file__).parent
        library = next((p for p in folder.iterdir() if p.name in {'pdfium.dll', 'libpdfium.so', 'libpdfium.dylib'}), None)
        return {'backend': 'pdfium', 'version': importlib.metadata.version('pypdfium2'), 'engine': str(pdfium.PDFIUM_INFO), 'binary': digest(library) if library else 'package-' + importlib.metadata.version('pypdfium2')}
    p = subprocess.run([str(path), '-v'], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)
    log.write(p.stdout + p.stderr)
    if p.returncode: raise PdfError('renderer_failed', 'Cannot run pdftoppm.', 'dependencies')
    return {'binary': digest(path), 'version': (p.stderr or p.stdout).splitlines()[0]}


def render(root, pdf, renderer, identity, dpi, count, stats, log):
    from PIL import Image
    cache = root / '.cache/renders' / key_for({'pdf': digest(pdf), 'renderer': identity, 'dpi': dpi})
    manifest = cache / 'render.json'
    valid = False
    if manifest.exists():
        try:
            saved = json.loads(manifest.read_text(encoding='utf-8'))
            valid = len(saved['pages']) == count
            for item in saved['pages']:
                file = cache / item['file']
                valid = valid and file.is_file() and digest(file) == item['sha256']
                with Image.open(file) as im: im.verify()
        except (OSError, ValueError, KeyError): valid = False
    if not valid:
        # Never publish incomplete render caches. No recursive cleanup is needed.
        staging = root / 'tmp' / ('render-' + uuid.uuid4().hex)
        staging.mkdir(parents=True, exist_ok=False)
        if renderer == 'pdfium':
            import pypdfium2 as pdfium
            document = pdfium.PdfDocument(str(pdf))
            try:
                for number in range(len(document)):
                    page = document[number]
                    try:
                        bitmap = page.render(scale=dpi / 72)
                        try:
                            image = bitmap.to_pil().convert('RGB')
                            try: image.save(staging / f'page-{number+1:03d}.png')
                            finally: image.close()
                        finally: bitmap.close()
                    finally: page.close()
            finally: document.close()
        else:
            p = subprocess.run([str(renderer), '-r', str(dpi), '-png', str(pdf), str(staging / 'page')], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=180)
            log.write(p.stdout + p.stderr)
            if p.returncode: raise PdfError('render_failed', 'Poppler failed; see the detailed log.', 'render')
        pages = sorted(staging.glob('page-*.png'))
        if len(pages) != count: raise PdfError('render_page_count', 'Renderer did not produce the expected pages.', 'render')
        cache.mkdir(parents=True, exist_ok=True)
        items = []
        for number, file in enumerate(pages, 1):
            with Image.open(file) as im: im.verify()
            filename = f'page-{number:03d}.png'; target = cache / filename
            shutil.copy2(file, target)
            items.append({'file': filename, 'sha256': digest(target)})
        write_json(manifest, {'pages': items})
        try:
            for file in pages: file.unlink()
            staging.rmdir()
        except OSError:
            log.write('Intermediate render files retained; the validated cache is complete.\n')
        saved = {'pages': items}; stats['render_hit'] = False
    else: stats['render_hit'] = True
    return [cache / item['file'] for item in saved['pages']]


def copy_pages(pages, destination):
    destination.mkdir(parents=True, exist_ok=True)
    result = []
    for n, path in enumerate(pages, 1):
        target = destination / f'page-{n:03d}.png'; shutil.copy2(path, target); result.append(target)
    return result


def compare(root, name, mode, pages, signature, run):
    from PIL import Image, ImageChops, ImageDraw
    pointer = root / 'baselines' / name / mode / 'current.json'
    result = {'baseline': None, 'comparable': False, 'reason': 'no_approved_baseline',
              'changed_pages': list(range(1, len(pages) + 1)), 'unchanged_pages': [], 'removed_pages': [], 'diffs': []}
    if not pointer.exists(): return result
    try:
        baseline = json.loads(pointer.read_text(encoding='utf-8'))
        folder = pointer.parent / baseline['generation']
        if digest(folder / 'document.pdf') != baseline['pdf_sha256']:
            raise ValueError('PDF hash mismatch')
        old_pages = [folder / item['file'] for item in baseline['pages']]
        if any(digest(p) != item['sha256'] for p, item in zip(old_pages, baseline['pages'])):
            raise ValueError('Page hash mismatch')
    except (OSError, ValueError, KeyError) as error:
        raise PdfError('baseline_invalid', 'Approved baseline is incomplete or altered; restore it before comparing.', 'comparison') from error
    result['baseline'] = baseline['run_id']
    result['removed_pages'] = list(range(len(pages) + 1, len(old_pages) + 1))
    if baseline['signature'] != signature:
        result['reason'] = 'render_settings_fonts_or_template_changed'
        return result
    result.update(comparable=True, reason='exact_pixel_comparison', changed_pages=[])
    diff_dir = run / 'diff'; diff_dir.mkdir(exist_ok=True)
    for number, current in enumerate(pages, 1):
        if number > len(old_pages):
            result['changed_pages'].append(number)
            continue
        with Image.open(old_pages[number - 1]) as old, Image.open(current) as new:
            old, new = old.convert('RGB'), new.convert('RGB')
            if old.size != new.size:
                result['changed_pages'].append(number)
                continue
            diff = ImageChops.difference(old, new); bounds = diff.getbbox()
            if not bounds:
                result['unchanged_pages'].append(number)
                continue
            result['changed_pages'].append(number)
            mask = ImageChops.lighter(ImageChops.lighter(diff.getchannel('R'), diff.getchannel('G')), diff.getchannel('B'))
            pixels = old.width * old.height - mask.histogram()[0]
            overlay = Image.composite(Image.new('RGB', new.size, '#D84A3A'), new, mask.point(lambda v: 160 if v else 0))
            ImageDraw.Draw(overlay).rectangle(bounds, outline='#C62424', width=3)
            destination = diff_dir / f'page-{number:03d}.png'; overlay.save(destination)
            result['diffs'].append({'page': number, 'file': str(destination.relative_to(root)), 'changed_pixels': pixels, 'fraction': round(pixels / (old.width * old.height), 8), 'bounds': bounds})
    return result


def previews(root, pages, selected, run):
    from PIL import Image, ImageOps, ImageDraw, ImageFont
    chosen = selected or []
    result = []
    # No new visual review is required for exact copies of approved pages.
    if not chosen: return result
    for group in range(0, len(chosen), 4):
        numbers = chosen[group:group + 4]
        rows = (len(numbers) + 1) // 2
        sheet = Image.new('RGB', (1060, rows * 755), '#E3E7E6'); draw = ImageDraw.Draw(sheet)
        for i, number in enumerate(numbers):
            with Image.open(pages[number - 1]) as image:
                thumb = ImageOps.contain(image.convert('RGB'), (500, 708))
            x, y = 15 + (i % 2) * 530, 30 + (i // 2) * 755
            sheet.paste(thumb, (x, y)); draw.text((x, y - 19), f'PAGE {number}', fill='black')
        path = run / f'preview-{group // 4 + 1:02d}.jpg'; sheet.save(path, quality=92)
        result.append(str(path.relative_to(root)))
    return result


def approve(root, name, mode, run_id, reviewed, acknowledge_removed=False):
    run = root / 'output' / name / mode / run_id
    report_file = run / 'report.json'
    if not report_file.is_file(): raise PdfError('run_missing', 'The specified build does not exist.', 'approval')
    report = json.loads(report_file.read_text(encoding='utf-8'))
    if report['status'] not in ('needs_visual_review', 'passed') or not report.get('checks_passed'):
        raise PdfError('checks_failed', 'Only builds with successful automated checks can be approved.', 'approval')
    if report['run_id'] != run_id or report['mode'] != mode or report['name'] != name:
        raise PdfError('run_invalid', 'Build identity does not match the requested approval.', 'approval')
    pdf = run / 'document.pdf'
    if digest(pdf) != report['pdf_sha256']:
        raise PdfError('run_changed', 'PDF changed after validation; rebuild it.', 'approval')
    pages = [run / 'pages' / item['file'] for item in report['page_hashes']]
    if any(digest(p) != item['sha256'] for p, item in zip(pages, report['page_hashes'])):
        raise PdfError('run_changed', 'Rendered pages changed after validation; rebuild them.', 'approval')
    needed = set(report['comparison']['changed_pages'])
    if not needed.issubset(reviewed): raise PdfError('review_incomplete', 'Confirm review of every page listed in review_pages.', 'approval')
    if report['comparison']['removed_pages'] and not acknowledge_removed:
        raise PdfError('removed_pages_unreviewed', 'Confirm removed pages with --acknowledge-removed-pages.', 'approval')
    destination = root / 'baselines' / name / mode / run_id
    if destination.exists(): raise PdfError('already_approved', 'This build already has a baseline generation.', 'approval')
    destination.mkdir(parents=True)
    shutil.copy2(pdf, destination / 'document.pdf')
    copied = copy_pages(pages, destination / 'pages')
    snapshot = {'generation': run_id, 'run_id': run_id, 'signature': report['signature'], 'pdf_sha256': report['pdf_sha256'], 'pages': [{'file': str(p.relative_to(destination)), 'sha256': digest(p)} for p in copied], 'reviewed_pages': sorted(reviewed), 'removed_pages_acknowledged': acknowledge_removed}
    write_json(destination / 'approval.json', snapshot)
    write_json(destination.parent / 'current.json', snapshot)
    report['status'] = 'passed'; report['visual_review'] = {'confirmed': True, 'pages': sorted(reviewed)}
    write_json(report_file, report)
    return {'status': 'approved', 'name': name, 'mode': mode, 'run_id': run_id, 'baseline': str(destination.relative_to(root))}
