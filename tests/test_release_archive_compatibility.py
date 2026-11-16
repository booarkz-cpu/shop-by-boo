"""The actual distribution must pass the updater already installed on servers."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def load_script(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReleaseArchiveCompatibilityTest(unittest.TestCase):
    def test_real_package_is_accepted_without_losing_runtime_assets(self):
        updater = load_script('release_archive_updater', 'github_release_fetch.py')
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / 'release.zip'
            subprocess.run([sys.executable, str(ROOT / 'scripts/package-source.py'), str(archive)], cwd=ROOT, check=True)
            destination = Path(directory) / 'extracted'
            updater.safe_extract(archive.read_bytes(), destination)
            with zipfile.ZipFile(archive) as bundle:
                names = set(bundle.namelist())
            self.assertFalse(any(name.startswith('screenshots/') for name in names))
            for name in ('.env.example', 'release-manifest.template.json', 'deploy/install-vps.sh',
                         'scripts/update.sh', 'services/backend/app/main.py',
                         'infrastructure/deployment/build-production.sh'):
                self.assertEqual((destination / name).read_bytes(), (ROOT / name).read_bytes(), name)
            for raw in subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).split(b'\0'):
                if not raw:
                    continue
                name = raw.decode()
                path = ROOT / name
                if ('/assets/' in name or '/res/' in name) and path.is_file() and not path.is_symlink() and name.startswith(('apps/', 'services/', 'mobile/')):
                    self.assertEqual((destination / name).read_bytes(), path.read_bytes(), name)

    def test_oversized_package_does_not_replace_previous_artifact(self):
        packager = load_script('release_archive_packager', 'package-source.py')
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / 'release.zip'
            archive.write_bytes(b'previous verified artifact')
            with patch.object(sys, 'argv', ['package-source.py', str(archive)]), patch.object(packager, 'LEGACY_ARCHIVE_LIMIT', 1):
                with self.assertRaisesRegex(SystemExit, 'installed updater limit'):
                    packager.main()
            self.assertEqual(archive.read_bytes(), b'previous verified artifact')


if __name__ == '__main__':
    unittest.main()
