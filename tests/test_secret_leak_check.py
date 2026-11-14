"""REQ-INFRA-0021: the repository check finds environment files, private keys, dumps and tokens, and lets examples pass."""
import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("secret_leak_check", ROOT / "scripts/ci/secret-leak-check.py")
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)

KEY_BODY = "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7" * 2


def run(tmp_path, files: dict) -> dict:
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    paths = [p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()]
    return dict(check.scan(tmp_path, paths))


def test_secrets_are_found(tmp_path):
    found = run(tmp_path, {
        ".env": "APP_SECRET=x\n", "backend/.env.production": "X=1\n", "deploy/server.key": "x", "backups/shop.sql.gz": "x",
        "app/config.py": "TOKEN = '123456789:AA" + "b" * 33 + "'\n",
        "docs/note.md": f"-----BEGIN OPENSSH PRIVATE KEY-----\n{KEY_BODY}\n",
        "scripts/x.sh": "GH=ghp_" + "a1" * 18 + "\n", "infra/aws.txt": "AKIA" + "ABCDEFGHIJKLMNOP\n",
    })
    assert found == {".env": "файл окружения .env", "backend/.env.production": "файл окружения .env",
                     "deploy/server.key": "файл ключа или хранилища ключей", "backups/shop.sql.gz": "дамп базы или резервная копия",
                     "app/config.py": "токен Telegram-бота", "docs/note.md": "приватный ключ в тексте",
                     "scripts/x.sh": "токен GitHub", "infra/aws.txt": "ключ AWS"}


def test_examples_and_placeholders_pass(tmp_path):
    assert run(tmp_path, {
        ".env.example": "APP_SECRET=\n", "backend/.env.sample": "X=\n",
        "apps/lucy-admin/web/src/form.tsx": 'placeholder="-----BEGIN OPENSSH PRIVATE KEY-----"\n',
        "docs/push.md": "APNS_PRIVATE_KEY=-----BEGIN PRIVATE KEY-----\\nMIGT...\\n-----END PRIVATE KEY-----\n",
        "tests/fixtures/node.key": "test key",
    }) == {}


def test_the_repository_itself_is_clean():
    assert check.scan(ROOT, check.tracked(ROOT)) == []
