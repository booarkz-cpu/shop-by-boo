import os
from pathlib import Path
import sqlite3
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def migrate(path, revision):
    result = subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', revision], cwd=ROOT,
        env={**os.environ, 'DATABASE_URL':'sqlite+aiosqlite:///'+str(path)}, text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_fresh_database_and_upgrade_preserves_history(tmp_path):
    fresh = tmp_path/'fresh.db'
    migrate(fresh, 'head')
    with sqlite3.connect(fresh) as c:
        assert c.execute('SELECT version_num FROM alembic_version').fetchone()[0] == '0007'
        assert 'notifications' in {x[0] for x in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    old = tmp_path/'old.db'
    migrate(old,'0001')
    with sqlite3.connect(old) as c:
        c.execute("INSERT INTO operators(id,login,password_hash,role) VALUES(1,'old','hash','admin')")
        c.execute("INSERT INTO tickets(id,telegram_user_id,full_name,username,status) VALUES(1,123,'Old Name','olduser','open')")
        c.execute("INSERT INTO messages(id,ticket_id,sender,text) VALUES(1,1,'user','Old question')")
        c.execute("INSERT INTO messages(id,ticket_id,sender,text) VALUES(2,1,'operator','Old reply')")
        c.execute("INSERT INTO attachments(id,ticket_id,message_id,filename,path) VALUES(1,1,2,'file.txt','/data/uploads/file.txt')")
    migrate(old,'head')
    migrate(old,'head')
    with sqlite3.connect(old) as c:
        assert c.execute('SELECT text,delivery_state FROM messages ORDER BY id').fetchall() == [('Old question','received'),('Old reply','legacy')]
        assert c.execute('SELECT full_name FROM clients WHERE telegram_user_id=123').fetchone()[0] == 'Old Name'
        assert c.execute('SELECT last_customer_message_id FROM tickets').fetchone()[0] == 1
        assert c.execute('SELECT path,state FROM attachments').fetchone() == ('/data/uploads/file.txt','ready')


def run_guard(path):
    return subprocess.run([sys.executable, '-m', 'app.migrate'], cwd=ROOT,
        env={**os.environ, 'DATABASE_URL':'sqlite+aiosqlite:///'+str(path)}, text=True, capture_output=True)


def test_unversioned_legacy_is_verified_and_upgraded(tmp_path):
    path = tmp_path/'unversioned.db'
    migrate(path, '0001')
    with sqlite3.connect(path) as c:
        c.execute('DROP TABLE alembic_version')
        c.execute("INSERT INTO tickets(id,telegram_user_id,subject) VALUES(1,777,'Keep me')")
    result = run_guard(path)
    assert result.returncode == 0, result.stdout + result.stderr
    with sqlite3.connect(path) as c:
        assert c.execute('SELECT version_num FROM alembic_version').fetchone()[0] == '0007'
        assert c.execute('SELECT subject FROM tickets').fetchone()[0] == 'Keep me'


def test_unrecognized_unversioned_schema_not_modified(tmp_path):
    path = tmp_path/'unknown.db'
    migrate(path, '0001')
    with sqlite3.connect(path) as c:
        c.execute('DROP TABLE alembic_version')
        c.execute('ALTER TABLE tickets ADD COLUMN custom_field TEXT')
    result = run_guard(path)
    assert result.returncode != 0
    assert 'No changes made' in result.stderr
    with sqlite3.connect(path) as c:
        assert 'clients' not in {row[0] for row in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_upgrade_from_33_preserves_product_data(tmp_path):
    path=tmp_path/'v33.db'
    migrate(path,'0003')
    with sqlite3.connect(path) as c:
        c.execute("INSERT INTO knowledge_articles(id,title,slug,body,status,visibility) VALUES(1,'Keep','keep','Article','published','public')")
        c.execute("INSERT INTO tickets(id,telegram_user_id,subject) VALUES(1,987,'Original')")
    migrate(path,'head')
    with sqlite3.connect(path) as c:
        assert c.execute('SELECT subject,channel,paused_seconds FROM tickets').fetchone()==('Original','telegram',0)
        assert c.execute('SELECT body FROM knowledge_articles').fetchone()[0]=='Article'
        assert 'work_items' in {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_email_channel_migration_roundtrip_and_downgrade_guard(tmp_path):
    path = tmp_path/'email.db'
    migrate(path, 'head')
    def downgrade():
        return subprocess.run([sys.executable, '-m', 'alembic', 'downgrade', '0006'], cwd=ROOT,
            env={**os.environ, 'DATABASE_URL':'sqlite+aiosqlite:///'+str(path)}, text=True, capture_output=True)
    assert downgrade().returncode == 0
    migrate(path, 'head')
    with sqlite3.connect(path) as c:
        c.execute("INSERT INTO tickets(id,telegram_user_id,subject,channel) VALUES(1,-5,'Mail','email')")
        c.execute("INSERT INTO channel_identities(client_id,channel,external_id,address,verified) VALUES(-5,'email','a@example.org','a@example.org',0)")
        try:
            c.execute("INSERT INTO channel_identities(client_id,channel,external_id,address,verified) VALUES(-6,'email','a@example.org','a@example.org',0)")
            raise AssertionError('duplicate identity accepted')
        except sqlite3.IntegrityError:
            pass
    result = downgrade()
    assert result.returncode != 0 and 'Email tickets exist' in result.stdout + result.stderr
