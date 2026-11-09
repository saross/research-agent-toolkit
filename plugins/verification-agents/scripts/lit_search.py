#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx>=0.27"]
# ///
"""
Academic literature search CLI for the lit-scout agent.

Provides subcommands for querying CrossRef, Semantic Scholar, and OpenAlex
APIs with automatic fallback, rate limiting, and deduplication. All output
is JSON to stdout for machine consumption by the lit-scout agent.

Usage:
    lit-search.py metadata DOI
    lit-search.py references DOI
    lit-search.py citations DOI
    lit-search.py search "QUERY"
    lit-search.py openalex-cited-by DOI

Requires: httpx. The `lit-search` wrapper beside this file runs it through `uv`, which installs
httpx on first use.
No API keys required — uses free tiers and polite pool headers.
"""

import argparse
import email.utils
import json
import logging
import os
import random
import re
import sys
import threading
import time
import urllib.parse
from collections.abc import Callable
from typing import Any

import httpx

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
S2_BASE = "https://api.semanticscholar.org/graph/v1"
OPENALEX_BASE = "https://api.openalex.org"



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
        MAX_BACKOFF, so a call can never hang indefinitely;
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
        "title": _first_or_none(raw.get("title", [])),
        "authors": authors,
        "year": year,
        "doi": raw.get("DOI"),
        "openalex_id": None,
        "s2_id": None,
        "citation_count": raw.get("is-referenced-by-count"),
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
    unchanged. Case is normalised before comparison; whitespace is
    stripped — DOIs are case-insensitive per the DOI spec.

    Audit 2026-05-02 (D-M4): switched from "winner-takes-all" to merge.
    """
    seen: dict[str, dict] = {}
    no_doi: list[dict] = []

    for paper in papers:
        doi = (paper.get("doi") or "").lower().strip()
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


def cmd_metadata(doi: str, client: httpx.Client) -> dict:
    """
    Fetch full metadata for a single paper by DOI.

    Tries CrossRef first, then Semantic Scholar, then OpenAlex.
    Merges results to produce the most complete record.
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
        return {"error": f"No metadata found for DOI: {doi}"}

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
# Subcommand: bibtex
# ============================================================================


def cmd_bibtex(
    dois: list[str],
    client: httpx.Client,
) -> str:
    """
    Generate BibTeX entries for one or more DOIs via CrossRef content
    negotiation.

    Uses CrossRef's native BibTeX support (Accept: application/x-bibtex).
    Returns concatenated BibTeX entries as a single string. Failed DOIs
    are reported to stderr but do not abort the run.
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

    for doi in dois:
        encoded = urllib.parse.quote(doi, safe='')
        url = f"{CROSSREF_BASE}/works/{encoded}/transform/application/x-bibtex"
        # Pacing + retry now flow through the shared helper, so a batch of
        # many DOIs is paced across the whole run (all hit api.crossref.org)
        # and a transient 429/5xx on one DOI is retried with backoff before
        # falling back to the same "% FAILED" marker as before.
        try:
            resp = _request_with_retry(
                lambda u=url: client.get(u, headers=bibtex_headers),
                host=_host_of(url),
                source="crossref",
            )
            if resp.status_code != 200:
                log.warning(
                    "bibtex: HTTP %d for DOI %s", resp.status_code, doi
                )
                entries.append(
                    f"% FAILED: {doi} (HTTP {resp.status_code})\n"
                )
                continue
            entry = resp.text.strip()
            if entry:
                entry = _dedupe_bibtex_key(entry, seen_keys)
                entries.append(entry)
                log.info("bibtex: generated entry for %s", doi)
            else:
                entries.append(f"% EMPTY RESPONSE: {doi}\n")
        except httpx.HTTPError as exc:
            log.warning("bibtex: request failed for %s: %s", doi, _redact(str(exc)))
            entries.append(f"% FAILED: {doi} ({_redact(str(exc))})\n")

    return "\n\n".join(entries) + "\n"


# ============================================================================
# Helpers
# ============================================================================


#: The citation key of a BibTeX entry: "@type{key," on the opening line.
_BIBTEX_KEY = re.compile(r"^(@\w+\s*\{)([^,]+)(,)", re.MULTILINE)


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
