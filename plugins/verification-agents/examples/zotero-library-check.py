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

It only reads, and it uses the Python standard library alone. It opens the
database read-only through SQLite in the ordinary way, so it sees everything
Zotero has saved, including recent changes. Zotero can hold the database
locked while it is open. The check then fails and says so, and the scout
reports the library as not checked: close Zotero and run the search again.
The script does not work around the lock. Reading a copy made while Zotero
is writing, or opening the file in SQLite's "immutable" mode, can give wrong
answers, and a wrong "held" or "new" is worse than a check that didn't run.

By default it looks in `~/Zotero`, Zotero's usual data folder. Set the
environment variable `ZOTERO_DATA_DIR` if yours is elsewhere (Zotero shows
the location under Settings, Advanced, Files and Folders).

Usage:
    printf '%s\\n' 10.1000/one 10.1000/two | python3 zotero-library-check.py

Exit status: 0 when the check ran, whether or not anything matched; 1 when
the database could not be read (missing, locked, or not a Zotero database),
so that the scout reports the library as not checked instead of marking
everything new.
"""

from __future__ import annotations

import os
import sqlite3
import sys
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


#: How long to wait, in seconds, for another program to release the database.
LOCK_WAIT = 2


def held_dois(database: Path) -> set[str]:
    """
    Return every DOI in the Zotero database, normalised.

    Args:
        database: Path to `zotero.sqlite`.

    Returns:
        The set of normalised DOIs carried by items outside the bin.

    Raises:
        FileNotFoundError: If the database file does not exist.
        sqlite3.Error: If it is locked for longer than `LOCK_WAIT`, or
            cannot be read as a Zotero database.
    """
    if not database.is_file():
        raise FileNotFoundError(f"no Zotero database at {database}")
    connection = sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True, timeout=LOCK_WAIT)
    try:
        return {normalise(value) for (value,) in connection.execute(QUERY) if value}
    finally:
        connection.close()


def main() -> int:
    """Print the DOIs from standard input that the Zotero library holds."""
    data_folder = Path(os.environ.get("ZOTERO_DATA_DIR") or Path.home() / "Zotero")
    try:
        held = held_dois(data_folder / "zotero.sqlite")
    except (FileNotFoundError, sqlite3.Error) as error:
        print(f"library check failed: {error}", file=sys.stderr)
        if "locked" in str(error).lower():
            print("Zotero may have the database open: close Zotero and try again.",
                  file=sys.stderr)
        return 1
    held.discard("")
    for line in sys.stdin:
        doi = line.strip()
        if doi and normalise(doi) in held:
            print(doi)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
