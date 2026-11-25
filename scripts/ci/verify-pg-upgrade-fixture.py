"""Verify every synthetic row restored during the PostgreSQL upgrade drill."""
import hashlib
import subprocess
import sys


def expected_digest(database, major):
    checksum = hashlib.sha256(f"db\t{database}\t{major}\n".encode())
    for i in range(1, 1501):
        checksum.update(f"order\t{i}\t{database} order {i}\t{i}.00\n".encode())
    for i in range(1, 43):
        checksum.update(f"user\t{i}\n".encode())
    return checksum.hexdigest()


def verify(database, major, psql):
    query = b"""
SELECT 'db', current_database(), current_setting('server_version_num')::int / 10000;
SELECT 'order', id, note, paid FROM legacy_orders ORDER BY id;
SELECT 'user', id FROM legacy_users ORDER BY id;
"""
    result = subprocess.run([*psql, "-X", "-qAt", "-F", "\t", "-v", "ON_ERROR_STOP=1"],
                            input=query, stdout=subprocess.PIPE, check=True)
    digest = hashlib.sha256(result.stdout).hexdigest()
    if digest != expected_digest(database, major):
        raise SystemExit(f"Recovery fixture mismatch for {database} on PostgreSQL {major}: {digest}")
    print(f"Verified {database} on PostgreSQL {major}: 1500 orders, 42 users, SHA-256 {digest}")


if __name__ == "__main__":
    database, major, *psql = sys.argv[1:]
    verify(database, major, psql)
