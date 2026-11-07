"""v28.91.0 (stage 20, N8): «Серверы → SelfSteal» — the catalogue, own sites from an archive, the site on the node and
the outside check.

* the catalogue: 22 templates in 7 themes, ru and en; every build has inner pages, 404, robots.txt with the sitemap and
  nothing from outside (no scripts, no foreign addresses); two nodes on one template get different builds;
* archives: zip and tar.gz with a top folder are accepted; paths out of the site, links, hidden files, server scripts,
  a page without <title> and an archive over the limit are refused with the file named;
* the node: rw_steps.SITE itself (bash) unpacks a build, switches «current» and switches back on «undo»;
* the outside check: 11 points against a fake node that behaves like the node's Caddy — all «ok» for a catalogue build,
  remarks for a bare web server; only the node's own address is asked;
* the API: upload, list, delete (refused while a node shows the site), overview «N из M», preview."""
import hashlib
import io
import subprocess
import tarfile
import zipfile
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import rw_plan, rw_selfsteal, rw_steps, selfsteal_check, selfsteal_sites
from app.config import settings
from test_subscription_commerce import database  # noqa: F401

DOMAIN = "node1.example.com"
ADMIN = SimpleNamespace(email="admin@example.com", role="owner")


# ---------------------------------------------------------------- catalogue

def test_catalogue_has_twenty_templates_with_full_sites():
    assert len(selfsteal_sites.CATALOGUE) >= 20
    assert {t.theme for t in selfsteal_sites.CATALOGUE} == set(selfsteal_sites.THEMES)
    assert {"cloud", "docs", "corgi"} <= set(selfsteal_sites.TEMPLATES), "earlier installations keep their template"
    for t in selfsteal_sites.CATALOGUE:
        for lang in selfsteal_sites.LANGS:
            files = selfsteal_sites.build_site(t.id, DOMAIN, lang)
            slug = t.section[0]
            assert {"index.html", "about/index.html", f"{slug}/index.html", "contacts/index.html", "404.html", "robots.txt",
                    "sitemap.xml", "style.css", "favicon.svg", "hero.svg", f"{slug}/1/index.html"} <= set(files), (t.id, lang)
            for path, body in files.items():
                text = body.decode()
                assert "<script" not in text.lower(), (t.id, path)
                foreign = [u for u in text.replace("https://" + DOMAIN, "").split("http")[1:]
                           if not u.startswith(("://www.w3.org/2000/svg", "://www.sitemaps.org/"))]
                assert not foreign, (t.id, path, foreign[:2])
            assert f"Sitemap: https://{DOMAIN}/sitemap.xml" in files["robots.txt"].decode()
            assert f"<html lang='{lang}'>" in files["index.html"].decode()


def test_every_node_gets_its_own_build():
    a = selfsteal_sites.build_site("bakery", "a.example.com")
    b = selfsteal_sites.build_site("bakery", "b.example.com")
    assert a == selfsteal_sites.build_site("bakery", "a.example.com"), "the same node — the same site after a reinstall"
    builds = {selfsteal_sites.pack(selfsteal_sites.build_site("bakery", f"n{i}.example.com")) for i in range(6)}
    assert len(builds) == 6 and a["index.html"] != b["index.html"]
    with pytest.raises(ValueError):
        selfsteal_sites.build_site("nope", DOMAIN)
    with pytest.raises(ValueError):
        selfsteal_sites.build_site("cloud", DOMAIN, "de")


# ---------------------------------------------------------------- archives

def zip_of(entries: dict) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for name, body in entries.items():
            z.writestr(name, body)
    return out.getvalue()


def tgz_of(entries: dict, link: str | None = None) -> bytes:
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as tar:
        for name, body in entries.items():
            info = tarfile.TarInfo(name)
            info.size = len(body)
            tar.addfile(info, io.BytesIO(body))
        if link:
            info = tarfile.TarInfo(link)
            info.type, info.linkname = tarfile.SYMTYPE, "/etc/passwd"
            tar.addfile(info)
    return out.getvalue()


INDEX = b"<!doctype html><html><head><title>My studio</title></head><body><a href='/about.html'>About</a></body></html>"


def test_archives_are_accepted_and_moved_to_the_root():
    files = selfsteal_sites.read_archive(zip_of({"site/index.html": INDEX, "site/css/a.css": b"body{}", "__MACOSX/x": b"",
                                                 "site/img/logo.png": b"\x89PNG"}), "site.zip")
    assert set(files) == {"index.html", "css/a.css", "img/logo.png"}
    assert selfsteal_sites.page_title(files) == "My studio"
    files = selfsteal_sites.read_archive(tgz_of({"index.html": INDEX, "about.html": b"<p>x</p>"}), "site.tar.gz")
    assert set(files) == {"index.html", "about.html"}
    bundle = selfsteal_sites.pack(files)
    assert bundle == selfsteal_sites.pack(dict(reversed(list(files.items())))), "the same site — the same bytes"


@pytest.mark.parametrize("archive,name,error", [
    (zip_of({"../evil.html": INDEX, "index.html": INDEX}), "a.zip", "за пределы"),
    (zip_of({"index.html": INDEX, ".htaccess": b"x"}), "a.zip", "скрытые"),
    (zip_of({"index.html": INDEX, "shell.php": b"<?php"}), "a.zip", ".php"),
    (zip_of({"index.html": INDEX, "run.sh": b"rm"}), "a.zip", ".sh"),
    (zip_of({"index.html": b"<html><body>no title</body></html>"}), "a.zip", "<title>"),
    (zip_of({"page.html": INDEX}), "a.zip", "index.html"),
    (zip_of({"a/index.html": INDEX, "b/x.html": INDEX}), "a.zip", "index.html"),
    (tgz_of({"index.html": INDEX}, link="evil.html"), "a.tar.gz", "ссылки"),
    (zip_of({"/etc/index.html": INDEX}), "a.zip", "абсолютный"),
    (b"not an archive", "a.rar", ".zip или .tar.gz"),
])
def test_bad_archives_are_refused_with_the_reason(archive, name, error):
    with pytest.raises(selfsteal_sites.SiteError) as err:
        selfsteal_sites.read_archive(archive, name)
    assert error in str(err.value)


def test_archive_size_limit(monkeypatch):
    monkeypatch.setattr(selfsteal_sites, "MAX_ARCHIVE", 100)
    with pytest.raises(selfsteal_sites.SiteError, match="20 МБ"):
        selfsteal_sites.read_archive(b"x" * 101, "a.zip")


# ---------------------------------------------------------------- the node: rw_steps.SITE itself

def test_site_script_switches_and_goes_back(tmp_path):
    script = rw_steps.SITE.replace("d=/opt/remnawave-selfsteal/sites", f"d={tmp_path}/sites")

    def put(files):
        data = selfsteal_sites.pack(files)
        return subprocess.run(["bash", "-c", script, "site", "put", hashlib.sha256(data).hexdigest()], input=data, capture_output=True)

    first = put({"index.html": b"<title>one</title>"})
    assert first.returncode == 0, first.stderr
    current = tmp_path / "sites" / "current"
    assert (current / "index.html").read_bytes() == b"<title>one</title>"
    assert put({"index.html": b"<title>two</title>", "a/b.css": b"x"}).returncode == 0
    assert (current / "index.html").read_bytes() == b"<title>two</title>" and (current / "a/b.css").exists()
    assert subprocess.run(["bash", "-c", script, "site", "undo"], capture_output=True).returncode == 0
    assert (current / "index.html").read_bytes() == b"<title>one</title>", "«undo» brings the previous site back"
    data = selfsteal_sites.pack({"index.html": b"x"})
    bad = subprocess.run(["bash", "-c", script, "site", "put", "0" * 64], input=data, capture_output=True)
    assert bad.returncode == 3 and (current / "index.html").read_bytes() == b"<title>one</title>", "a wrong SHA-256 changes nothing"
    assert subprocess.run(["bash", "-c", script, "site", "put", "x;rm"], capture_output=True).returncode == 2


def test_caddy_serves_the_site_like_the_check_expects():
    caddy = rw_plan.selfsteal_caddyfile(DOMAIN, "acme", "a@example.com")
    assert "root * /sites/current" in caddy and "\t\t-Server" in caddy and "Strict-Transport-Security" in caddy
    assert "rewrite * /404.html" in caddy and "try_files {path} /index.html" not in caddy, "no catch-all: missing pages are 404"
    assert f"redir https://{DOMAIN}{{uri}} permanent" in caddy
    with pytest.raises(Exception):
        rw_plan.PlanIn(mode="node", node_server_ids=[2], selfsteal_domain=DOMAIN, tls="internal", selfsteal_template="custom")
    with pytest.raises(Exception):
        rw_plan.PlanIn(mode="node", node_server_ids=[2], selfsteal_domain=DOMAIN, tls="internal", selfsteal_template="unknown")
    plan = rw_plan.PlanIn(mode="node", node_server_ids=[2], selfsteal_domain=DOMAIN, tls="internal", selfsteal_template="coffee",
                          selfsteal_lang="en")
    assert tarfile.open(fileobj=io.BytesIO(rw_steps.site_bundle(plan)), mode="r:gz").getnames()[0]


# ---------------------------------------------------------------- the outside check

class FakeNode:
    """Answers like the node's Caddy with a site (or like a bare web server when ``bare``)."""

    def __init__(self, files: dict[str, bytes], address: str, bare: bool = False):
        self.files, self.address, self.bare, self.asked = files, address, bare, []

    async def fetch(self, address, domain, scheme, path):
        self.asked.append((address, domain, scheme, path))
        assert address == self.address and domain == DOMAIN, "only the node's own address, with its domain"
        if scheme == "http":
            return selfsteal_check.Answer(200 if self.bare else 301, {} if self.bare else {"location": f"https://{DOMAIN}{path}"}, b"", 3)
        headers = {"server": "nginx/1.18.0", "x-powered-by": "PHP/7.4"} if self.bare else {"strict-transport-security": "max-age=31536000"}
        key = path.lstrip("/")
        for candidate in (key, f"{key}index.html".lstrip("/"), f"{key}/index.html"):
            if candidate in self.files:
                return selfsteal_check.Answer(200, headers, self.files[candidate], 12)
        return selfsteal_check.Answer(404, headers, b"" if self.bare else self.files.get("404.html", b""), 5)


@pytest.mark.asyncio
async def test_outside_check_eleven_points(monkeypatch):
    node = FakeNode(selfsteal_sites.build_site("photo", DOMAIN), "93.184.216.34")

    async def resolve(domain):
        return {"93.184.216.34"}

    async def certificate(address, domain):
        return {"notAfter": "Dec 31 23:59:59 2030 GMT", "issuer": ((("organizationName", "Let's Encrypt"),),),
                "subject": ((("commonName", DOMAIN),),)}

    monkeypatch.setattr(selfsteal_check, "resolve", resolve)
    monkeypatch.setattr(selfsteal_check, "certificate", certificate)
    monkeypatch.setattr(selfsteal_check, "fetch", node.fetch)
    report = await selfsteal_check.check(DOMAIN, "93.184.216.34")
    assert [p["key"] for p in report["points"]] == list(selfsteal_check.POINTS)
    assert report["remarks"] == 0 and report["summary"] == "в порядке", [p for p in report["points"] if not p["ok"]]

    bare = FakeNode({"index.html": b"<html><title>Welcome to nginx!</title></html>"}, "93.184.216.34", bare=True)
    monkeypatch.setattr(selfsteal_check, "fetch", bare.fetch)

    async def other(domain):
        return {"203.0.113.5"}

    async def bad_cert(address, domain):
        raise selfsteal_check.ssl.SSLCertVerificationError("self signed")

    monkeypatch.setattr(selfsteal_check, "resolve", other)
    monkeypatch.setattr(selfsteal_check, "certificate", bad_cert)
    report = await selfsteal_check.check(DOMAIN, "93.184.216.34")
    bad = {p["key"] for p in report["points"] if not p["ok"]}
    assert bad == {"dns", "title", "cert", "redirect", "notfound", "headers", "hsts", "robots", "sitemap", "pages"}
    assert report["summary"] == "есть замечания (10)"
    assert "nginx/1.18.0" in next(p["text"] for p in report["points"] if p["key"] == "headers")


def test_only_public_node_addresses_are_checked():
    assert selfsteal_check.node_address("93.184.216.34") == "93.184.216.34"
    for private in ("127.0.0.1", "10.0.0.5", "192.168.1.1", "169.254.169.254"):
        with pytest.raises(ValueError):
            selfsteal_check.node_address(private)


# ---------------------------------------------------------------- the API

class Upload:
    def __init__(self, data: bytes, filename: str):
        self.data, self.filename = data, filename

    async def read(self, limit: int = -1) -> bytes:
        return self.data if limit < 0 else self.data[:limit]


@pytest.mark.asyncio
async def test_api_upload_list_delete_preview_and_overview(database, monkeypatch, tmp_path):
    db = database
    monkeypatch.setattr(settings, "media_dir", str(tmp_path))
    monkeypatch.setattr(settings, "remnawave_url", "")
    monkeypatch.setattr(settings, "remnawave_token", "")
    entry = await rw_selfsteal.upload_site(Upload(zip_of({"index.html": INDEX}), "studio.zip"), "", db, ADMIN)
    assert entry["name"] == "My studio" and entry["files"] == 1
    assert rw_selfsteal.upload_path(entry["id"]).is_file()
    again = await rw_selfsteal.upload_site(Upload(zip_of({"index.html": INDEX}), "studio.zip"), "Студия", db, ADMIN)
    listed = (await rw_selfsteal.list_sites(db, ADMIN))["sites"]
    assert [s["id"] for s in listed] == [entry["id"]] and again["name"] == "Студия", "the same archive replaces its entry"
    with pytest.raises(HTTPException) as err:
        await rw_selfsteal.upload_site(Upload(zip_of({"index.php": b"x"}), "x.zip"), "", db, ADMIN)
    assert err.value.status_code == 422
    plan = rw_plan.PlanIn(mode="node", node_server_ids=[2], selfsteal_domain=DOMAIN, tls="internal", selfsteal_template="custom",
                          selfsteal_upload=entry["id"])
    assert rw_steps.site_bundle(plan) == rw_selfsteal.upload_path(entry["id"]).read_bytes()
    page = await rw_selfsteal.preview("garden", DOMAIN, "en", "index.html", ADMIN)
    assert b"<title>" in page.body and "default-src 'none'" in page.headers["content-security-policy"]
    assert b"<style>" in page.body and b"data:image/svg+xml;base64," in page.body and b"href='/" not in page.body
    assert b"page=about/index.html" in page.body, "links lead to the other pages of the preview"
    assert "frame-ancestors 'self'" in page.headers["content-security-policy"] and page.headers["x-frame-options"] == "SAMEORIGIN"
    with pytest.raises(HTTPException):
        await rw_selfsteal.preview("garden", "bad domain", "en", "index.html", ADMIN)
    catalogue = await rw_selfsteal.catalogue(ADMIN)
    assert len(catalogue["templates"]) >= 20 and "creative" in catalogue["themes"]
    overview = await rw_selfsteal.overview(db, ADMIN)
    assert overview == {"known": 0, "total": 0, "panel_connected": False, "nodes": [], "templates": len(selfsteal_sites.CATALOGUE)}
    with pytest.raises(HTTPException) as err:
        await rw_selfsteal.check(rw_selfsteal.CheckIn(key="1:2"), db, ADMIN)
    assert err.value.status_code == 404
    await rw_selfsteal.delete_site(entry["id"], db, ADMIN)
    assert not rw_selfsteal.upload_path(entry["id"]).exists() and (await rw_selfsteal.list_sites(db, ADMIN))["sites"] == []
