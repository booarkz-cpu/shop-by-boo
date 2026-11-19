from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PANEL_VERSION = "3.4.11"
NODE_VERSION = "3.4.6"
SUBPAGE_VERSION = "8.0.1"
PANEL_COMMIT = "6853666801d6d1925b6aec55824106100485777a"
NODE_COMMIT = "52d0f1c00c23bf99912687cb3b75faffb2d3bffb"
SUBPAGE_COMMIT = "9045728e6e197a2581c6da40f4f92b170a8bad53"
PANEL_IMAGE = "remnawave/backend:3.4.11@sha256:a5b9f81fe2cfacec1c41bd2bb43fa1a5980228b81aa2e744be4adffa3a00135b"
NODE_IMAGE = "remnawave/node:3.4.6@sha256:3d5fde656a36920f53c5c080f2dc821df8318f453803b07c4e5242752a549d69"
SUBPAGE_IMAGE = "remnawave/subscription-page:8.0.1@sha256:ba8445b1e0d1c170cf314686ef638b73cabf42a0c6217d027e6cb958ca161ca6"


def read(path: str) -> str:
    return (ROOT / path).read_text()


def test_live_contract_uses_exact_releases_and_checks_digests():
    script = read("scripts/ci/remnawave-live.sh")
    for value in (
        PANEL_VERSION, NODE_VERSION, SUBPAGE_VERSION,
        PANEL_COMMIT, NODE_COMMIT, SUBPAGE_COMMIT,
        PANEL_IMAGE, NODE_IMAGE, SUBPAGE_IMAGE,
    ):
        assert value in script
    assert "refs/heads/$REF" not in script
    assert "remnawave/node:latest" not in script
    assert "remnawave/subscription-page:latest" not in script
    assert '[[ "$version" == "$PANEL_VERSION" ]]' in script
    assert 'verify_image_digest "$PANEL_IMAGE"' in script
    assert 'verify_image_digest "$NODE_IMAGE"' in script
    assert 'verify_image_digest "$SUBPAGE_IMAGE"' in script
    assert "org.opencontainers.image.version" not in script
    assert '  local image="$1"\\n  local expected="${image##*@}"' in script
    assert r'local image="$1"\\\\n' not in script


def test_runtime_and_provisioning_use_the_same_pins():
    plan = read("services/backend/app/rw_plan.py")
    provisioner = read("services/backend/app/provisioner.py")
    autoscale = read("services/backend/app/node_autoscale.py")
    for image in (PANEL_IMAGE, NODE_IMAGE, SUBPAGE_IMAGE):
        assert image in plan
    assert f'"panel": "{PANEL_VERSION}"' in plan
    assert f'"node": "{NODE_VERSION}"' in plan
    assert f'"subscription_page": "{SUBPAGE_VERSION}"' in plan
    assert f'NODE_IMAGE = "remnawave/node:{NODE_VERSION}"' in provisioner
    assert f"remnawave/node:{NODE_VERSION}" in autoscale
    assert "remnawave/node:latest" not in provisioner + autoscale


def test_compatibility_matrix_matches_executable_pins():
    matrix = read("docs/ru/new/REMNAWAVE_COMPATIBILITY.md")
    architecture = read("docs/ru/new/REMNAWAVE_ARCHITECTURE.md")
    api = read("docs/ru/new/REMNAWAVE_API_DESIGN.md")
    for value in (
        PANEL_VERSION, NODE_VERSION, SUBPAGE_VERSION,
        PANEL_COMMIT, NODE_COMMIT, SUBPAGE_COMMIT,
        PANEL_IMAGE, NODE_IMAGE, SUBPAGE_IMAGE,
    ):
        assert value in matrix
    assert "Backend contract (`@remnawave/backend-contract`) | `3.4.17`" in matrix
    assert "3.4.11" in architecture and "3.4.6" in architecture
    assert "@remnawave/backend-contract` 3.4.17" in api
