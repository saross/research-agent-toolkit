"""
Tests for the example Zotero library check (examples/zotero-library-check.py).

The example is published for people to copy, so it has to be right. The scout
marks a paper `[HAVE]` on its word, and treats a clean exit with no output as
"nothing held". These tests build a small database with the parts of
Zotero's layout the example reads, and check that it finds a DOI however it
is written, ignores items in the bin, never prints a DOI it did not find, and
exits with an error when there is no database.
"""

import importlib.util
import io
import sqlite3
from pathlib import Path

import pytest

_PATH = Path(__file__).parent.parent / "examples" / "zotero-library-check.py"
_spec = importlib.util.spec_from_file_location("zotero_library_check", _PATH)
assert _spec is not None and _spec.loader is not None
example = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(example)

SCHEMA = """
    CREATE TABLE fields (fieldID INTEGER PRIMARY KEY, fieldName TEXT);
    CREATE TABLE itemDataValues (valueID INTEGER PRIMARY KEY, value TEXT);
    CREATE TABLE itemData (itemID INTEGER, fieldID INTEGER, valueID INTEGER);
    CREATE TABLE deletedItems (itemID INTEGER PRIMARY KEY);
    INSERT INTO fields VALUES (1, 'DOI'), (2, 'title');
"""


def make_database(folder: Path, items: list[tuple[str, str, bool]]) -> Path:
    """
    Create a `zotero.sqlite` holding one item per (field, value, binned) entry.

    Args:
        folder: Where to create the file.
        items: For each item, the field name (`DOI` or `title`), its value,
            and whether the item is in the bin.

    Returns:
        The data folder, for use as `ZOTERO_DATA_DIR`.
    """
    connection = sqlite3.connect(folder / "zotero.sqlite")
    connection.executescript(SCHEMA)
    for number, (field, value, binned) in enumerate(items, start=1):
        connection.execute("INSERT INTO itemDataValues VALUES (?, ?)", (number, value))
        connection.execute(
            "INSERT INTO itemData VALUES (?, ?, ?)", (number, 1 if field == "DOI" else 2, number)
        )
        if binned:
            connection.execute("INSERT INTO deletedItems VALUES (?)", (number,))
    connection.commit()
    connection.close()
    return folder


def run(monkeypatch: pytest.MonkeyPatch, folder: Path, stdin: str) -> int:
    """Run the example's `main` against a data folder with the given input."""
    monkeypatch.setenv("ZOTERO_DATA_DIR", str(folder))
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    return example.main()


@pytest.mark.parametrize(
    "written",
    ["10.1000/AbC", "https://doi.org/10.1000/abc", "doi:10.1000/ABC", "  10.1000/abc\n"],
)
def test_normalise_reduces_every_spelling_to_one(written: str) -> None:
    assert example.normalise(written) == "10.1000/abc"


def test_finds_a_doi_however_it_is_stored_and_echoes_the_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = make_database(tmp_path, [("DOI", "https://doi.org/10.1000/ABC", False)])
    assert run(monkeypatch, folder, "10.1000/abc\n10.2000/absent\n\n") == 0
    assert capsys.readouterr().out == "10.1000/abc\n"


def test_ignores_the_bin_other_fields_and_partial_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = make_database(
        tmp_path,
        [
            ("DOI", "10.1000/binned", True),
            ("title", "10.1000/in-a-title", False),
            ("DOI", "10.1000/abcdef", False),
            ("DOI", "", False),
        ],
    )
    stdin = "10.1000/binned\n10.1000/in-a-title\n10.1000/abc\n"
    assert run(monkeypatch, folder, stdin) == 0
    assert capsys.readouterr().out == ""


def test_sees_a_change_zotero_has_committed_but_not_yet_merged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A paper moved to the bin in the write-ahead log is no longer held.

    SQLite's immutable mode reads only the main file here and still reports
    the paper, which is why the example doesn't use it.
    """
    folder = make_database(tmp_path, [("DOI", "10.1000/abc", False)])
    writer = sqlite3.connect(folder / "zotero.sqlite")
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("PRAGMA wal_autocheckpoint=0")
    writer.execute("INSERT INTO deletedItems VALUES (1)")
    writer.commit()  # committed, held in the -wal file, writer still open
    try:
        assert run(monkeypatch, folder, "10.1000/abc\n") == 0
        assert capsys.readouterr().out == ""
    finally:
        writer.close()


def test_reads_a_checked_copy_when_the_database_is_locked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """With the database held under an exclusive lock, the copy is read."""
    items = [("DOI", "10.1000/abc", False), ("DOI", "10.1000/gone", False)]
    folder = make_database(tmp_path, items)
    holder = sqlite3.connect(folder / "zotero.sqlite")
    holder.execute("PRAGMA locking_mode=EXCLUSIVE")
    holder.execute("PRAGMA journal_mode=WAL")
    holder.execute("PRAGMA wal_autocheckpoint=0")
    holder.execute("INSERT INTO deletedItems VALUES (2)")
    holder.commit()  # the lock is now held until `holder` closes
    try:
        with pytest.raises(sqlite3.OperationalError):
            example.query_dois(folder / "zotero.sqlite", read_only=True)
        assert run(monkeypatch, folder, "10.1000/abc\n10.1000/gone\n") == 0
        assert capsys.readouterr().out == "10.1000/abc\n"
    finally:
        holder.close()


def test_fails_when_the_database_keeps_changing_during_the_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A copy that can't be shown to be steady is never read."""
    folder = make_database(tmp_path, [("DOI", "10.1000/abc", False)])
    calls = iter(range(100))
    changing = lambda database: [("zotero.sqlite", next(calls), 0)]  # noqa: E731
    monkeypatch.setattr(example, "fingerprint", changing)

    def locked(database: Path, read_only: bool) -> set[str]:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(example, "query_dois", locked)
    assert run(monkeypatch, folder, "10.1000/abc\n") == 1
    captured = capsys.readouterr()
    assert captured.out == "" and "kept changing" in captured.err


def test_exits_with_an_error_and_prints_nothing_without_a_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(monkeypatch, tmp_path, "10.1000/abc\n") == 1
    captured = capsys.readouterr()
    assert captured.out == "" and "library check failed" in captured.err


def test_exits_with_an_error_when_the_file_is_not_a_zotero_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    sqlite3.connect(tmp_path / "zotero.sqlite").close()  # a database with no tables
    assert run(monkeypatch, tmp_path, "10.1000/abc\n") == 1
    assert capsys.readouterr().out == ""
