"""Recovery and installer regressions exercised without Docker or a live server."""
import os
import io
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RecoveryTests(unittest.TestCase):
    def test_installer_writes_one_cabinet_cors_origin(self):
        script = (ROOT / "deploy/install-vps.sh").read_text()
        writer = script[script.index("umask 077\n{"):script.index("# Strict production firewall:")]
        self.assertEqual(writer.count("env_line CABINET_CORS_ORIGINS "), 1)
        self.assertIn('env_line CABINET_CORS_ORIGINS "https://${CABINET_DOMAIN}"', writer)

    def test_rollback_requires_database_before_modifying_installation(self):
        with tempfile.TemporaryDirectory() as base:
            app = Path(base) / "shop"
            app.mkdir()
            (app / ".env").write_text("secret\n")
            archive = app / "old.tar.gz"
            with tarfile.open(archive, "w:gz"):
                pass
            run = subprocess.run(["bash", str(ROOT / "scripts/rollback.sh"), str(archive), str(app / "missing.sql")],
                                 env={**os.environ, "APP_DIR": str(app)}, capture_output=True, text=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertIn("Database snapshot is required", run.stderr)
            self.assertEqual((app / ".env").read_text(), "secret\n")
            self.assertFalse((app / ".rollback").exists())

    def test_rollback_rejects_corrupt_archive_before_stopping_services(self):
        with tempfile.TemporaryDirectory() as base:
            app = Path(base) / "shop"
            app.mkdir()
            (app / "current.txt").write_text("running")
            archive = app / "bad.tar.gz"
            archive.write_bytes(b"not a tarball")
            database = app / "old.sql"
            database.write_text("SELECT 1;")
            run = subprocess.run(["bash", str(ROOT / "scripts/rollback.sh"), str(archive), str(database)],
                                 env={**os.environ, "APP_DIR": str(app)}, capture_output=True, text=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertEqual((app / "current.txt").read_text(), "running")
            self.assertFalse((app / ".rollback").exists())

    def test_rollback_rejects_protected_entry_before_stopping_services(self):
        with tempfile.TemporaryDirectory() as base:
            app = Path(base) / "shop"
            app.mkdir()
            (app / "current.txt").write_text("running")
            archive = app / "unsafe.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                data = b"overwritten-secret"
                entry = tarfile.TarInfo("./support-pro/.env")
                entry.size = len(data)
                tar.addfile(entry, io.BytesIO(data))
            database = app / "old.sql"
            database.write_text("SELECT 1;")
            run = subprocess.run(["bash", str(ROOT / "scripts/rollback.sh"), str(archive), str(database)],
                                 env={**os.environ, "APP_DIR": str(app)}, capture_output=True, text=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertIn("Protected archive entry", run.stderr)
            self.assertEqual((app / "current.txt").read_text(), "running")
            self.assertFalse((app / ".rollback").exists())

    def test_rollback_rejects_link_before_stopping_services(self):
        with tempfile.TemporaryDirectory() as base:
            app = Path(base) / "shop"
            app.mkdir()
            (app / "current.txt").write_text("running")
            archive = app / "unsafe.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                entry = tarfile.TarInfo("./redirect")
                entry.type = tarfile.SYMTYPE
                entry.linkname = "../outside"
                tar.addfile(entry)
            database = app / "old.sql"
            database.write_text("SELECT 1;")
            run = subprocess.run(["bash", str(ROOT / "scripts/rollback.sh"), str(archive), str(database)],
                                 env={**os.environ, "APP_DIR": str(app)}, capture_output=True, text=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertIn("Unsafe archive entry", run.stderr)
            self.assertEqual((app / "current.txt").read_text(), "running")

    def test_manual_rollback_keeps_git_and_secrets_out_of_archive(self):
        with tempfile.TemporaryDirectory() as base:
            base = Path(base)
            app = base / "shop"
            app.mkdir()
            (app / ".env").write_text("shop-secret")
            (app / ".env.previous").write_text("previous-secret")
            (app / ".git").mkdir()
            (app / ".git" / "head").write_text("git-marker")
            (app / "support-pro").mkdir()
            (app / "support-pro" / ".env").write_text("support-secret")
            (app / "backend").mkdir()
            (app / "backend" / ".env.local").write_text("backend-secret")
            (app / "current.txt").write_text("current")
            (app / ".rollback").mkdir()
            old = app / ".rollback" / "old.tar.gz"
            with tempfile.TemporaryDirectory() as source:
                src = Path(source)
                (src / "old.txt").write_text("restored")
                (src / "deploy").mkdir()
                (src / "scripts").mkdir()
                for path in (src / "deploy" / "build-production.sh", src / "scripts" / "doctor.sh"):
                    path.write_text("#!/bin/sh\nexit 0\n")
                    path.chmod(0o755)
                with tarfile.open(old, "w:gz") as archive:
                    for path in src.rglob("*"):
                        archive.add(path, arcname=path.relative_to(src), recursive=False)
            database = app / ".rollback" / "old.sql"
            database.write_text("SELECT 1;\n")
            fakebin = base / "bin"
            fakebin.mkdir()
            docker = fakebin / "docker"
            docker.write_text('#!/bin/sh\ncase "$*" in *"exec -T db psql"*) cat >/dev/null;; esac\nexit 0\n')
            docker.chmod(0o755)
            run = subprocess.run(["bash", str(ROOT / "scripts/rollback.sh"), str(old), str(database)],
                                 cwd=app, env={**os.environ, "APP_DIR": str(app), "TMPDIR": str(base), "PATH": f"{fakebin}:{os.environ['PATH']}"},
                                 capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual((app / "old.txt").read_text(), "restored")
            self.assertEqual((app / ".git" / "head").read_text(), "git-marker")
            self.assertEqual((app / ".env.previous").read_text(), "previous-secret")
            self.assertEqual((app / "support-pro" / ".env").read_text(), "support-secret")
            self.assertEqual((app / "backend" / ".env.local").read_text(), "backend-secret")
            snapshot = next((app / ".rollback").glob("pre-rollback-*.tar.gz"))
            with tarfile.open(snapshot) as archive:
                names = archive.getnames()
                self.assertFalse(any(Path(name).name.startswith(".env") for name in names))
                self.assertFalse(any(".git" in Path(name).parts for name in names))

    def test_updater_removes_downloaded_stage_after_success(self):
        with tempfile.TemporaryDirectory() as base:
            base = Path(base)
            app = base / "shop"
            (app / "scripts").mkdir(parents=True)
            (app / ".env").write_text("APP_ENV=production\n")
            (app / "scripts" / "github_release_fetch.py").write_text("placeholder")
            (app / "scripts" / "update.sh").write_text(
                '#!/bin/sh\ntest -f "$UPDATE_STAGE/marker" || exit 1\nprintf "%s" "$UPDATE_STAGE" > "$APP_DIR/stage_path"\n')
            fakebin = base / "bin"
            fakebin.mkdir()
            python = fakebin / "python3"
            python.write_text('#!/bin/sh\ntouch "$3/marker"\necho 20.0.18\n')
            python.chmod(0o755)
            run = subprocess.run(["bash", str(ROOT / "scripts/update-from-github.sh")],
                                 cwd=app, env={**os.environ, "APP_DIR": str(app), "TMPDIR": str(base), "PATH": f"{fakebin}:{os.environ['PATH']}"},
                                 capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertFalse(Path((app / "stage_path").read_text()).exists())

    def test_update_does_not_replace_nested_environment_file(self):
        with tempfile.TemporaryDirectory() as base:
            base = Path(base)
            app = base / "shop"
            (app / "support-pro").mkdir(parents=True)
            (app / ".env").write_text("APP_ENV=test\n")
            (app / "support-pro" / ".env").write_text("original-secret\n")
            stage = base / "release"
            (stage / "backend" / "app").mkdir(parents=True)
            (stage / "backend" / "app" / "main.py").write_text("release")
            (stage / "support-pro").mkdir()
            (stage / "support-pro" / ".env").write_text("release-secret\n")
            (stage / "deploy").mkdir()
            (stage / "scripts").mkdir()
            for path in (stage / "deploy" / "build-production.sh", stage / "scripts" / "doctor.sh", stage / "scripts" / "upgrade-postgres.sh"):
                path.write_text("#!/bin/sh\nexit 0\n")
                path.chmod(0o755)
            fakebin = base / "bin"
            fakebin.mkdir()
            docker = fakebin / "docker"
            docker.write_text('#!/bin/sh\ncase "$*" in *"pg_dump"*) echo "SELECT 1;";; esac\nexit 0\n')
            docker.chmod(0o755)
            run = subprocess.run(["bash", str(ROOT / "scripts/update.sh")], cwd=app,
                                 env={**os.environ, "APP_DIR": str(app), "UPDATE_STAGE": str(stage),
                                      "PATH": f"{fakebin}:{os.environ['PATH']}"},
                                 capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual((app / "support-pro" / ".env").read_text(), "original-secret\n")
            self.assertEqual((app / "backend" / "app" / "main.py").read_text(), "release")


if __name__ == "__main__":
    unittest.main()
