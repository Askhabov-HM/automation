"""One-command PDF build, JSON results, explicit review and durable baselines."""
import argparse
from datetime import datetime, timezone
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import traceback
import uuid

from pdf_engine import PdfError, digest, key_for, load_content, make_pdf, validate_pdf, write_json
from pdf_compare import renderer_path, renderer_identity, render, copy_pages, compare, previews, approve

DEFAULT_ROOT = Path(__file__).resolve().parents[1]


class Parser(argparse.ArgumentParser):
    def error(self, message): raise PdfError('invalid_arguments', message, 'arguments')


def parser():
    p = Parser(description=__doc__)
    p.add_argument('--root', type=Path, default=DEFAULT_ROOT, help=argparse.SUPPRESS)
    commands = p.add_subparsers(dest='command', required=True, parser_class=Parser)
    build = commands.add_parser('build', help='Build, validate, render and compare a document')
    build.add_argument('content', type=Path, help='Structured JSON or simple Markdown')
    build.add_argument('--mode', choices=['economy', 'technical'], default='economy')
    build.add_argument('--name', help='Stable document ID (letters, numbers, hyphen, underscore)')
    build.add_argument('--dpi', type=int, default=110)
    build.add_argument('--pdftoppm', type=Path)
    build.add_argument('--renderer', choices=['auto', 'poppler', 'pdfium'], default='auto')
    build.add_argument('--font-dir', type=Path)
    build.add_argument('--no-render-cache', action='store_true', help='Render again in a fresh cache generation')
    setup = commands.add_parser('setup', help='Prepare an isolated environment and reuse cached tools')
    setup.add_argument('--pdftoppm', type=Path)
    setup.add_argument('--renderer', choices=['auto', 'poppler', 'pdfium'], default='auto')
    status = commands.add_parser('status', help='Show the last build result')
    status.add_argument('--name', required=True)
    status.add_argument('--mode', choices=['economy', 'technical'], default='economy')
    review = commands.add_parser('approve', help='Approve a particular build after visual review')
    review.add_argument('--name', required=True)
    review.add_argument('--mode', choices=['economy', 'technical'], required=True)
    review.add_argument('--run', required=True)
    review.add_argument('--reviewed-pages', required=True, help='all or comma-separated page numbers actually reviewed')
    review.add_argument('--acknowledge-removed-pages', action='store_true')
    return p


def identifier(value, label):
    if not value or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,95}', value):
        raise PdfError('invalid_identifier', f'{label} must contain only letters, numbers, hyphens and underscores.', 'arguments')
    return value


def emit(value):
    print(json.dumps(value, ensure_ascii=False, separators=(',', ':')))


def summary(report):
    return {key: report[key] for key in ['status', 'name', 'mode', 'run_id', 'pages', 'checks_passed', 'review_pages', 'removed_pages', 'cache', 'files']}


def versions(root):
    result = {}
    for line in (root / 'requirements.txt').read_text(encoding='utf-8').splitlines():
        if not line.strip() or line.startswith('#'): continue
        package, expected = line.strip().split('==', 1)
        try: actual = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError as error:
            raise PdfError('dependency_missing', 'Run the setup command to install the required Python packages.', 'dependencies') from error
        if actual != expected:
            raise PdfError('dependency_version', f'Package {package} does not match requirements.txt; run setup.', 'dependencies')
        result[package] = actual
    return result


def build(args):
    root = args.root; name = identifier(args.name or args.content.stem, 'Document name')
    if not 36 <= args.dpi <= 300: raise PdfError('invalid_dpi', 'DPI must be between 36 and 300.', 'arguments')
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
    run = root / 'output' / name / args.mode / run_id; run.mkdir(parents=True, exist_ok=False)
    log_file = run / 'build.log'
    with log_file.open('w', encoding='utf-8') as log:
        try:
            installed = versions(root)
            renderer = renderer_path(root, args.pdftoppm, args.renderer)
            identity = renderer_identity(renderer, log)
            content = load_content(args.content)
            stats = {'image_hits': 0, 'image_misses': 0, 'render_hit': False}
            pdf = run / 'document.pdf'
            layout = make_pdf(root, content, args.content.resolve().parent, args.mode, pdf, args.font_dir, stats)
            validation = validate_pdf(pdf, content, args.mode)
            render_id = dict(identity)
            if args.no_render_cache: render_id['fresh_generation'] = run_id
            cached = render(root, pdf, renderer, render_id, args.dpi, validation['pages'], stats, log)
            pages = copy_pages(cached, run / 'pages')
            signature = {'renderer': identity, 'dpi': args.dpi, 'fonts': layout['fonts'], 'template': layout['template'], 'page_size': 'A4', 'mode': args.mode}
            difference = compare(root, name, args.mode, pages, signature, run)
            review_pages = difference['changed_pages']
            review_files = previews(root, pages, review_pages, run)
            passed = difference['comparable'] and not review_pages and not difference['removed_pages']
            report = {'status': 'passed' if passed else 'needs_visual_review', 'name': name, 'mode': args.mode, 'run_id': run_id,
                      'pages': validation['pages'], 'checks_passed': True, 'review_pages': review_pages, 'removed_pages': difference['removed_pages'],
                      'cache': stats, 'signature': signature, 'comparison': difference, 'validation': validation,
                      'pdf_sha256': digest(pdf), 'page_hashes': [{'file': p.name, 'sha256': digest(p)} for p in pages],
                      'versions': installed, 'source_sha256': digest(args.content), 'template_sha256': layout['template'],
                      'visual_review': {'confirmed': False, 'inherited_from_approved_baseline': passed},
                      'files': {'pdf': str(pdf.relative_to(root)), 'report': str((run / 'report.json').relative_to(root)),
                                'log': str(log_file.relative_to(root)), 'previews': review_files,
                                'diffs': [item['file'] for item in difference['diffs']]}}
            write_json(run / 'report.json', report)
            write_json(run.parent / 'latest.json', {'run_id': run_id})
            return summary(report)
        except Exception as error:
            traceback.print_exc(file=log)
            if isinstance(error, PdfError): failure = error
            elif isinstance(error, json.JSONDecodeError): failure = PdfError('invalid_json', 'Content file is not valid JSON.', 'input')
            elif isinstance(error, FileNotFoundError): failure = PdfError('file_missing', 'A required file does not exist; see the log.', 'input')
            elif type(error).__name__ == 'LayoutError': failure = PdfError('layout_overflow', 'A block cannot fit on the page; shorten or split it. See the log.', 'layout')
            else: failure = PdfError('build_failed', 'Build failed; see the detailed log.', 'build')
            failure.log_file = str(log_file.relative_to(root))
            raise failure from error


def setup(args):
    root = args.root; cache = root / '.cache'; cache.mkdir(parents=True, exist_ok=True)
    log_path = cache / 'setup.log'
    runtime = root / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    with log_path.open('w', encoding='utf-8') as log:
        if not runtime.exists():
            subprocess.run([sys.executable, '-m', 'venv', str(root / '.venv')], stdout=log, stderr=log, check=True)
        subprocess.run([str(runtime), '-m', 'pip', 'install', '--disable-pip-version-check', '--cache-dir', str(cache / 'pip'), '-r', str(root / 'requirements.txt')], stdout=log, stderr=log, check=True)
        # setup is run by the system interpreter; probe PDFium using the new venv.
        if args.renderer == 'pdfium':
            probe = subprocess.run([str(runtime), '-c', 'import pypdfium2'], stdout=log, stderr=log)
            if probe.returncode: raise PdfError('renderer_missing', 'PDFium is missing in the isolated runtime.', 'dependencies')
            tool = 'pdfium'
        else:
            try: tool = renderer_path(root, args.pdftoppm, args.renderer)
            except PdfError:
                if args.renderer != 'auto' or args.pdftoppm: raise
                tool = 'pdfium'
        if tool == 'pdfium':
            probe = subprocess.run([str(runtime), '-c', 'import json,pypdfium2; print(json.dumps({"backend":"pdfium","version":str(pypdfium2.PDFIUM_INFO)}))'], stdout=subprocess.PIPE, stderr=log, text=True, check=True)
            write_json(cache / 'runtime.json', {'requirements_sha256': digest(root / 'requirements.txt'), 'renderer': json.loads(probe.stdout)})
            return {'status': 'ready', 'runtime': str(runtime.relative_to(root)), 'renderer': 'pdfium', 'renderer_cached': True, 'log': str(log_path.relative_to(root))}
        renderer_identity(tool, log)
        if os.name == 'nt':
            local = cache / 'poppler/Library'
            # Copy the portable runtime together with DLLs and Poppler data.
            if not (local / 'bin/pdftoppm.exe').is_file():
                source = tool.parent.parent
                if tool.parent.name.lower() != 'bin': raise PdfError('renderer_layout', 'Pass pdftoppm from a complete Poppler Library/bin directory.', 'dependencies')
                local.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(source, local, dirs_exist_ok=True)
            tool = local / 'bin/pdftoppm.exe'
        write_json(cache / 'runtime.json', {'requirements_sha256': digest(root / 'requirements.txt'), 'renderer': renderer_identity(tool, log)})
    return {'status': 'ready', 'runtime': str(runtime.relative_to(root)), 'renderer_cached': os.name == 'nt', 'log': str(log_path.relative_to(root))}


def execute(args):
    if args.command == 'setup': return setup(args)
    if args.command == 'build': return build(args)
    name = identifier(args.name, 'Document name')
    if args.command == 'status':
        pointer = args.root / 'output' / name / args.mode / 'latest.json'
        if not pointer.is_file(): raise PdfError('build_missing', 'No successful build exists for this name and mode.', 'status')
        run_id = identifier(json.loads(pointer.read_text(encoding='utf-8'))['run_id'], 'Run ID')
        report = json.loads((pointer.parent / run_id / 'report.json').read_text(encoding='utf-8'))
        return summary(report)
    run_id = identifier(args.run, 'Run ID')
    report_path = args.root / 'output' / name / args.mode / run_id / 'report.json'
    if not report_path.is_file(): raise PdfError('run_missing', 'The specified build does not exist.', 'approval')
    report = json.loads(report_path.read_text(encoding='utf-8'))
    try: reviewed = set(range(1, report['pages'] + 1)) if args.reviewed_pages == 'all' else {int(n) for n in args.reviewed_pages.split(',')}
    except ValueError as error: raise PdfError('invalid_review_pages', 'Use all or a comma-separated list of page numbers.', 'approval') from error
    if any(n < 1 or n > report['pages'] for n in reviewed): raise PdfError('invalid_review_pages', 'Reviewed page numbers must exist in this build.', 'approval')
    return approve(args.root, name, args.mode, run_id, reviewed, args.acknowledge_removed_pages)


def main():
    if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
    try:
        args = parser().parse_args(); args.root = args.root.resolve()
        runtime = args.root / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        if args.command != 'setup' and runtime.is_file() and Path(sys.prefix).resolve() != (args.root / '.venv').resolve():
            return subprocess.run([str(runtime), str(Path(__file__).resolve()), *sys.argv[1:]], env=dict(os.environ, PYTHONUTF8='1')).returncode
        emit(execute(args)); return 0
    except PdfError as error:
        value = {'status': 'failed', 'stage': error.stage, 'errors': [{'code': error.code, 'message': str(error)}]}
        if error.page is not None: value['errors'][0]['page'] = error.page
        if getattr(error, 'log_file', None): value['log_file'] = error.log_file
        emit(value); return 1
    except Exception:
        emit({'status': 'failed', 'stage': 'runtime', 'errors': [{'code': 'runtime_error', 'message': 'Command failed. Check file paths and the setup log.'}]}); return 1


if __name__ == '__main__': raise SystemExit(main())
