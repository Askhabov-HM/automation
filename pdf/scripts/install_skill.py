"""Install an independent personal copy of this PDF skill; standard library only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

SOURCE = Path(__file__).resolve().parents[1]
NAME = 'pdf-documents'
ROOT_FILES = {'SKILL.md', 'README.md', 'requirements.txt', '.gitignore', '.gitattributes'}
DIRECTORIES = {'scripts', 'templates', 'assets', 'references', 'examples', 'tests', 'agents'}
EXCLUDED = {'__pycache__', '.cache', '.venv', 'output', 'inputs', 'baselines', 'tmp', '.git'}


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def authored_files(source=SOURCE):
    files = []
    for name in ROOT_FILES:
        file = source / name
        if not file.is_file(): raise ValueError('Required package file missing: ' + name)
        files.append(file)
    for name in DIRECTORIES:
        folder = source / name
        if not folder.is_dir(): raise ValueError('Required package folder missing: ' + name)
        for file in folder.rglob('*'):
            relative = file.relative_to(source)
            if any(part in EXCLUDED for part in relative.parts) or file.suffix in {'.pyc', '.pyo'}: continue
            if file.is_symlink(): raise ValueError('Package symlinks are not supported.')
            if file.is_file():
                if file.name == '.env' or file.name.startswith('.env.'):
                    raise ValueError('Environment files cannot be part of a skill package.')
                files.append(file)
    return sorted(files)


def child(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()): raise ValueError('Manifest path escapes the skill directory.')
    return path


def discovery_link(destination):
    """Bridge the local Codex skill directory to the current USER discovery path."""
    alias = Path.home() / '.agents/skills' / NAME
    if alias.resolve() == destination.resolve(): return str(alias)
    if alias.exists() or alias.is_symlink(): raise ValueError('User discovery path contains another skill; refusing to replace it.')
    alias.parent.mkdir(parents=True, exist_ok=True)
    if os.name == 'nt':
        quote = lambda value: "'" + str(value).replace("'", "''") + "'"
        command = '$ErrorActionPreference = "Stop"; New-Item -ItemType Junction -Path ' + quote(alias) + ' -Value ' + quote(destination) + ' | Out-Null'
        subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command], capture_output=True, check=True)
    else:
        alias.symlink_to(destination, target_is_directory=True)
    if alias.resolve() != destination.resolve(): raise ValueError('User discovery link verification failed.')
    return str(alias)


def main():
    if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    default = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))) / 'skills'
    parser.add_argument('--skills-dir', type=Path, help='Custom parent directory for skills (without a discovery alias)')
    parser.add_argument('--update', action='store_true', help='Update a previously installed copy without changing runtime data')
    parser.add_argument('--check', action='store_true', help='Compare authored package files without changing anything')
    parser.add_argument('--setup', action='store_true', help='Prepare the installed isolated Python environment with PDFium')
    args = parser.parse_args()
    destination = (args.skills_dir or default).expanduser().resolve() / NAME
    try:
        if sys.version_info < (3, 11): raise ValueError('Python 3.11 or newer is required.')
        files = authored_files(); desired = {p.relative_to(SOURCE).as_posix(): sha(p) for p in files}
        manifest_path = destination / 'installed-manifest.json'
        if args.check:
            differing = [name for name, expected in desired.items() if not child(destination, name).is_file() or sha(child(destination, name)) != expected]
            manifest = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.is_file() else {}
            matching = not differing and manifest.get('files') == desired
            print(json.dumps({'status': 'in_sync' if matching else 'different', 'skill': NAME, 'files': len(desired), 'different_files': differing}, ensure_ascii=False))
            return 0 if matching else 1
        if destination.resolve() == SOURCE: raise ValueError('The installation directory must differ from the source package.')
        previous = {}
        if destination.exists():
            if destination.is_symlink(): raise ValueError('Installation target must be a real directory, not a symlink.')
            if not args.update: raise ValueError('Skill already exists; use --check or --update.')
            if not manifest_path.is_file(): raise ValueError('Existing skill has no installation manifest; refusing to overwrite it.')
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            if manifest.get('name') != NAME: raise ValueError('Installation manifest belongs to another skill.')
            previous = manifest['files']
            for name, expected in previous.items():
                file = child(destination, name)
                if not file.is_file() or sha(file) != expected:
                    raise ValueError('Installed authored files were changed locally; preserve those edits before updating.')
            for name in desired.keys() - previous.keys():
                if child(destination, name).exists(): raise ValueError('A new package file collides with a local file.')
        destination.mkdir(parents=True, exist_ok=True)
        for source_file in files:
            target = child(destination, source_file.relative_to(SOURCE))
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, target)
        # Only obsolete, manifest-owned files can be removed during an update.
        for name in previous.keys() - desired.keys(): child(destination, name).unlink()
        if any(sha(child(destination, name)) != expected for name, expected in desired.items()):
            raise ValueError('Installed file verification failed.')
        manifest_path.write_text(json.dumps({'name': NAME, 'files': desired}, ensure_ascii=False, indent=2), encoding='utf-8')
        alias = discovery_link(destination) if args.skills_dir is None else None
        setup = None
        if args.setup:
            process = subprocess.run([sys.executable, str(destination / 'scripts/pdf_tool.py'), 'setup', '--renderer', 'pdfium'], capture_output=True, encoding='utf-8', env=dict(os.environ, PYTHONUTF8='1'))
            try: setup = json.loads(process.stdout)
            except ValueError: setup = {'status': 'failed'}
            if process.returncode: raise ValueError('Skill copied, but runtime setup failed; inspect .cache/setup.log in the installed copy.')
        print(json.dumps({'status': 'installed', 'skill': NAME, 'directory': str(destination), 'discovery_path': alias, 'files': len(desired), 'runtime': setup}, ensure_ascii=False))
        return 0
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError) as error:
        print(json.dumps({'status': 'failed', 'message': str(error)}, ensure_ascii=False))
        return 1


if __name__ == '__main__': raise SystemExit(main())
