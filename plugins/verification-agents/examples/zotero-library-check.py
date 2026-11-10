#!/usr/bin/env python3
"""
zotero-library-check.py
=======================

An example library check command for Zotero.

The literature scout can ask a command of yours which candidate papers you
already hold (plugin option `library_check_command`; see the repository
README, "Optional: connect your reference library"). This is a working
example for a Zotero library on the same computer. Copy it somewhere of your
own, check it does what you want, and set the option to its full path.

It reads Digital Object Identifiers (DOIs) from standard input, one per
line, and prints each one that an item in your Zotero database carries in
its DOI field, in any of your libraries, including group libraries. Items in
the bin are ignored. A paper you hold with an empty DOI field is not found.

It only reads, and it uses the Python standard library alone. It first
opens the database read-only in the ordinary way, which sees everything
Zotero has saved. If Zotero has the database locked, as it may while it is
open, the script copies the database files to a temporary folder, checks
that they didn't change while being copied, and reads the copy. If it can't
get a steady copy in a few attempts it fails, so that a half-written
database is never read. It does not use SQLite's "immutable" mode, which
can give wrong answers for a file that another program is changing.

By default it looks in `~/Zotero`, Zotero's usual data folder. Set the
environment variable `ZOTERO_DATA_DIR` if yours is elsewhere (Zotero shows
the location under Settings, Advanced, Files and Folders).

Usage:
    printf '%s\\n' 10.1000/one 10.1000/two | python3 zotero-library-check.py

Exit status: 0 when the check ran, whether or not anything matched; 1 when
the database could not be read, so that the scout reports the library as not
checked instead of marking everything new.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

#: Spellings that can wrap a DOI in Zotero's DOI field or in the input.
PREFIXES = (
    "https://doi.org/",
    "http://doi.org/",
    "https://dx.doi.org/",
    "http://dx.doi.org/",
    "doi:",
)

#: Every DOI field value of every item that is not in the bin.
QUERY = """
    SELECT itemDataValues.value
    FROM itemData
    JOIN fields ON fields.fieldID = itemData.fieldID
    JOIN itemDataValues ON itemDataValues.valueID = itemData.valueID
    WHERE fields.fieldName = 'DOI'
      AND itemData.itemID NOT IN (SELECT itemID FROM deletedItems)
"""


def normalise(doi: str) -> str:
    """
    Reduce a DOI to a form that can be compared.

    DOIs are not case-sensitive, and the same DOI may be written bare or as a
    web address.

    Args:
        doi: A DOI as typed, stored, or pasted.

    Returns:
        The DOI in lower case, without surrounding space or a leading
        `https://doi.org/`, `doi:`, or similar.
    """
    text = doi.strip().lower()
    for prefix in PREFIXES:
        if text.startswith(prefix):
            return text[len(prefix):].strip()
    return text


#: SQLite keeps recent changes in these files beside the database.
COMPANIONS = ("-wal", "-journal")

#: How many times to try for a copy that didn't change while being made.
COPY_ATTEMPTS = 3


def query_dois(database: Path, read_only: bool) -> set[str]:
    """
    Read every DOI from a database file through an ordinary connection.

    Args:
        database: Path to the database file.
        read_only: Open the file read-only. A private copy is opened for
            writing instead, so SQLite can apply its pending changes.

    Returns:
        The set of normalised DOIs carried by items outside the bin.

    Raises:
        sqlite3.Error: If the file is locked or is not a Zotero database.
    """
    address = f"{database.as_uri()}?mode=ro" if read_only else database.as_uri()
    connection = sqlite3.connect(address, uri=True, timeout=2)
    try:
        return {normalise(value) for (value,) in connection.execute(QUERY) if value}
    finally:
        connection.close()


def fingerprint(database: Path) -> list[tuple[str, int, int]]:
    """
    Describe the database files as they are now.

    Args:
        database: Path to the database file.

    Returns:
        The name, size, and modification time of the database and of each
        companion file that exists. Two equal results mean nothing was
        written in between.
    """
    found = []
    for suffix in ("", *COMPANIONS):
        path = database.with_name(database.name + suffix)
        if path.exists():
            status = path.stat()
            found.append((path.name, status.st_size, status.st_mtime_ns))
    return found


def query_copy(database: Path) -> set[str]:
    """
    Read every DOI from a private copy of a database that is locked.

    The database and its companion files are copied to a temporary folder.
    The copy is used only if the originals were the same before and after
    copying, which shows that no write happened part-way through.

    Args:
        database: Path to the locked database file.

    Returns:
        The set of normalised DOIs carried by items outside the bin.

    Raises:
        sqlite3.Error: If no steady copy could be made, or the copy can't be
            read as a Zotero database.
    """
    for _ in range(COPY_ATTEMPTS):
        with tempfile.TemporaryDirectory(prefix="zotero-library-check-") as folder:
            before = fingerprint(database)
            for name, _, _ in before:
                shutil.copy2(database.with_name(name), Path(folder) / name)
            if fingerprint(database) != before:
                continue  # Zotero wrote during the copy: try again
            return query_dois(Path(folder) / database.name, read_only=False)
    raise sqlite3.OperationalError(
        "the Zotero database kept changing while it was being copied; try again shortly"
    )


def held_dois(database: Path) -> set[str]:
    """
    Return every DOI in the Zotero database, normalised.

    Args:
        database: Path to `zotero.sqlite`.

    Returns:
        The set of normalised DOIs carried by items outside the bin.

    Raises:
        FileNotFoundError: If the database file does not exist.
        sqlite3.Error: If it cannot be read as a Zotero database.
    """
    if not database.is_file():
        raise FileNotFoundError(f"no Zotero database at {database}")
    try:
        return query_dois(database, read_only=True)
    except sqlite3.OperationalError as error:
        # Only a lock sends us to the copy. Any other error, such as a file
        # that isn't a Zotero database, is reported as it is.
        if "locked" not in str(error).lower() and "busy" not in str(error).lower():
            raise
    return query_copy(database)


def main() -> int:
    """Print the DOIs from standard input that the Zotero library holds."""
    data_folder = Path(os.environ.get("ZOTERO_DATA_DIR") or Path.home() / "Zotero")
    try:
        held = held_dois(data_folder / "zotero.sqlite")
    except (FileNotFoundError, sqlite3.Error) as error:
        print(f"library check failed: {error}", file=sys.stderr)
        return 1
    held.discard("")
    for line in sys.stdin:
        doi = line.strip()
        if doi and normalise(doi) in held:
            print(doi)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
