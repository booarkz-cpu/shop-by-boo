"""Real file fixtures exercise the release contract without publishing or changing a release."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
from scripts.audit.check_release_changelog import COLUMNS, release_section, table_rows, validate  # noqa: E402

HEADER = "| " + " | ".join(COLUMNS) + " |\n| " + " | ".join(["---"] * 6) + " |\n"
ROW = ("Кабинет", "Исправлена выгрузка данных", "Ранее выгрузка не включала сведения о сессиях. Теперь владелец получает метаданные собственных сессий.",
       "Новые действия пользователя не требуются.", "Регрессии выгрузки и границ доступа проходят в CI.",
       "[PR #372](https://github.com/booarkz-cpu/shop-by-boo/pull/372)")


def table(row=ROW):
    return HEADER + "| " + " | ".join(row) + " |\n"


def write_release(root, *, tag="v28.162.0", changelog=None, notes=None):
    (root / "release-manifest.template.json").write_text(
        json.dumps({"distribution_tag": tag, "release_notes": "notes.md"}), encoding="utf-8")
    sections = "\n".join("## " + section + "\n\nОписано отдельно.\n" for section in
                         ("Ломающие изменения", "Миграции", "Откат", "Известные ограничения", "Чем проверено"))
    (root / "notes.md").write_text(notes if notes is not None else f"# {tag}\n\n{table()}\n{sections}", encoding="utf-8")
    (root / "CHANGELOG.md").write_text(changelog if changelog is not None else f"# {tag}\n\n{table()}", encoding="utf-8")


def test_new_release_requires_a_detailed_matching_table(tmp_path):
    write_release(tmp_path)
    assert "structure OK" in validate(tmp_path)
    write_release(tmp_path, changelog="# v28.162.0\n\n- Краткая строка без таблицы.\n")
    with pytest.raises(ValueError, match="table is required"):
        validate(tmp_path)


@pytest.mark.parametrize("index,value", [(0, "—"), (1, "TODO подробнее"), (2, "Кратко"),
                                        (3, ""), (4, "TBD"), (5, "нет ссылки")])
def test_rejects_incomplete_unfinished_and_untraceable_rows(index, value):
    row = list(ROW)
    row[index] = value
    with pytest.raises(ValueError):
        table_rows(table(row), "fixture")


def test_mismatch_between_changelog_and_release_notes_is_an_error(tmp_path):
    changed = list(ROW)
    changed[3] = "После обновления пользователю требуется повторно открыть кабинет."
    write_release(tmp_path, changelog="# v28.162.0\n\n" + table(changed))
    with pytest.raises(ValueError, match="same ordered"):
        validate(tmp_path)


def test_only_the_requested_release_section_is_compared():
    text = "# v28.162.0\n\n" + table() + "\n# v28.161.0\n\n- Исторические заметки.\n"
    assert table_rows(release_section(text, "v28.162.0"), "fixture") == [ROW]
    with pytest.raises(ValueError, match="missing release"):
        release_section(text, "v28.163.0")


def test_preserves_escaped_pipes_and_refuses_duplicate_rows():
    row = list(ROW)
    row[2] += r" Поддерживается A \| B."
    assert table_rows(table(row), "fixture")[0][2].endswith("A | B.")
    with pytest.raises(ValueError, match="duplicate"):
        table_rows(table() + "\n" + table(), "fixture")


def test_existing_published_release_is_not_reformatted(tmp_path):
    write_release(tmp_path, tag="v28.161.0", changelog="История", notes="Исходные заметки")
    assert "preserved" in validate(tmp_path)
    assert (tmp_path / "notes.md").read_text() == "Исходные заметки"


def test_rejects_release_notes_path_outside_checkout(tmp_path):
    write_release(tmp_path)
    (tmp_path / "release-manifest.template.json").write_text(
        json.dumps({"distribution_tag": "v28.162.0", "release_notes": "../outside.md"}), encoding="utf-8")
    with pytest.raises(ValueError, match="escapes"):
        validate(tmp_path)



def test_new_client_version_requires_its_own_release_table(tmp_path):
    from scripts.audit.check_release_changelog import validate_current_client

    path = tmp_path / "apps/vpn-client/android/app/build.gradle.kts"
    path.parent.mkdir(parents=True)
    path.write_text('versionName = "1.10.1"\n', encoding="utf-8")
    assert "preserved" in validate_current_client(tmp_path)
    path.write_text('versionName = "1.10.2"\n', encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        validate_current_client(tmp_path)
    write_release(tmp_path, tag="client-v1.10.2")
    notes = tmp_path / "docs/releases/client-v1.10.2.md"
    notes.parent.mkdir(parents=True)
    notes.write_text((tmp_path / "notes.md").read_text(), encoding="utf-8")
    assert "structure OK" in validate_current_client(tmp_path)
