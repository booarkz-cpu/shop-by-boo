"""CI licence gate: a strong copyleft or source-available dependency fails the build; weak copyleft does not."""
import importlib.util
import pathlib

SPEC = importlib.util.spec_from_file_location("check_licenses", pathlib.Path(__file__).resolve().parents[1] / "scripts/ci/check-licenses.py")
lic = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lic)


def test_verdicts():
    for ok in ("MIT", "Apache-2.0", "BSD License", "ISC", "MPL-2.0", "LGPL-3.0-or-later", "LGPL-2.1",
               "GNU Lesser General Public License v3 (LGPLv3)", "Apache-2.0 OR BSD-3-Clause", "(MIT OR GPL-3.0)",
               "Apache Software License; BSD License", "CC-BY-4.0", "OFL-1.1", "0BSD"):
        assert lic.verdict(ok) == "ok", ok
    for bad in ("GPL-3.0", "GNU General Public License v3 (GPLv3)", "AGPL-3.0-only", "GNU Affero General Public License v3",
                "SSPL-1.0", "BUSL-1.1", "Elastic License 2.0", "MIT AND GPL-2.0", "GPL-2.0 OR AGPL-3.0"):
        assert lic.verdict(bad) == "denied", bad
    for unknown in ("", "UNKNOWN", "UNLICENSED"):
        assert lic.verdict(unknown) == "unknown"


def test_both_report_formats_and_the_result():
    python = [{"Name": "fastapi", "License": "MIT License"}, {"Name": "evil", "License": "GNU General Public License v3 (GPLv3)"}]
    node = {"react@19.0.0": {"licenses": "MIT"}, "dual@1.0.0": {"licenses": ["MIT", "GPL-3.0"]}, "@scope/quiet@2.0.0": {}}
    denied, unknown, summary = lic.check([python, node])
    assert denied == ["evil: GNU General Public License v3 (GPLv3)"]
    assert unknown == ["@scope/quiet"]
    assert summary["MIT"] == 1 and sum(summary.values()) == 5
    assert lic.ALLOWED == {}, "an exception needs a reason and a human decision"


def test_exit_code(tmp_path, capsys):
    import json

    good, bad = tmp_path / "good.json", tmp_path / "bad.json"
    good.write_text(json.dumps([{"Name": "a", "License": "MIT"}]))
    bad.write_text(json.dumps([{"Name": "b", "License": "AGPL-3.0"}]))
    assert lic.main([str(good)]) == 0
    assert lic.main([str(good), str(bad)]) == 1
    assert "::error::copyleft or source-available licence: b: AGPL-3.0" in capsys.readouterr().out
