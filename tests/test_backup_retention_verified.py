"""REQ-INFRA-0037: the retention never deletes the newest backup whose restore check passed."""
from types import SimpleNamespace

from app.backups_api import retention_victims


def rows(*ids):
    return [SimpleNamespace(id=i) for i in ids]          # newest first


def test_old_backups_go_but_the_last_verified_stays():
    backups = rows(9, 8, 7, 6, 5, 4)
    assert [r.id for r in retention_victims(backups, 3, verified={4})] == [6, 5]          # 4 is the last verified one
    assert [r.id for r in retention_victims(backups, 3, verified={8, 4})] == [6, 5, 4]    # 8 is newer and verified
    assert [r.id for r in retention_victims(backups, 3, verified=set())] == [6, 5, 4]


def test_at_least_one_backup_is_always_kept():
    assert [r.id for r in retention_victims(rows(3, 2, 1), 0, verified=set())] == [2, 1]
    assert retention_victims(rows(1), 7, verified=set()) == []
