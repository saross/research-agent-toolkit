#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx>=0.27", "bibtexparser>=1.4,<2"]
# ///
"""
Academic literature search CLI for the lit-scout agent.

Provides subcommands for querying CrossRef, Semantic Scholar, and OpenAlex
APIs with automatic fallback, rate limiting, and deduplication. The DOI
resolver at doi.org answers two further questions: whether a DOI resolves
(`doi-exists`), and, when none of the three indexes holds a DOI, what the
agency that registered it records (the last source of `metadata`). All
output is JSON to stdout for machine consumption by the lit-scout agent.

Usage:
    lit-search.py metadata DOI
    lit-search.py references DOI
    lit-search.py citations DOI
    lit-search.py search "QUERY"
    lit-search.py openalex-cited-by DOI
    lit-search.py doi-exists DOI
    lit-search.py bibtex DOI [DOI ...]

Requires: httpx, and bibtexparser 1.x for the bibtex subcommand. The `lit-search` wrapper
beside this file runs it through `uv`, which installs both on first use.
No API keys required — uses free tiers and polite pool headers.
"""

import argparse
import base64
import email.utils
import json
import logging
import os
import random
import re
import string
import sys
import threading
import time
import unicodedata
import urllib.parse
from collections.abc import Callable
from typing import Any

import bibtexparser
import httpx
from bibtexparser.bibdatabase import BibDatabase
from bibtexparser.bparser import BibTexParser
from bibtexparser.bwriter import BibTexWriter

# ============================================================================
# Configuration
# ============================================================================

def _resolve_mailto() -> str | None:
    """
    Contact address sent to CrossRef and OpenAlex, read from the environment.

    CrossRef and OpenAlex both operate a "polite pool" — faster, more reliable
    service for callers who identify themselves with a contact address. That is
    the ONLY purpose this value serves.

    It is deliberately NOT hard-coded. A baked-in address means every person who
    runs this script unmodified identifies themselves, to third-party APIs, as
    whoever happens to be written into the source. Set ``LIT_SCOUT_MAILTO`` (or
    ``CROSSREF_MAILTO``) to your own address to join the polite pool; leave it
    unset and the scripts still work, just in the common pool.
    """
    for name in ("LIT_SCOUT_MAILTO", "CROSSREF_MAILTO"):
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    return None


MAILTO = _resolve_mailto()
USER_AGENT = (
    f"lit-scout/1.0 (mailto:{MAILTO})" if MAILTO else "lit-scout/1.0"
)

# API base URLs
CROSSREF_BASE = "https://api.crossref.org"
#: The DOI resolver, which answers a BibTeX request for a DOI of any registry.
DOI_RESOLVER = "https://doi.org"
S2_BASE = "https://api.semanticscholar.org/graph/v1"
OPENALEX_BASE = "https://api.openalex.org"

#: Headers for every request to doi.org: the `doi-exists` lookup, the
#: CSL-JSON record, and the BibTeX fallback. The contact address is for the
#: CrossRef and OpenAlex polite pools only (see `_resolve_mailto`), so these
#: requests identify the tool and nobody else; no key is added to them
#: either. They override the shared client's own User-Agent, which may carry
#: the address.
DOI_ORG_HEADERS = {"User-Agent": "lit-scout/1.0"}


# ----------------------------------------------------------------------------
# DOI names: how one is read from the input, and when two are the same
# ----------------------------------------------------------------------------
# Both rules follow the DOI Foundation's "DOI URI Scheme" specification
# (doi:10.1000/292, 2024; read on 12 November 2026): chapter 2 for the
# percent-encoded forms, chapter 3 for equivalence. Review finding R34,
# follow-ups (0.3.1, GPT in Codex, lane astra): Unicode case folding made
# different names equal, and a link's encoded name was encoded a second time.

#: A DOI written as a doi.org link (https or http, with or without "dx.") or
#: as a "doi:" URI, rather than as a bare name.
_DOI_PREFIX = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:)", re.IGNORECASE)

#: Maps A-Z to a-z and leaves every other code point as it is.
_BASIC_LATIN_LOWER = str.maketrans(string.ascii_uppercase, string.ascii_lowercase)


def _bare_doi(doi: str) -> str | None:
    """
    Return the DOI name that *doi* gives, unencoded, ready to be encoded once.

    The input contract, shared by `doi-exists` and the CSL-JSON record read
    through doi.org (`_agency_record`):

    * A bare name, such as "10.1000/a#b", is the DOI name itself, raw. It is
      never percent-decoded, since a literal percent sequence can be part of
      a name: "10.1000/a%23b" is a different name from "10.1000/a#b".
    * A doi.org link ("https://doi.org/...", "http://...", "dx.doi.org") or a
      "doi:" URI carries the name percent-encoded, so everything after the
      prefix is percent-decoded exactly once, as UTF-8:
      "https://doi.org/10.1000/a%23b" and "doi:10.1000/a%23b" both give
      10.1000/a#b. A character left unencoded in a link, such as a "#" in a
      link pasted from a reference list, is kept as it stands.

    Surrounding whitespace is removed first. The caller percent-encodes the
    result once for its own request, so the name reaches doi.org whole.

    Returns:
        The DOI name, or None for a link or "doi:" URI whose percent-encoding
        does not decode as UTF-8, which names no DOI that could be asked
        about faithfully. Whether the name has the shape of a DOI is for the
        caller to check.
    """
    text = doi.strip()
    match = _DOI_PREFIX.match(text)
    if match is None:
        return text
    try:
        return urllib.parse.unquote(text[match.end():], errors="strict")
    except UnicodeDecodeError:
        return None


def _doi_key(doi: str) -> str:
    """
    Return *doi* in the form in which two DOI names are compared for identity.

    DOI names are case-insensitive only in the Basic Latin block (DOI URI
    Scheme, chapter 3), so only A-Z become a-z, and every other code point
    stays as it is. Unicode lower-casing or case folding would be too broad:
    case folding makes "10.1000/straße" equal "10.1000/strasse", and both
    make "Ä" equal "ä", which are different names. Nor is the name
    normalised, since equivalence goes by code point.
    """
    return doi.translate(_BASIC_LATIN_LOWER)


def _same_doi(first: str, second: str) -> bool:
    """True if two DOI names are the same name (see `_doi_key`)."""
    return _doi_key(first) == _doi_key(second)


def _polite(params: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Add the polite-pool ``mailto`` to *params*, or leave it out when no
    contact address is configured. Never sends ``mailto=None``.
    """
    out = dict(params or {})
    if MAILTO:
        out["mailto"] = MAILTO
    else:
        out.pop("mailto", None)
    return out


def _env_float(name: str, default: float) -> float:
    """
    Read a float tuning knob from the environment, falling back to a
    conservative default. A malformed value logs a warning (deferred to
    first use, since logging is configured below) and uses the default.
    """
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        # `log` is configured later in this module; emit via stderr
        # directly to avoid an import-order dependency.
        sys.stderr.write(
            f"WARNING: {name}={raw!r} is not a float; using default "
            f"{default}.\n"
        )
        return default


def _env_int(name: str, default: int) -> int:
    """Read an int tuning knob from the environment (see `_env_float`)."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        sys.stderr.write(
            f"WARNING: {name}={raw!r} is not an int; using default "
            f"{default}.\n"
        )
        return default


# ----------------------------------------------------------------------------
# Per-host pacing (minimum inter-request interval, seconds)
# ----------------------------------------------------------------------------
# Pacing is keyed by HOST rather than by logical source so that the floor is
# honoured across an entire batch operation (e.g. `bibtex` over many DOIs,
# which all hit api.crossref.org) and across every subcommand that touches a
# given host. Semantic Scholar's unauthenticated public limit is roughly
# 1 request/second, so we space S2 calls ~1.1 s apart by default; CrossRef
# rewards a polite mailto with a moderate rate; OpenAlex is generous.
#
# Each knob is overridable via an environment variable for ad-hoc tuning
# (e.g. backing right off when S2 is having a bad day) without code edits.
S2_HOST = "api.semanticscholar.org"
CROSSREF_HOST = "api.crossref.org"
OPENALEX_HOST = "api.openalex.org"

HOST_MIN_INTERVAL: dict[str, float] = {
    S2_HOST: _env_float("LIT_SEARCH_S2_MIN_INTERVAL", 1.1),
    CROSSREF_HOST: _env_float("LIT_SEARCH_CROSSREF_MIN_INTERVAL", 0.2),
    OPENALEX_HOST: _env_float("LIT_SEARCH_OPENALEX_MIN_INTERVAL", 0.1),
}
# Floor applied to any host not listed above.
DEFAULT_MIN_INTERVAL = _env_float("LIT_SEARCH_DEFAULT_MIN_INTERVAL", 0.2)

# ----------------------------------------------------------------------------
# Legacy per-source pacing map (retained for backward compatibility)
# ----------------------------------------------------------------------------
# `_rate_limit(source)` is still part of the module's internal surface. It now
# delegates to the per-host limiter, but the source->host mapping below keeps
# the old call sites working unchanged. S2's interval was previously 0.5 s,
# which proved too aggressive against the ~1 req/s public limit; the per-host
# floor (1.1 s) now governs S2 regardless of which key a caller passes.
RATE_LIMITS = {
    "crossref": 0.1,
    "s2": 0.5,
    "openalex": 0.1,
}
_SOURCE_TO_HOST = {
    "crossref": CROSSREF_HOST,
    "s2": S2_HOST,
    "openalex": OPENALEX_HOST,
}

# ----------------------------------------------------------------------------
# Retry / exponential-backoff knobs
# ----------------------------------------------------------------------------
# Transient failures (HTTP 429, HTTP 5xx, connection/timeout errors) are
# retried with exponential backoff plus jitter. After exhausting attempts the
# caller's existing graceful-degradation path runs (returns None / emits a
# "% FAILED" marker), so a persistently-429 source still degrades to the
# remaining sources rather than crashing the whole call.
MAX_RETRIES = _env_int("LIT_SEARCH_MAX_RETRIES", 4)  # total attempts per call
BASE_BACKOFF = _env_float("LIT_SEARCH_BASE_BACKOFF", 2.0)  # seconds (attempt 0)
MAX_BACKOFF = _env_float("LIT_SEARCH_MAX_BACKOFF", 60.0)  # cap on a single sleep
BACKOFF_JITTER = _env_float("LIT_SEARCH_BACKOFF_JITTER", 0.5)  # +/- fraction

# Optional Semantic Scholar API key (higher authenticated limits). Not
# required — absence simply uses the public unauthenticated tier, exactly as
# before. Both common env-var spellings are accepted.
S2_API_KEY = (
    os.environ.get("S2_API_KEY")
    or os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
    or ""
).strip()

# Optional OpenAlex API key. Free to register at
# https://openalex.org/settings/api; it raises the daily budget from the
# anonymous $0.10 to $1.00, both resetting at midnight UTC. Absent a key,
# behaviour is identical to before — the anonymous tier. Verified against
# help.openalex.org on 2026-08-21; note the GitHub docs mirror still
# describes the retired pre-2026 "100,000 credits, no key needed" model.
OPENALEX_API_KEY = (
    os.environ.get("OPENALEX_API_KEY")
    or os.environ.get("OPENALEX_KEY")
    or ""
).strip()

# Default result limits
DEFAULT_SEARCH_LIMIT = 10
DEFAULT_CITATION_LIMIT = 50

# Track last request time per host for pacing (thread-safe for future use).
_last_request: dict[str, float] = {}
_pace_lock = threading.Lock()

# ============================================================================
# Logging
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("lit-search")

# Values a log line or an error message must never carry: an `api_key`
# query parameter, wherever it appears in a URL.
_API_KEY_PARAM = re.compile(r"(api_key=)[^&\s'\"<>]+")


def _redact(text: str) -> str:
    """
    Remove credentials from text bound for a log line or the output.

    httpx puts the full request URL, query string included, into its own
    log lines and into many exception messages, and the OpenAlex key
    travels as the `api_key` query parameter (see `_with_openalex_key`).
    So every configured key is replaced wherever it appears, and so is
    any `api_key` value (release review L1, 9 November 2026).

    Args:
        text: a message, possibly holding a URL or an exception's text.

    Returns:
        The text with every credential replaced by `<redacted>`.
    """
    for key in (OPENALEX_API_KEY, S2_API_KEY):
        if key:
            text = text.replace(key, "<redacted>")
    return _API_KEY_PARAM.sub(r"\1<redacted>", text)


class _RedactCredentials(logging.Filter):
    """Rewrite a log record so that it carries no credential."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        clean = _redact(message)
        if clean != message:
            record.msg, record.args = clean, None
        return True


# httpx logs every request URL at INFO, query string and all, so its
# request lines are switched off, and anything these loggers do write is
# redacted, whichever handler receives it.
for _name in ("httpx", "httpcore"):
    logging.getLogger(_name).setLevel(logging.WARNING)
for _name in ("lit-search", "httpx", "httpcore"):
    logging.getLogger(_name).addFilter(_RedactCredentials())

# ============================================================================
# HTTP Client
# ============================================================================


def _enforce_credential_scope(request: httpx.Request) -> None:
    """
    Strip any credential header not addressed to its own host.

    Runs as an httpx request event hook, so it fires on EVERY outgoing
    request — including the ones httpx builds when following a redirect,
    which is the case a per-call header cannot cover on its own. httpx
    strips ``Authorization`` across origins but forwards arbitrary custom
    headers such as ``x-api-key``, so without this a redirect from
    Semantic Scholar to any other host would hand that host the key.

    Args:
        request: The outgoing request, mutated in place.
    """
    if request.url.host != S2_HOST and "x-api-key" in request.headers:
        del request.headers["x-api-key"]


def _with_s2_key(host: str, headers: dict | None) -> dict | None:
    """
    Attach the Semantic Scholar key to Semantic-Scholar-bound requests only.

    Audit round 4d (E3): the key used to be set on the shared client, so
    it went to CrossRef, DataCite, and OpenAlex on every call — three
    unrelated operators, each handed a credential for a fourth. Mirrors
    ``_with_openalex_key`` above.

    Args:
        host: hostname of the outbound request, from ``_host_of``.
        headers: the caller's headers, possibly None.

    Returns:
        The headers unchanged for any non-S2 host, or when no key is
        configured; otherwise a copy carrying ``x-api-key``.
    """
    if host != S2_HOST or not S2_API_KEY:
        return headers
    merged = dict(headers or {})
    merged.setdefault("x-api-key", S2_API_KEY)
    return merged


def _get_client() -> httpx.Client:
    """Create an httpx client with appropriate headers.

    Neither credential is set here. This client is shared by five
    services, so a client-wide credential would be sent to all of them:
    see `_with_openalex_key` and `_with_s2_key`, which attach each key per
    request, and `_enforce_credential_scope`, which removes a stray one
    from any request — redirect-generated included — bound elsewhere.
    """
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }
    return httpx.Client(
        headers=headers,
        timeout=30.0,
        follow_redirects=True,
        event_hooks={"request": [_enforce_credential_scope]},
    )


def _host_of(url: str) -> str:
    """Extract the hostname from a URL for per-host pacing."""
    return urllib.parse.urlsplit(url).hostname or ""


def _with_openalex_key(host: str, params: dict | None) -> dict | None:
    """Attach the OpenAlex API key to OpenAlex-bound requests only.

    OpenAlex accepts the key either as an `api_key` query parameter or as
    an `Authorization: Bearer` header, and treats the two identically. The
    parameter is used here because `_get_client` builds a single
    `httpx.Client` shared by CrossRef, DataCite, Semantic Scholar, arXiv,
    and OpenAlex: a key set as a client-wide header would be sent to all
    five. Gating on the hostname keeps it going only where it belongs.

    The key does not reach the logs: httpx's own request lines are switched
    off, and every record from this script's loggers, and from httpx's,
    passes through `_redact`, as does exception text written to the
    output. (An earlier version of this note said logging the bare `url`
    was enough; httpx logs the composed URL itself, so it wasn't.)

    Args:
        host: hostname of the outbound request, from `_host_of`.
        params: the caller's query parameters, possibly None.

    Returns:
        The parameters unchanged for any non-OpenAlex host, or when no key
        is configured; otherwise a copy carrying `api_key`. An explicit
        `api_key` supplied by the caller is left alone.
    """
    if host != OPENALEX_HOST or not OPENALEX_API_KEY:
        return params
    merged = dict(params or {})
    merged.setdefault("api_key", OPENALEX_API_KEY)
    return merged


def _pace_host(host: str) -> None:
    """
    Enforce the minimum inter-request interval for `host`.

    Sleeps just long enough that consecutive requests to the same host are
    spaced by at least `HOST_MIN_INTERVAL[host]` (or `DEFAULT_MIN_INTERVAL`).
    Because the timestamp is keyed by host and stored at module scope, the
    floor applies across an entire batch (e.g. `bibtex` over many DOIs) and
    across every subcommand, not just within one call.
    """
    min_interval = HOST_MIN_INTERVAL.get(host, DEFAULT_MIN_INTERVAL)
    with _pace_lock:
        now = time.monotonic()
        last = _last_request.get(host, 0.0)
        elapsed = now - last
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        _last_request[host] = time.monotonic()


def _rate_limit(source: str) -> None:
    """
    Enforce pacing for a logical `source` (backward-compatible shim).

    Delegates to the per-host limiter via the source->host mapping so that the
    same floor governs every call to a host regardless of which subcommand or
    source key issued it.
    """
    host = _SOURCE_TO_HOST.get(source)
    if host is None:
        # Unknown source key: fall back to the generic floor under its own
        # bucket so it still gets paced.
        _pace_host(source)
    else:
        _pace_host(host)


def _parse_retry_after(value: str) -> float | None:
    """
    Parse a `Retry-After` header value into a delay in seconds.

    The header may be either an integer number of seconds or an HTTP-date
    (RFC 7231). Returns the delay in seconds (>= 0), or None if it cannot be
    parsed. A past HTTP-date yields 0.0 (retry immediately, subject to the
    backoff floor in the caller).
    """
    value = (value or "").strip()
    if not value:
        return None
    # Numeric seconds form.
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    # HTTP-date form. `parsedate_to_datetime` raises (TypeError/ValueError)
    # on unparseable input rather than returning None, so guard it and treat
    # an unparseable header as "no usable hint" -> fall back to backoff.
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed is None:
        return None
    delay = parsed.timestamp() - time.time()
    return max(0.0, delay)


def _backoff_delay(attempt: int) -> float:
    """
    Exponential backoff with jitter for retry `attempt` (0-indexed).

    delay = BASE_BACKOFF * 2**attempt, multiplied by a random jitter factor in
    [1 - BACKOFF_JITTER, 1 + BACKOFF_JITTER], then capped at MAX_BACKOFF. The
    jitter spreads out retries so concurrent/repeated callers do not stampede
    the API in lockstep ("thundering herd").
    """
    raw = BASE_BACKOFF * (2 ** attempt)
    jitter = 1.0 + random.uniform(-BACKOFF_JITTER, BACKOFF_JITTER)
    return min(MAX_BACKOFF, max(0.0, raw * jitter))


# Status codes treated as transient and therefore retryable.
def _is_retryable_status(status_code: int) -> bool:
    """True for HTTP 429 and any 5xx (transient server-side failures)."""
    return status_code == 429 or 500 <= status_code < 600


def _request_with_retry(
    do_request: Callable[[], httpx.Response],
    host: str,
    source: str,
) -> httpx.Response:
    """
    Execute a single HTTP request with pacing + exponential-backoff retry.

    `do_request` is a zero-argument callable that performs exactly one GET and
    returns the `httpx.Response` (it must NOT do its own pacing/retry — this
    helper owns both). The helper:

      * paces the host before every attempt (so retries also respect the
        per-host floor);
      * retries on HTTP 429, HTTP 5xx, and connection/timeout errors;
      * on 429 honours `Retry-After` (seconds or HTTP-date) when present,
        otherwise uses exponential backoff with jitter;
      * caps the number of attempts at MAX_RETRIES and any single sleep at
        MAX_BACKOFF. That bounds the retrying, not the call's duration: each
        attempt is limited only by the client's timeouts, which apply to
        each HTTP operation (connecting, and each read or write), not to an
        attempt or the call as a whole, so there is no overall deadline;
      * after exhausting retries, returns the last response (so the caller's
        existing non-200 handling runs) or re-raises the last connection
        error (so the caller's existing `except httpx.HTTPError` runs).

    Net effect: success and terminal-4xx paths are unchanged; only transient
    failures gain extra, backed-off attempts before the SAME graceful
    degradation the caller already implemented.
    """
    last_exc: httpx.HTTPError | None = None
    last_resp: httpx.Response | None = None

    for attempt in range(MAX_RETRIES):
        _pace_host(host)
        try:
            resp = do_request()
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            # Connection-level failure: retryable.
            last_exc = exc
            last_resp = None
            if attempt < MAX_RETRIES - 1:
                delay = _backoff_delay(attempt)
                log.warning(
                    "%s: connection error (%s); retry %d/%d in %.1fs.",
                    source, type(exc).__name__, attempt + 1,
                    MAX_RETRIES - 1, delay,
                )
                time.sleep(delay)
                continue
            # Exhausted: re-raise so caller's except-clause degrades it.
            raise

        last_resp = resp
        if not _is_retryable_status(resp.status_code):
            # Success or a terminal status (e.g. 404): return immediately.
            return resp

        # Transient HTTP status (429 or 5xx).
        if attempt >= MAX_RETRIES - 1:
            # Out of attempts: hand the response back so the caller's
            # existing non-200 branch logs and returns None / a marker.
            return resp

        if resp.status_code == 429:
            retry_after = _parse_retry_after(
                resp.headers.get("Retry-After", "")
            )
            if retry_after is not None:
                # Respect the server's hint, but never below the backoff
                # floor for this attempt and never above the global cap.
                delay = min(
                    MAX_BACKOFF, max(retry_after, _backoff_delay(attempt))
                )
                hint = f"Retry-After={retry_after:.1f}s"
            else:
                delay = _backoff_delay(attempt)
                hint = "no Retry-After"
            log.warning(
                "%s: rate limited (429, %s); retry %d/%d in %.1fs.",
                source, hint, attempt + 1, MAX_RETRIES - 1, delay,
            )
        else:
            delay = _backoff_delay(attempt)
            log.warning(
                "%s: server error (HTTP %d); retry %d/%d in %.1fs.",
                source, resp.status_code, attempt + 1,
                MAX_RETRIES - 1, delay,
            )
        time.sleep(delay)

    # Loop fell through (should be unreachable given the returns/raises
    # above, but kept for total-function safety).
    if last_resp is not None:
        return last_resp
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("retry loop exited without a response")


def _safe_get(
    client: httpx.Client,
    url: str,
    source: str,
    params: dict | None = None,
) -> dict | None:
    """
    Make a GET request with rate limiting and error handling.

    Returns the parsed JSON response, or None on failure.
    Logs errors to stderr but does not raise.

    Audit 2026-05-02 (D-M1, D-M2): the 429 path used to retry exactly
    once with a flat 5 s sleep, without honouring `Retry-After` and
    without distinguishing "still rate-limited" from "definitively not
    found". A second 429 silently fell through to the generic non-200
    branch and the caller saw a `None` indistinguishable from a 404.

    Hardening 2026-06-06: pacing and retry are now delegated to the
    shared `_request_with_retry` helper, which paces per host, retries
    HTTP 429 / 5xx / connection errors with exponential backoff + jitter
    (honouring `Retry-After` on 429), caps attempts at MAX_RETRIES and
    any single sleep at MAX_BACKOFF, and — crucially — degrades exactly
    as before once retries are exhausted (non-200 -> None below; a
    connection error -> the `except httpx.HTTPError` branch -> None). A
    persistently rate-limited source therefore still drops out cleanly,
    leaving the remaining sources to answer, rather than crashing.
    """
    host = _host_of(url)
    params = _with_openalex_key(host, params)
    headers = _with_s2_key(host, None)
    try:
        resp = _request_with_retry(
            lambda: client.get(url, params=params, headers=headers),
            host=host,
            source=source,
        )
        if resp.status_code == 429:
            # Retries exhausted while still rate-limited. Preserve the
            # explicit WARN so silent rate-limit pressure stays visible,
            # and the caller still cannot distinguish this from a 404 —
            # the same contract as before.
            log.warning(
                "[lit-search] WARN: %s still rate-limited after %d "
                "attempts (HTTP 429); returning None — caller cannot "
                "distinguish this from 404. URL: %s",
                source, MAX_RETRIES, url,
            )
            return None
        if resp.status_code != 200:
            # Distinguish retryable transient failures (5xx) from terminal
            # 4xx so the log makes the failure mode visible. We still
            # return None — fixing the cursor-of-truth semantics is the
            # job of a later batch (D-X4) — but the log line tells the
            # operator which kind of failure happened.
            kind = "transient (5xx)" if 500 <= resp.status_code < 600 else "terminal"
            log.warning(
                "%s: HTTP %d (%s) for %s",
                source, resp.status_code, kind, url,
            )
            return None
        data = resp.json()
        if not isinstance(data, dict):
            log.warning(
                "%s: unexpected response type: %s",
                source, type(data).__name__,
            )
            return None
        return data
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        # Specific exceptions only — a programming bug should still crash
        # rather than be swallowed as "request failed".
        log.warning(
            "[lit-search] WARN: %s request failed (%s): %s",
            source, type(exc).__name__, _redact(str(exc)),
        )
        return None


# ============================================================================
# OpenAlex cursor pagination
# ============================================================================

# OpenAlex caps `per_page` at 200 (the API rejects larger values). Cursor
# pagination starts with the literal token `*` and follows
# `meta.next_cursor` until the API returns a null/empty cursor.
OPENALEX_PER_PAGE_MAX = 200
OPENALEX_INITIAL_CURSOR = "*"


def _openalex_paginate(
    client: httpx.Client,
    url: str,
    base_params: dict,
    limit: int,
) -> list[dict]:
    """
    Iterate OpenAlex cursor pagination until `limit` results are
    collected or the cursor terminates.

    Audit 2026-05-02 (D-M5, D-M6): the previous code hard-capped each
    request at `per_page=min(limit, 50)` and never followed the cursor,
    so a `--limit 200` request returned at most 50 results. OpenAlex
    supports `cursor=*` opaque-token pagination — that is the API's
    correct mechanism for deep paging. `page=N` offset pagination is
    capped at 10 000 results and is *not* what OpenAlex prefers; cursor
    is the documented choice for any traversal beyond the first page.

    The helper requests `per_page = min(remaining, OPENALEX_PER_PAGE_MAX)`
    each iteration so it never overshoots the user's `--limit`.

    Defensive against malformed responses: a missing `meta.next_cursor`
    or a cursor that does not advance terminates the loop. This avoids
    an infinite loop if the API ever echoes back a stale cursor.
    """
    if limit <= 0:
        return []

    collected: list[dict] = []
    cursor: str | None = OPENALEX_INITIAL_CURSOR
    seen_cursors: set[str] = set()

    while cursor and len(collected) < limit:
        remaining = limit - len(collected)
        per_page = max(1, min(remaining, OPENALEX_PER_PAGE_MAX))
        params = dict(base_params)
        params["per_page"] = str(per_page)
        params["cursor"] = cursor

        page = _safe_get(client, url, "openalex", params=params)
        if not page or "results" not in page:
            # Either the request failed (logged in `_safe_get`) or the
            # API returned no results envelope. Stop rather than loop.
            break

        results = page.get("results") or []
        if not results:
            break
        collected.extend(results)

        # Defensive: detect a cursor that does not advance. The API
        # contract says `next_cursor` should differ from the cursor we
        # just used; if it matches, or if we have seen this cursor
        # before, terminate to avoid infinite loops on malformed
        # responses. (`cursor` here is what we sent on this iteration.)
        next_cursor = (page.get("meta") or {}).get("next_cursor")
        if (
            not next_cursor
            or next_cursor == cursor
            or next_cursor in seen_cursors
        ):
            break
        seen_cursors.add(cursor)
        cursor = next_cursor

    return collected[:limit]


# ============================================================================
# Paper schema normalisation
# ============================================================================


def _normalise_paper(
    raw: dict,
    source: str,
) -> dict[str, Any]:
    """
    Normalise a paper record from any API source into the common schema.

    Returns:
        {title, authors, year, doi, openalex_id, s2_id,
         citation_count, source, abstract}
    """
    if source == "crossref":
        return _normalise_crossref(raw)
    elif source == "s2":
        return _normalise_s2(raw)
    elif source == "openalex":
        return _normalise_openalex(raw)
    else:
        return {"title": str(raw), "source": source}


def _join_title_and_subtitle(title: str, subtitle: str) -> str:
    """
    Join a title and a subtitle that a registry holds in separate fields.

    The same rule is kept in three places: this function in the published
    `lit_search.py`, in the personal `lit-search.py`, and in
    `lit-scout-zotero-import.py`. Change all three together.

    Args:
        title: The main title, stripped, not empty.
        subtitle: The subtitle, stripped, not empty.

    Returns:
        - The title alone when the subtitle is already in it: the two are
          equal, or the title ends with the subtitle straight after a
          separator (a colon, dash, full stop, question mark, or exclamation
          mark). A subtitle that merely matches the end of a word, as
          "Information" does in "Disinformation", is a distinct subtitle.
        - "Title? Subtitle" when the title ends with a question or
          exclamation mark, which stands as the separator.
        - "Title: Subtitle" otherwise.
    """
    folded_title, folded_subtitle = title.casefold(), subtitle.casefold()
    if folded_title == folded_subtitle:
        return title
    if folded_title.endswith(folded_subtitle):
        # Look at the folded title, not the original: folding can change a
        # string's length ("Stra\u00dfe" folds to "strasse"), so lengths taken
        # from the originals would cut in the wrong place.
        before = folded_title[: len(folded_title) - len(folded_subtitle)].rstrip()
        if before and before[-1] in ":-\u2013\u2014.?!":
            return title
    if title[-1] in "?!":
        return f"{title} {subtitle}"
    return f"{title.rstrip(':').rstrip()}: {subtitle}"


def _crossref_full_title(raw: dict) -> str | None:
    """
    Return a CrossRef work's title with its subtitle, as "Title: Subtitle".

    CrossRef holds the two in separate fields. Returning the title alone
    made a correct full title look wrong: a proposer that copied the short
    form was told it matched, and a verifier comparing against the
    publisher's page saw a dropped subtitle. The BibTeX that doi.org
    returns already joins them, so this also makes the two agree.

    Args:
        raw: A CrossRef work record (the `message` object).

    Returns:
        The title; with ": " and the subtitle appended when the record has
        a subtitle that the title does not already end with. None when the
        record has no title.
    """
    title = _first_or_none(raw.get("title", []))
    subtitle = _first_or_none(raw.get("subtitle") or [])
    if not isinstance(title, str) or not title.strip():
        return title
    if not isinstance(subtitle, str) or not subtitle.strip():
        return title
    return _join_title_and_subtitle(title.strip(), subtitle.strip())


def _normalise_crossref(raw: dict) -> dict[str, Any]:
    """Normalise a CrossRef work record."""
    # Authors: CrossRef uses {given, family} objects for people and a
    # single {name} for an organisation ("World Health Organization",
    # "The LIGO Collaboration"). Audit round 4d (E19): the organisation
    # form used to be dropped silently, so a corporate-authored work
    # arrived with an empty author list and the verifier had nothing to
    # check attribution against. The importer's own _creators_from_record
    # has always handled both shapes.
    authors = []
    for author in raw.get("author", []):
        family = (author.get("family") or "").strip()
        given = (author.get("given") or "").strip()
        name = (author.get("name") or "").strip()
        if family and given:
            authors.append(f"{family}, {given}")
        elif family:
            authors.append(family)
        elif name:
            authors.append(name)

    # Year: CrossRef nests dates oddly; values can be None
    year = None
    for date_field in ("published-print", "published-online", "issued"):
        date_obj = raw.get(date_field)
        if not isinstance(date_obj, dict):
            continue
        date_parts = date_obj.get("date-parts", [[]])
        if date_parts and date_parts[0] and date_parts[0][0]:
            year = date_parts[0][0]
            break

    return {
        "title": _crossref_full_title(raw),
        "authors": authors,
        "year": year,
        "doi": raw.get("DOI"),
        "openalex_id": None,
        "s2_id": None,
        "citation_count": raw.get("is-referenced-by-count"),
        "reference_count": raw.get("references-count"),
        "source": "crossref",
        "abstract": raw.get("abstract"),
    }


def _normalise_s2(raw: dict) -> dict[str, Any]:
    """Normalise a Semantic Scholar paper record."""
    authors = []
    for author in raw.get("authors", []):
        name = author.get("name", "")
        if name:
            authors.append(name)

    # Extract DOI from externalIds
    external_ids = raw.get("externalIds", {}) or {}
    doi = external_ids.get("DOI")

    return {
        "title": raw.get("title"),
        "authors": authors,
        "year": raw.get("year"),
        "doi": doi,
        "openalex_id": None,
        "s2_id": raw.get("paperId"),
        "citation_count": raw.get("citationCount"),
        "source": "s2",
        "abstract": raw.get("abstract"),
    }


def _normalise_openalex(raw: dict) -> dict[str, Any]:
    """Normalise an OpenAlex work record."""
    authors = []
    for authorship in raw.get("authorships", []) or []:
        # OpenAlex emits `"author": null` for an authorship it could not
        # resolve. `.get("author", {})` returns that None, not the default,
        # so the next `.get` raised AttributeError and the whole record was
        # lost (audit round 4d, lens B fixture gap).
        author = authorship.get("author") or {}
        name = author.get("display_name") or ""
        if name:
            authors.append(name)

    # OpenAlex DOI includes a URL prefix (various formats seen)
    doi_url = raw.get("doi") or ""
    doi = re.sub(r'^https?://(dx\.)?doi\.org/', '', doi_url) if doi_url else None

    # OpenAlex ID is a URL like https://openalex.org/W1234567
    oa_id = raw.get("id", "")

    return {
        "title": raw.get("display_name") or raw.get("title"),
        "authors": authors,
        "year": raw.get("publication_year"),
        "doi": doi,
        "openalex_id": oa_id,
        "s2_id": None,
        "citation_count": raw.get("cited_by_count"),
        "source": "openalex",
        "abstract": _reconstruct_openalex_abstract(raw),
    }


#: How a CSL-JSON record read through doi.org is named in `source` and
#: `sources`. It names the route, not the author of the record: doi.org
#: normally hands such a request to the registering agency's service, but
#: all the helper establishes is the address that answered, `record_url`
#: (review finding R39, 0.3.1, GPT in Codex, lane astra; until then this
#: said "doi.org (registration agency)").
DOI_CSL_SOURCE = "doi.org (content negotiation)"

#: What `doi_check` says about a CSL-JSON record's own DOI, in words.
_DOI_CHECK_NOTES = {
    "same": "the record names the DOI asked for",
    "different": (
        "the record names a different DOI, so it is a record of another identifier "
        "and cannot establish the identity of the DOI asked for"
    ),
    "absent": (
        "the record names no DOI, so nothing binds it to the DOI asked for: its "
        "metadata stands, but it cannot establish identity on its own"
    ),
}


def _csl_text(value: Any) -> str | None:
    """
    Return a CSL-JSON text variable as one stripped string, or None.

    CSL-JSON allows a text variable such as `title` or `container-title` to
    arrive as a string or, from some agencies, as a list of strings; a list
    gives its first item. An empty or non-text value gives None.
    """
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _csl_author_name(author: Any) -> str | None:
    """
    Return one CSL-JSON name as text, in the form `_normalise_crossref` uses.

    A person is written as `family` and `given` ("Family, Given"), with any
    `non-dropping-particle` ("van", "de") kept in front of the family name;
    an organisation or an unparsed name as `literal`. A name with only one
    part is kept as it stands: JaLC was seen on 12 November 2026 (DOI
    10.11501/3140078) writing a whole name, "Family, Given", in `given`
    alone. A non-standard `name` is read as `literal` is.

    Args:
        author: one item of the record's `author` list.

    Returns:
        The name, or None when the item holds no usable name.
    """
    if not isinstance(author, dict):
        return None
    family = _csl_text(author.get("family"))
    particle = _csl_text(author.get("non-dropping-particle"))
    if family and particle:
        family = f"{particle} {family}"
    given = _csl_text(author.get("given"))
    literal = _csl_text(author.get("literal")) or _csl_text(author.get("name"))
    if family and given:
        return f"{family}, {given}"
    return family or literal or given


def _normalise_csl(raw: dict, requested: str) -> dict[str, Any]:
    """
    Normalise a CSL-JSON record read through doi.org's content negotiation.

    doi.org normally hands a request for CSL-JSON to the service of the
    agency that registered the DOI (DataCite, mEDRA, JaLC, CrossRef, and
    others). The helper establishes less than that: which address answered
    (`record_url`, which `_agency_record` adds) and what the answer says, so
    `source` names the route (`DOI_CSL_SOURCE`), not the agency. The record
    carries no citation or reference counts, which stay None.

    The record is bound to the DOI asked for only by the DOI it names itself
    (review finding R39, 0.3.1). `doi` is that DOI as the record gives it,
    or None, and is never filled in with the DOI asked for; `requested_doi`
    is the DOI asked for; and `doi_check` compares the two by `_same_doi`:

    * "same": the record names the DOI asked for (perhaps with A-Z in
      another case, as DataCite writes a suffix in capitals);
    * "different": it names another DOI, so it is a record of another
      identifier, and cannot establish the identity of the DOI asked for;
    * "absent": it names no DOI, so nothing binds it to the DOI asked for;
      its metadata is kept, but it cannot establish identity on its own.

    `doi_check_note` says the same in words.

    Args:
        raw: the CSL-JSON object that answered.
        requested: the DOI asked for, bare.

    Returns:
        A record in the same shape as the other normalisers', plus `venue`
        (from `container-title`, else `publisher`), `type` (the CSL item
        type), `requested_doi`, `doi_check`, and `doi_check_note`.
    """
    title = _csl_text(raw.get("title"))
    subtitle = _csl_text(raw.get("subtitle"))
    if title and subtitle:
        title = _join_title_and_subtitle(title, subtitle)

    authors: list[str] = []
    raw_authors = raw.get("author")
    for author in raw_authors if isinstance(raw_authors, list) else []:
        name = _csl_author_name(author)
        if name:
            authors.append(name)

    year = None
    issued = raw.get("issued")
    parts = issued.get("date-parts") if isinstance(issued, dict) else None
    if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0]:
        year = _parse_year(parts[0][0])

    # The record's own DOI, kept apart from the DOI asked for, so that a
    # value the helper supplied is never mistaken for one the record gave.
    record_doi = _csl_text(raw.get("DOI"))
    if record_doi is None:
        doi_check = "absent"
    elif _same_doi(record_doi, requested):
        doi_check = "same"
    else:
        doi_check = "different"

    return {
        "title": title,
        "authors": authors,
        "year": year,
        "doi": record_doi,
        "requested_doi": requested,
        "doi_check": doi_check,
        "doi_check_note": _DOI_CHECK_NOTES[doi_check],
        "openalex_id": None,
        "s2_id": None,
        "citation_count": None,
        "reference_count": None,
        "venue": _csl_text(raw.get("container-title")) or _csl_text(raw.get("publisher")),
        "type": _csl_text(raw.get("type")),
        "source": DOI_CSL_SOURCE,
        "abstract": _csl_text(raw.get("abstract")),
    }


def _reconstruct_openalex_abstract(raw: dict) -> str | None:
    """
    Reconstruct abstract from OpenAlex's inverted index format.

    OpenAlex stores abstracts as {word: [positions]} for compression.
    """
    inverted = raw.get("abstract_inverted_index")
    if not inverted:
        return None
    # Build word list sorted by position
    words: list[tuple[int, str]] = []
    for word, positions in inverted.items():
        for pos in positions:
            words.append((pos, word))
    words.sort(key=lambda x: x[0])
    return " ".join(w for _, w in words)


def _first_or_none(lst: list) -> str | None:
    """Return the first element of a list, or None if empty."""
    return lst[0] if lst else None


# ============================================================================
# Deduplication
# ============================================================================


def _merge_paper_records(base: dict, extra: dict) -> dict:
    """
    Merge two paper records sharing a DOI, filling gaps in `base` from
    `extra` rather than discarding one.

    Audit 2026-05-02 (D-M4): the previous "more non-None fields wins"
    heuristic dropped complementary metadata. CrossRef carries DOI, year,
    title, authors but not abstract; OpenAlex carries DOI, abstract,
    citation count. Picking one record discarded fields the other
    populated. This merger preserves the same gap-fill semantics already
    used by `cmd_metadata` (truthiness check, so empty lists / zero counts
    can be filled in by populated values from other sources).

    `sources` is accumulated as a list so the merged record records every
    upstream that contributed.
    """
    merged = dict(base)
    for key, value in extra.items():
        if key == "source":
            # Single-source field is replaced by the multi-source `sources`.
            continue
        if value and not merged.get(key):
            merged[key] = value

    # Track all contributing sources. Promote `source` to `sources` list.
    sources: list[str] = []
    for record in (base, extra):
        existing = record.get("sources")
        if isinstance(existing, list):
            sources.extend(existing)
        single = record.get("source")
        if single and single not in sources:
            sources.append(single)
    if sources:
        merged["sources"] = sources
    return merged


def _deduplicate(papers: list[dict]) -> list[dict]:
    """
    Deduplicate papers by DOI, merging complementary metadata across
    sources rather than discarding one.

    Records without a DOI cannot be paired and are passed through
    unchanged. Whitespace is stripped, and A-Z are matched to a-z before
    comparison, since DOI names are case-insensitive in the Basic Latin
    block only (see `_doi_key`); every other character must match exactly.

    Audit 2026-05-02 (D-M4): switched from "winner-takes-all" to merge.
    """
    seen: dict[str, dict] = {}
    no_doi: list[dict] = []

    for paper in papers:
        doi = _doi_key((paper.get("doi") or "").strip())
        if not doi:
            no_doi.append(paper)
            continue

        if doi in seen:
            # Merge complementary fields from this duplicate into the
            # record we already have.
            seen[doi] = _merge_paper_records(seen[doi], paper)
        else:
            seen[doi] = paper

    return list(seen.values()) + no_doi


# ============================================================================
# Subcommand: metadata
# ============================================================================


#: The media type doi.org's content negotiation answers with CSL-JSON.
DOI_CSL_ACCEPT = "application/vnd.citationstyles.csl+json"
#: Timeouts for the CSL-JSON record, through doi.org's redirects: 10 s to
#: connect, 30 s for each read, write, or wait for a pooled connection. They
#: apply to each HTTP operation, not to the lookup as a whole: each redirect
#: and each retry is timed afresh, so there is no overall deadline.
DOI_CSL_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


def _agency_record(doi: str, client: httpx.Client) -> dict | None:
    """
    Read a CSL-JSON record of *doi* through doi.org's content negotiation.

    Asks `https://doi.org/<DOI>` for CSL-JSON, following redirects. doi.org
    normally hands the request to the agency that registered the DOI
    (DataCite for arXiv and Zenodo, mEDRA, JaLC, CrossRef, and others),
    which answers from its registration. This covers a DOI that no index
    holds yet, such as a deposit made the same day (Shawn's design, 11
    November 2026: the "is it the right target" check, through doi.org).
    What is established is only the address that gave the final answer,
    kept as `record_url`, and what that answer says: neither the Accept
    header nor a title in the answer proves that it is the agency's record
    (review finding R39, 0.3.1).

    The DOI is read as `cmd_doi_exists` reads it (`_bare_doi`: a bare name
    raw, a doi.org link or "doi:" URI decoded once), then percent-encoded
    once for the path, keeping its `/`. The request carries
    `DOI_ORG_HEADERS` and no key: `_enforce_credential_scope` removes any
    Semantic Scholar key, on the redirected requests too. Cost: up to
    `MAX_RETRIES` attempts, each followed through its redirects; timeouts
    apply to each HTTP operation, not to the whole.

    Args:
        doi: the DOI: a bare name, raw, or a doi.org link or "doi:" URI,
            percent-encoded (see `_bare_doi`).
        client: the shared client.

    Returns:
        The normalised record (see `_normalise_csl`, including how it is
        bound to the DOI asked for) with `record_url`, the address of the
        final answer; or None for something that is not a DOI, an HTTP
        error status, no answer, a body that is not a JSON object, or a
        record without a title.
    """
    requested = _bare_doi(doi)
    if requested is None or not requested.startswith("10.") or "/" not in requested:
        return None
    url = f"{DOI_RESOLVER}/{urllib.parse.quote(requested, safe='/')}"
    headers = {**DOI_ORG_HEADERS, "Accept": DOI_CSL_ACCEPT}
    try:
        resp = _request_with_retry(
            lambda: client.get(
                url, headers=headers, timeout=DOI_CSL_TIMEOUT, follow_redirects=True
            ),
            host=_host_of(url),
            source="doi.org",
        )
    except httpx.HTTPError as exc:
        log.warning(
            "doi.org: no answer for a CSL-JSON record of %s (%s)",
            requested, _redact(str(exc)) or type(exc).__name__,
        )
        return None
    if resp.status_code != 200:
        log.warning(
            "doi.org: HTTP %d for a CSL-JSON record of %s",
            resp.status_code, requested,
        )
        return None
    try:
        raw = resp.json()
    except ValueError:  # json.JSONDecodeError is a ValueError
        raw = None
    if not isinstance(raw, dict):
        log.warning("doi.org: the answer for %s is not a CSL-JSON record", requested)
        return None
    record = _normalise_csl(raw, requested)
    if not record["title"]:
        log.warning("doi.org: the CSL-JSON record of %s has no title", requested)
        return None
    record["record_url"] = _redact(str(resp.url))
    if record["doi_check"] != "same":
        log.warning("doi.org: the CSL-JSON record of %s: %s", requested, record["doi_check_note"])
    return record


def cmd_metadata(doi: str, client: httpx.Client) -> dict:
    """
    Fetch full metadata for a single paper by DOI.

    Tries CrossRef first, then Semantic Scholar, then OpenAlex, and merges
    their results to produce the most complete record. When none of the
    three holds a record, a CSL-JSON record is read through doi.org's
    content negotiation (`_agency_record`), with `source` and `sources`
    naming that route as `DOI_CSL_SOURCE`, `record_url` the address that
    answered, and `requested_doi`, `doi_check`, and `doi_check_note` saying
    whether the record names the DOI asked for; it has no citation count.
    Only when that fails too is the result "No metadata found".
    """
    results = []

    # CrossRef
    data = _safe_get(
        client, f"{CROSSREF_BASE}/works/{urllib.parse.quote(doi, safe='')}", "crossref"
    )
    if data and "message" in data:
        results.append(_normalise_crossref(data["message"]))

    # Semantic Scholar
    s2_fields = (
        "title,authors,year,abstract,citationCount,referenceCount,"
        "fieldsOfStudy,publicationTypes,externalIds"
    )
    data = _safe_get(
        client,
        f"{S2_BASE}/paper/DOI:{urllib.parse.quote(doi, safe='')}",
        "s2",
        params={"fields": s2_fields},
    )
    if data and "paperId" in data:
        record = _normalise_s2(data)
        # Add extra S2 fields
        record["reference_count"] = data.get("referenceCount")
        record["fields_of_study"] = data.get("fieldsOfStudy")
        record["publication_types"] = data.get("publicationTypes")
        results.append(record)

    # OpenAlex
    data = _safe_get(
        client,
        f"{OPENALEX_BASE}/works/doi:{urllib.parse.quote(doi, safe='')}",
        "openalex",
        params=_polite(),
    )
    if data and "id" in data:
        record = _normalise_openalex(data)
        record["is_oa"] = data.get("open_access", {}).get("is_oa")
        record["oa_url"] = data.get("open_access", {}).get("oa_url")
        results.append(record)

    if not results:
        # No index holds the DOI (or none could be read): ask doi.org, which
        # normally hands the request to the agency that registered it.
        agency = _agency_record(doi, client)
        if agency is None:
            return {"error": f"No metadata found for DOI: {doi}"}
        log.info("metadata: no index holds %s; read a CSL-JSON record through doi.org", doi)
        agency["sources"] = [DOI_CSL_SOURCE]
        return agency

    # Merge: start with first result, fill gaps from subsequent.
    # Use truthiness check so empty lists and zero counts get overwritten
    # by populated values from other sources.
    merged = results[0].copy()
    for extra in results[1:]:
        for key, value in extra.items():
            if value and not merged.get(key):
                merged[key] = value
    merged["sources"] = [r["source"] for r in results]
    return merged


# ============================================================================
# Subcommand: references (backward chaining)
# ============================================================================


def cmd_references(
    doi: str,
    client: httpx.Client,
    limit: int = DEFAULT_CITATION_LIMIT,
) -> list[dict]:
    """
    Get the reference list (backward chaining) for a paper.

    Fallback chain: CrossRef → Semantic Scholar → OpenAlex.
    Results are merged, deduplicated, and truncated to `limit`.
    """
    all_papers: list[dict] = []

    # CrossRef: reference array
    data = _safe_get(
        client, f"{CROSSREF_BASE}/works/{urllib.parse.quote(doi, safe='')}", "crossref"
    )
    if data and "message" in data:
        refs = data["message"].get("reference", [])
        for ref in refs:
            paper = {
                "title": ref.get("article-title") or ref.get(
                    "unstructured"
                ),
                "authors": [],
                "year": _parse_year(ref.get("year")),
                "doi": ref.get("DOI"),
                "openalex_id": None,
                "s2_id": None,
                "citation_count": None,
                "source": "crossref",
                "abstract": None,
            }
            # Try to extract author from unstructured string
            author = ref.get("author")
            if author:
                paper["authors"] = [author]
            if paper["title"] or paper["doi"]:
                all_papers.append(paper)
        log.info("CrossRef: found %d references", len(refs))

    # Semantic Scholar: references with metadata
    s2_fields = (
        "references.title,references.authors,references.year,"
        "references.externalIds,references.citationCount"
    )
    data = _safe_get(
        client,
        f"{S2_BASE}/paper/DOI:{urllib.parse.quote(doi, safe='')}",
        "s2",
        params={"fields": s2_fields},
    )
    if data and "references" in data:
        # A rate-limited (HTTP 429) or partial S2 response can carry the key
        # with a null value; coerce once so the loop and the log line agree
        # (previously len(None) crashed here after CrossRef had already
        # succeeded — 2026-06-12 lit-scout run on 10.1016/j.chbr.2026.101056).
        s2_refs = data["references"] or []
        for ref in s2_refs:
            if ref:
                all_papers.append(_normalise_s2(ref))
        log.info("S2: found %d references", len(s2_refs))

    # OpenAlex: referenced_works list (gives OpenAlex IDs, need to resolve)
    data = _safe_get(
        client,
        f"{OPENALEX_BASE}/works/doi:{urllib.parse.quote(doi, safe='')}",
        "openalex",
        params=_polite(),
    )
    if data and "referenced_works" in data:
        # Audit 2026-05-02 (D-M5): truncate to the user's `--limit`, not
        # to the hard-coded `DEFAULT_CITATION_LIMIT` (50). The previous
        # code silently capped the OpenAlex contribution at 50 even when
        # the user asked for more, then deduped against CrossRef and S2
        # at `limit`. The user's flag was partially ignored.
        all_ref_ids: list[str] = data["referenced_works"] or []
        ref_ids = all_ref_ids[:limit]
        if ref_ids:
            # OpenAlex batch resolves multiple IDs via the `openalex:` filter.
            # `per_page` is capped at OPENALEX_PER_PAGE_MAX (200) by the API;
            # if the user asks for more, page the filter via cursor.
            id_filter = "|".join(ref_ids)
            base_params = _polite({
                "filter": f"openalex:{id_filter}",
            })
            results = _openalex_paginate(
                client,
                f"{OPENALEX_BASE}/works",
                base_params,
                limit=len(ref_ids),
            )
            for work in results:
                all_papers.append(_normalise_openalex(work))
            log.info(
                "OpenAlex: resolved %d/%d references",
                len(results),
                len(ref_ids),
            )

    return _deduplicate(all_papers)[:limit]


# ============================================================================
# Subcommand: citations (forward chaining)
# ============================================================================


def cmd_citations(
    doi: str,
    client: httpx.Client,
    limit: int = DEFAULT_CITATION_LIMIT,
) -> list[dict]:
    """
    Get papers that cite a given paper (forward chaining).

    Uses Semantic Scholar (best citation data) and OpenAlex (highest volume).
    Results sorted by citation count descending.
    """
    all_papers: list[dict] = []

    # Semantic Scholar: citations with metadata
    s2_fields = (
        "citations.title,citations.authors,citations.year,"
        "citations.externalIds,citations.citationCount"
    )
    data = _safe_get(
        client,
        f"{S2_BASE}/paper/DOI:{urllib.parse.quote(doi, safe='')}",
        "s2",
        params={"fields": s2_fields},
    )
    if data and "citations" in data:
        # Same null-coercion as the references path: S2 can return the key
        # with a null value on rate-limited/partial responses.
        s2_cits = data["citations"] or []
        for cit in s2_cits[:limit]:
            if cit:
                all_papers.append(_normalise_s2(cit))
        log.info("S2: found %d citations", len(s2_cits))

    # OpenAlex: cited-by via filter
    # First resolve DOI to OpenAlex ID
    oa_data = _safe_get(
        client,
        f"{OPENALEX_BASE}/works/doi:{urllib.parse.quote(doi, safe='')}",
        "openalex",
        params=_polite({"select": "id"}),
    )
    if oa_data and "id" in oa_data:
        oa_id = oa_data["id"]
        # Audit 2026-05-02 (D-M6): the previous code requested
        # `per_page=min(limit, 50)` and never followed pagination, so a
        # `--limit 500` request returned at most 50 citing papers. Cursor
        # pagination is OpenAlex's documented mechanism for deep paging;
        # use it so `--limit` is honoured.
        results = _openalex_paginate(
            client,
            f"{OPENALEX_BASE}/works",
            _polite({
                "filter": f"cites:{oa_id}",
                "sort": "cited_by_count:desc",
            }),
            limit=limit,
        )
        for work in results:
            all_papers.append(_normalise_openalex(work))
        log.info(
            "OpenAlex: found %d citing papers", len(results),
        )

    deduped = _deduplicate(all_papers)
    # Sort by citation count descending (most-cited first)
    deduped.sort(
        key=lambda p: p.get("citation_count") or 0, reverse=True
    )
    return deduped[:limit]


# ============================================================================
# Subcommand: search
# ============================================================================


def cmd_search(
    query: str,
    client: httpx.Client,
    limit: int = DEFAULT_SEARCH_LIMIT,
) -> list[dict]:
    """
    Search for papers by keyword/title across multiple sources.

    Uses CrossRef and OpenAlex for broad coverage. Results are
    deduplicated and truncated to `limit`.
    """
    all_papers: list[dict] = []

    # CrossRef search
    data = _safe_get(
        client,
        f"{CROSSREF_BASE}/works",
        "crossref",
        params={
            "query": query,
            "rows": str(limit),
            "sort": "relevance",
            "order": "desc",
        },
    )
    if data and "message" in data:
        for item in data["message"].get("items", []):
            all_papers.append(_normalise_crossref(item))
        log.info(
            "CrossRef: found %d results",
            len(data["message"].get("items", [])),
        )

    # OpenAlex search
    data = _safe_get(
        client,
        f"{OPENALEX_BASE}/works",
        "openalex",
        params=_polite({
            "search": query,
            "per_page": str(limit),
        }),
    )
    if data and "results" in data:
        for work in data["results"]:
            all_papers.append(_normalise_openalex(work))
        log.info("OpenAlex: found %d results", len(data["results"]))

    return _deduplicate(all_papers)[:limit]


# ============================================================================
# Subcommand: openalex-cited-by
# ============================================================================


def cmd_openalex_cited_by(
    doi: str,
    client: httpx.Client,
    limit: int = DEFAULT_CITATION_LIMIT,
) -> list[dict]:
    """
    Get citing papers specifically from OpenAlex (free, high-volume).

    Useful when Semantic Scholar rate-limits or for bulk checks.
    """
    # Resolve DOI to OpenAlex ID
    oa_data = _safe_get(
        client,
        f"{OPENALEX_BASE}/works/doi:{urllib.parse.quote(doi, safe='')}",
        "openalex",
        params=_polite({"select": "id,cited_by_count"}),
    )
    if not oa_data or "id" not in oa_data:
        log.warning("Could not resolve DOI %s in OpenAlex", doi)
        return []

    oa_id = oa_data["id"]
    total_citations = oa_data.get("cited_by_count", 0)
    log.info(
        "OpenAlex: paper has %d total citations", total_citations
    )

    # Fetch citing papers via cursor pagination.
    # Audit 2026-05-02 (D-M6): the previous code took the first page only
    # (`per_page=min(limit, 50)`); a paper with 5 000 citations and a
    # `--limit 500` flag returned 50.
    raw_results = _openalex_paginate(
        client,
        f"{OPENALEX_BASE}/works",
        _polite({
            "filter": f"cites:{oa_id}",
            "sort": "cited_by_count:desc",
        }),
        limit=limit,
    )
    if not raw_results:
        log.warning("OpenAlex cited-by query returned no results")
        return []

    papers = [_normalise_openalex(w) for w in raw_results]
    papers.sort(
        key=lambda p: p.get("citation_count") or 0, reverse=True
    )
    return papers[:limit]


# ============================================================================
# Subcommand: doi-exists
# ============================================================================

# The DOI resolver's handle API answers for every registration agency
# (CrossRef, DataCite, and the rest), so it is the one place that can say a
# DOI does not exist; CrossRef answers 404 for every DOI it did not register.
# Documented in the DOI Foundation's "DOI URI Scheme" (chapters 2 and 4) and
# the Handle.Net proxy server's REST API: responseCode 1 with HTTP 200 is
# found, 100 with HTTP 404 is not found, and 200 with HTTP 200 is a handle
# with no values of the type asked for.
#
# The lookup asks for the URL values only (`?type=URL`; Shawn's design, 11
# November 2026). That can establish a URL value, but never that a DOI has
# no way to resolve: the proxy also redirects through 10320/loc values and
# follows HS_ALIAS values (Handle.Net proxy server documentation, read on 12
# November 2026), and this lookup reads neither (review finding R38, 0.3.1,
# GPT in Codex, lane astra). Nor does a URL value show that the page it
# names is up, or what the page holds: the target is never fetched. Checked
# live on 12 November 2026: `?type=URL` gave responseCode 1 with one URL
# value, at `data.value`, for 10.5281/zenodo.24128012, and an unknown type
# gave responseCode 200 with no values.
DOI_HANDLE_API = f"{DOI_RESOLVER}/api/handles"
#: Timeouts for the handle lookup: 10 s to connect, 15 s for each read,
#: write, or wait for a pooled connection. They apply to each HTTP operation,
#: not to the lookup as a whole, which `_request_with_retry` may also repeat,
#: so there is no overall deadline.
DOI_HANDLE_TIMEOUT = httpx.Timeout(15.0, connect=10.0)


#: The URL schemes a target may use.
_TARGET_SCHEMES = frozenset({"http", "https"})
#: Characters that RFC 3986 never allows unencoded anywhere in a URI.
_NEVER_IN_A_URI = frozenset(' "<>\\^`{|}')
#: Unicode categories refused in a target: control, format (such as a
#: bidirectional override), and surrogate characters.
_REFUSED_CATEGORIES = frozenset({"Cc", "Cf", "Cs"})


def _handle_value_text(data: Any) -> str | None:
    """
    Return the text that a handle value's `data` holds, or None.

    The proxy's REST API gives `data` as an object with a `format` and a
    `value` (Handle.Net proxy server documentation, read on 12 November
    2026): with "string", the value is the data as a UTF-8 string; with
    "base64" or "hex", it encodes the data's bytes. Those three formats are
    read, an encoded value only if it decodes, strictly, to UTF-8 text. Any
    other format ("admin", "vlist", "site", or one not documented), a value
    that is not a string, or an encoding that does not decode gives None: a
    representation this check does not support, which says nothing about
    whether the DOI can resolve.
    """
    if not isinstance(data, dict):
        return None
    form, value = data.get("format"), data.get("value")
    if not isinstance(value, str):
        return None
    try:
        if form == "string":
            return value
        if form == "base64":
            raw = base64.b64decode(value, validate=True)
        elif form == "hex":
            raw = bytes.fromhex(value)
        else:
            return None
        return raw.decode("utf-8")
    except (ValueError, UnicodeDecodeError):  # binascii.Error is a ValueError
        return None


def _usable_url(text: str) -> bool:
    """
    True if *text* is a well-formed absolute http or https URL.

    This checks the text alone; nothing is fetched. Refused: whitespace
    anywhere (surrounding whitespace included), a control, format, or
    surrogate character, a character RFC 3986 never allows unencoded, a
    scheme other than http or https, a relative reference, no host, and an
    authority that does not parse (an unclosed IPv6 bracket, a port that is
    not a number in range).
    """
    if not text or any(
        ch.isspace() or ch in _NEVER_IN_A_URI
        or unicodedata.category(ch) in _REFUSED_CATEGORIES
        for ch in text
    ):
        return False
    try:
        parts = urllib.parse.urlsplit(text)
        _ = parts.port  # raises ValueError for a malformed port
    except ValueError:
        return False
    return parts.scheme in _TARGET_SCHEMES and bool(parts.hostname)


def _handle_url_value(body: dict) -> tuple[str | None, int]:
    """
    Return the first usable URL value in a handle API answer, and a count.

    A usable value is an item of `values` whose `type` is `URL` and whose
    `data` holds, in a supported representation (`_handle_value_text`), a
    well-formed absolute http or https URL (`_usable_url`). It is returned
    exactly as registered. Before 0.3.1's review finding R38, any non-empty
    string passed, such as "not a URL".

    Returns:
        The URL or None, and how many values of type `URL` were read, so
        the caller can tell a handle with no URL value from one whose URL
        values this check cannot use.
    """
    values = body.get("values")
    url_values = 0
    for value in values if isinstance(values, list) else []:
        if not isinstance(value, dict) or value.get("type") != "URL":
            continue
        url_values += 1
        text = _handle_value_text(value.get("data"))
        if text is not None and _usable_url(text):
            return text, url_values
    return None, url_values


def cmd_doi_exists(doi: str, client: httpx.Client) -> dict:
    """
    Ask the DOI resolver's handle API whether *doi* holds a usable URL value.

    The returned dict's ``state`` is one of four:

    * ``resolves``: the handle holds a usable URL value (HTTP 200,
      responseCode 1, and a ``URL`` value that ``_handle_url_value``
      accepts: a well-formed absolute http or https URL, in a supported
      representation), returned as ``url``. Registration evidence only: the
      target is not fetched, so whether its page is up, and what it holds,
      are not checked. Nor is identity: whether the DOI names the expected
      work is a separate check, against a record (``metadata``).
    * ``registered_no_url``: the handle exists, but this check established
      no supported URL value: HTTP 200 with responseCode 200, which the
      handle API gives for a handle with no value of the type asked for, or
      responseCode 1 with no URL value that ``_handle_url_value`` accepts.
      Not evidence that the DOI cannot resolve, since the handle may
      redirect in a way this lookup does not read (a 10320/loc value, an
      alias); an undetermined result for a real DOI, not a fabrication.
    * ``not_found``: the resolver answered, for exactly this DOI, that it
      does not exist (HTTP 404, responseCode 100). The only authoritative
      negative.
    * ``unverifiable``: anything else, which says nothing about the DOI:
      input that is not a DOI, no answer, a rate limit, a server error, a
      redirect, a body that is not the handle API's JSON, an answer about a
      different identifier, or an unexpected pairing of status and
      responseCode.

    Input (see ``_bare_doi``): a bare DOI name is taken raw, as written, and
    is never percent-decoded, so a literal ``%23`` stays part of the name; a
    doi.org link (``https://doi.org/``, ``http://``, ``dx.``) or a ``doi:``
    URI carries the name percent-encoded, and is decoded exactly once. The
    returned ``doi`` is the name that was asked about.

    The name is percent-encoded once for the path, keeping its ``/``, so a
    suffix holding ``#``, ``?`` or ``%`` reaches the resolver whole; the
    query, ``?type=URL``, follows the encoded path. The resolver echoes the
    handle it looked up, and an answer counts only if the echo is the same
    DOI name as the one asked for: A-Z match a-z, and every other character
    must match exactly, since DOI names are case-insensitive only in the
    Basic Latin block (``_same_doi``). The request carries
    ``DOI_ORG_HEADERS`` and no key.

    Cost: one logical lookup, of up to ``MAX_RETRIES`` attempts (four by
    default) through ``_request_with_retry``, not one network request. Its
    timeouts apply to each HTTP operation, not to the lookup as a whole.
    """
    requested = _bare_doi(doi)
    result: dict[str, Any] = {
        "doi": doi.strip() if requested is None else requested,
        "state": "unverifiable",
        "url": None,
        "http_status": None,
        "response_code": None,
        "reason": "",
    }
    if requested is None:
        result["reason"] = "the link's percent-encoding does not decode as UTF-8"
        return result
    if not requested.startswith("10.") or "/" not in requested:
        result["reason"] = "not a DOI (expected 10.<prefix>/<suffix>)"
        return result

    url = f"{DOI_HANDLE_API}/{urllib.parse.quote(requested, safe='/')}?type=URL"
    try:
        resp = _request_with_retry(
            lambda: client.get(
                url, headers=DOI_ORG_HEADERS, timeout=DOI_HANDLE_TIMEOUT,
                follow_redirects=False,
            ),
            host=_host_of(url),
            source="doi.org",
        )
    except httpx.HTTPError as exc:
        result["reason"] = f"no answer from the resolver ({type(exc).__name__})"
        return result

    status = resp.status_code
    result["http_status"] = status
    if status not in (200, 404):
        # A rate limit, a server error, a redirect, or anything else the
        # handle API does not use for a completed lookup.
        result["reason"] = f"HTTP {status}: the lookup did not complete"
        return result

    try:
        body = resp.json()
    except ValueError:  # json.JSONDecodeError is a ValueError
        body = None
    if not isinstance(body, dict):
        result["reason"] = "the answer is not the handle API's JSON"
        return result

    code = body.get("responseCode")
    if isinstance(code, bool) or not isinstance(code, int):
        code = None
    result["response_code"] = code
    echoed = body.get("handle")
    if not isinstance(echoed, str) or not _same_doi(echoed, requested):
        result["reason"] = f"the answer is about a different identifier ({echoed!r})"
        return result

    # Neither reason claims more than this lookup read: it asks for URL
    # values only, and never fetches a target.
    no_url = (
        "the DOI is registered, but this check established no supported URL value: "
        "the handle gave no value of type URL (this lookup does not read 10320/loc "
        "or alias values)"
    )
    if (status, code) == (200, 1):
        target, url_values = _handle_url_value(body)
        if target is not None:
            result["state"] = "resolves"
            result["url"] = target
            result["reason"] = (
                "the handle holds a URL value, an absolute http or https URL: "
                "registration evidence only, since the target was not fetched"
            )
        else:
            result["state"] = "registered_no_url"
            result["reason"] = no_url if not url_values else (
                "the DOI is registered, but this check established no supported URL "
                f"value: none of its {url_values} URL value(s) is an absolute http or "
                "https URL in a supported representation (format string, base64, or hex)"
            )
    elif (status, code) == (200, 200):
        result["state"] = "registered_no_url"
        result["reason"] = no_url
    elif (status, code) == (404, 100):
        result["state"] = "not_found"
        result["reason"] = "the resolver answered that this DOI does not exist"
    else:
        result["reason"] = f"unexpected answer: HTTP {status} with responseCode {code!r}"
    return result


# ============================================================================
# Subcommand: bibtex
# ============================================================================


def cmd_bibtex(
    dois: list[str],
    client: httpx.Client,
) -> str:
    """
    Generate BibTeX entries for one or more DOIs.

    CrossRef's own BibTeX service is tried first. It knows only DOIs that
    CrossRef registered, so for any DOI it does not answer (an arXiv
    preprint, a Zenodo record, and other DataCite DOIs) the DOI resolver at
    doi.org is asked for BibTeX instead, which reaches whichever registry
    holds the DOI. Until 0.3.1 only CrossRef was asked, and a table of
    preprints came back almost empty while the command still succeeded.

    A source's answer counts only if it holds a complete bibliographic
    record (see `_bibtex_record`); any failure of the first source (an
    error status, a connection error after its retries, or an answer that is
    not a record) moves on to the next.

    Returns concatenated BibTeX entries as a single string. A DOI with no
    entry leaves a `% FAILED` comment in its place, naming why each source
    failed, and does not abort the run. A closing line on standard error
    says how many DOIs produced an entry and names the ones that did not,
    so that a short file is not mistaken for a complete one.
    """
    entries: list[str] = []
    # Separate client for BibTeX content negotiation — different Accept header
    bibtex_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/x-bibtex",
    }
    #: Citation keys already emitted this run, so a collision can be
    #: suffixed rather than silently shadowing an earlier entry.
    seen_keys: set[str] = set()
    missing: list[str] = []

    for doi in dois:
        # One validation drives both the file and the count: a DOI counts as
        # produced only when a source returned a complete bibliographic record.
        record, reasons = _fetch_bibtex_record(doi, client, bibtex_headers)
        if record is not None:
            entries.append(_dedupe_bibtex_key(record, seen_keys))
            log.info("bibtex: generated entry for %s", doi)
            continue
        why = "; ".join(reasons) or "no source answered"
        log.warning("bibtex: no entry for DOI %s (%s)", doi, why)
        entries.append(f"% FAILED: {doi} ({why})\n")
        missing.append(doi)

    # Always said, at warning level so it shows whatever the log level: the
    # exit status is 0 even when entries are missing.
    made = len(dois) - len(missing)
    if missing:
        log.warning(
            "bibtex: %d of %d DOIs produced an entry; none for: %s",
            made, len(dois), ", ".join(missing),
        )
    else:
        log.warning("bibtex: %d of %d DOIs produced an entry", made, len(dois))

    return "\n\n".join(entries) + "\n"


# ============================================================================
# Helpers
# ============================================================================


#: The citation key of a BibTeX entry: "@type{key," on the opening line.
_BIBTEX_KEY = re.compile(r"^(@\w+\s*[{(])([^,]+)(,)", re.MULTILINE)

#: Month macros that registries write beyond BibTeX's standard three letters,
#: which bibtexparser already knows. CrossRef writes "month=Sept" (found by a
#: real run of 0.3.1); names are matched without regard to case.
_EXTRA_MONTH_MACROS = {
    "sept": "September",
    **{name.lower(): name for name in (
        "January", "February", "March", "April", "May", "June", "July",
        "August", "September", "October", "November", "December",
    )},
}


def _starts_as_bibtex(text: str) -> bool:
    """
    True if the first line that is neither blank nor a "%" comment begins with "@".

    A cheap guard before parsing: an HTML landing page, or any other prose,
    is not BibTeX even if a record appears somewhere inside it.
    """
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("%"):
            continue
        return stripped.startswith("@")
    return False


def _bibtex_record(text: str) -> str | None:
    """
    Return one complete bibliographic record from a registry's answer, or None.

    Parsed with bibtexparser 1.x, not by hand (review findings R22 and R24,
    0.3.1: a hand-written grammar cut a quoted ")" short, accepted an empty
    value, and dropped @string definitions that a field relied on). The
    answer must begin, after blank and "%" comment lines, with "@". The
    record returned is the first entry with a citation key and at least one
    field with a value; empty fields are left out. @string macros (and the standard month
    names) are expanded into the fields, so the record stands alone in a
    .bib file shared with other DOIs; an undefined macro, a parse error, a
    directive alone, or a truncated record gives None, and the caller tries
    the next source. The record is written out again by bibtexparser, so its
    layout (field order, indentation) is the library's, not the registry's.
    """
    if not _starts_as_bibtex(text):
        return None
    # A fresh parser for every answer: a parser object accumulates entries
    # across calls. Non-standard types (@dataset, @software) are kept, since
    # DataCite uses them.
    parser = BibTexParser(common_strings=True, ignore_nonstandard_types=False)
    parser.bib_database.strings.update(_EXTRA_MONTH_MACROS)
    try:
        database = bibtexparser.loads(text, parser=parser)
    except Exception as exc:  # noqa: BLE001 — any parse failure means "no record"
        log.debug("bibtex: answer did not parse: %s", type(exc).__name__)
        return None
    for entry in database.entries:
        key = str(entry.get("ID", "")).strip()
        # An empty optional field ("note={}") is dropped, not a reason to refuse
        # the record (review finding R25); a record needs a key and at least one
        # field with a value. A malformed "title=" never parses as an entry.
        fields = {
            k: v for k, v in entry.items()
            if k not in ("ID", "ENTRYTYPE") and str(v).strip()
        }
        if not key or not fields:
            continue
        single = BibDatabase()
        single.entries = [{"ID": entry["ID"], "ENTRYTYPE": entry["ENTRYTYPE"], **fields}]
        writer = BibTexWriter()
        writer.indent = "  "
        return bibtexparser.dumps(single, writer).strip()
    return None


def _fetch_bibtex_record(
    doi: str, client: httpx.Client, headers: dict[str, str]
) -> tuple[str | None, list[str]]:
    """
    Ask CrossRef, then the DOI resolver, for one DOI's BibTeX record.

    Returns the first accepted record (or None) and, for each source that
    failed, a short reason. Every kind of failure moves on to the next
    source (review finding R23, 0.3.1): before, a CrossRef connection error
    that outlasted its retries skipped the resolver altogether. Each source
    keeps its own bounded retries through ``_request_with_retry``.
    """
    crossref = (
        f"{CROSSREF_BASE}/works/{urllib.parse.quote(doi, safe='')}"
        "/transform/application/x-bibtex"
    )
    # The resolver forwards to whichever registry holds the DOI (DataCite
    # for arXiv and Zenodo, among others).
    resolver = f"{DOI_RESOLVER}/{urllib.parse.quote(doi, safe='/')}"
    # CrossRef keeps the caller's headers, whose User-Agent may carry the
    # polite-pool contact address. The resolver leg, and every hop of its
    # redirects, identifies the tool alone, as the other doi.org requests do
    # (review of 9f57dc2, 0.3.1, GPT in Codex, lane astra).
    resolver_headers = {**headers, **DOI_ORG_HEADERS}
    sources = (
        ("CrossRef", crossref, "crossref", headers, False),
        ("doi.org", resolver, "doi.org", resolver_headers, True),
    )
    reasons: list[str] = []
    for label, url, source, leg_headers, follow in sources:
        try:
            if follow:
                def request(u: str = url, h: dict[str, str] = leg_headers) -> httpx.Response:
                    return client.get(u, headers=h, follow_redirects=True)
            else:
                def request(u: str = url, h: dict[str, str] = leg_headers) -> httpx.Response:
                    return client.get(u, headers=h)
            resp = _request_with_retry(request, host=_host_of(url), source=source)
        except httpx.HTTPError as exc:
            reasons.append(f"{label}: " + _redact(str(exc)).replace("\n", " "))
            continue
        if resp.status_code != 200:
            reasons.append(f"{label}: HTTP {resp.status_code}")
            continue
        text = resp.text or ""
        record = _bibtex_record(text)
        if record is None:
            reasons.append(
                f"{label}: " + ("empty response" if not text.strip()
                                else "no complete BibTeX record")
            )
            continue
        return record, reasons
    return None, reasons


def _dedupe_bibtex_key(entry: str, seen: set[str]) -> str:
    """
    Give ``entry`` a citation key unique within this run.

    Audit round 4d (E18): CrossRef derives its key from author and year,
    so two works by the same author in the same year come back with the
    SAME key. Concatenated into one .bib file, the second silently
    shadows the first in every LaTeX build — a wrong-citation bug with no
    error message anywhere. A colliding key gains a lower-case letter
    suffix, the convention BibTeX users already read as "second work by
    the same author that year".

    Args:
        entry: One BibTeX entry as returned by CrossRef.
        seen: Keys already emitted; mutated to include the key chosen.

    Returns:
        The entry, with its key replaced if it had to change.
    """
    match = _BIBTEX_KEY.search(entry)
    if not match:
        # Unparseable entry: pass it through rather than mangle it. It
        # will be visible in the output for a human to resolve.
        return entry
    key = match.group(2).strip()
    if key not in seen:
        seen.add(key)
        return entry
    for suffix in "abcdefghijklmnopqrstuvwxyz":
        candidate = f"{key}{suffix}"
        if candidate not in seen:
            break
    else:  # pragma: no cover - 27 works by one author in one year
        candidate = f"{key}-{len(seen)}"
    seen.add(candidate)
    log.warning(
        "bibtex: citation key %r already used; emitting %r instead",
        key, candidate,
    )
    return _BIBTEX_KEY.sub(
        lambda m: f"{m.group(1)}{candidate}{m.group(3)}", entry, count=1
    )


def _parse_year(value: Any) -> int | None:
    """Attempt to parse a year from various formats."""
    if value is None:
        return None
    try:
        year = int(str(value)[:4])
        return year if 1400 <= year <= 2100 else None
    except (ValueError, TypeError):
        return None


# ============================================================================
# CLI
# ============================================================================


def main() -> None:
    """Parse arguments and dispatch to the appropriate subcommand."""
    parser = argparse.ArgumentParser(
        description="Academic literature search CLI for lit-scout.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # metadata
    p_meta = subparsers.add_parser(
        "metadata", help="Full metadata for a single DOI"
    )
    p_meta.add_argument("doi", help="DOI to look up")

    # references
    p_refs = subparsers.add_parser(
        "references", help="Backward chaining: get reference list"
    )
    p_refs.add_argument("doi", help="DOI to get references for")
    p_refs.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_CITATION_LIMIT,
        help=f"Maximum results (default: {DEFAULT_CITATION_LIMIT})",
    )

    # citations
    p_cites = subparsers.add_parser(
        "citations", help="Forward chaining: get citing papers"
    )
    p_cites.add_argument("doi", help="DOI to get citations for")
    p_cites.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_CITATION_LIMIT,
        help=f"Maximum results (default: {DEFAULT_CITATION_LIMIT})",
    )

    # search
    p_search = subparsers.add_parser(
        "search", help="Keyword/title search"
    )
    p_search.add_argument("query", help="Search query")
    p_search.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_SEARCH_LIMIT,
        help=f"Maximum results (default: {DEFAULT_SEARCH_LIMIT})",
    )

    # openalex-cited-by
    p_oa = subparsers.add_parser(
        "openalex-cited-by",
        help="OpenAlex-specific cited-by (free, high volume)",
    )
    p_oa.add_argument("doi", help="DOI to get citing papers for")
    p_oa.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_CITATION_LIMIT,
        help=f"Maximum results (default: {DEFAULT_CITATION_LIMIT})",
    )

    # doi-exists
    p_exists = subparsers.add_parser(
        "doi-exists",
        help="Ask the DOI resolver whether a DOI holds a usable URL value, in any registry",
    )
    p_exists.add_argument(
        "doi",
        help="DOI to look up: a bare name, unencoded, or a doi.org link or doi: URI, "
        "percent-encoded",
    )

    # bibtex
    p_bib = subparsers.add_parser(
        "bibtex",
        help="Generate BibTeX entries for one or more DOIs",
    )
    p_bib.add_argument(
        "dois",
        nargs="+",
        help="One or more DOIs to generate BibTeX for",
    )

    args = parser.parse_args()

    with _get_client() as client:
        if args.command == "metadata":
            result = cmd_metadata(args.doi, client)
        elif args.command == "references":
            result = cmd_references(args.doi, client, args.limit)
        elif args.command == "citations":
            result = cmd_citations(args.doi, client, args.limit)
        elif args.command == "search":
            result = cmd_search(args.query, client, args.limit)
        elif args.command == "openalex-cited-by":
            result = cmd_openalex_cited_by(
                args.doi, client, args.limit
            )
        elif args.command == "doi-exists":
            result = cmd_doi_exists(args.doi, client)
        elif args.command == "bibtex":
            # BibTeX output is plain text, not JSON
            bibtex = cmd_bibtex(args.dois, client)
            sys.stdout.write(bibtex)
            return
        else:
            parser.print_help()
            sys.exit(1)

    # Output as JSON
    json.dump(result, sys.stdout, indent=2, ensure_ascii=False)
    print()  # trailing newline


if __name__ == "__main__":
    main()
