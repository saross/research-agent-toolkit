"""
Unit tests for the lit-search helper (scripts/lit_search.py).

Tests the parsing, normalisation, deduplication, and fallback logic
using mocked HTTP responses. Does not hit real APIs.
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

# The helper lives in the plugin's scripts folder.
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import lit_search  # noqa: E402

# ============================================================================
# Fixtures: realistic API response payloads
# ============================================================================


CROSSREF_WORK = {
    "message": {
        "DOI": "10.1371/journal.pcbi.1009041",
        "title": ["Ten simple rules for making a vocabulary FAIR"],
        "author": [
            {"given": "Simon J. D.", "family": "Cox"},
            {"given": "Alejandra N.", "family": "Gonzalez-Beltran"},
        ],
        "published-print": {"date-parts": [[2021, 6, 24]]},
        "is-referenced-by-count": 37,
        "abstract": "We present ten simple rules...",
        "reference": [
            {
                "DOI": "10.1038/sdata.2016.18",
                "article-title": "The FAIR Guiding Principles",
                "author": "Wilkinson",
                "year": "2016",
            },
            {
                "DOI": "10.1371/journal.pcbi.1004743",
                "article-title": "Ten Simple Rules for Bio-ontology",
                "author": "Malone",
                "year": "2016",
            },
            {
                "unstructured": "Some unstructured reference text",
            },
        ],
    }
}


S2_PAPER = {
    "paperId": "7e2451a298b1c5c6dd7c7c881861a8cb3621f6fa",
    "title": "Ten simple rules for making a vocabulary FAIR",
    "authors": [
        {"name": "Simon J. D. Cox"},
        {"name": "Alejandra N. Gonzalez-Beltran"},
    ],
    "year": 2021,
    "abstract": "We present ten simple rules...",
    "citationCount": 35,
    "referenceCount": 38,
    "fieldsOfStudy": ["Computer Science"],
    "publicationTypes": ["JournalArticle"],
    "externalIds": {"DOI": "10.1371/journal.pcbi.1009041"},
}


S2_PAPER_WITH_REFS = {
    **S2_PAPER,
    "references": [
        {
            "paperId": "abc123",
            "title": "The FAIR Guiding Principles",
            "authors": [{"name": "Mark D. Wilkinson"}],
            "year": 2016,
            "externalIds": {"DOI": "10.1038/sdata.2016.18"},
            "citationCount": 5000,
        },
        {
            "paperId": "def456",
            "title": "A unique S2 reference",
            "authors": [{"name": "Someone Else"}],
            "year": 2020,
            "externalIds": {"DOI": "10.9999/unique"},
            "citationCount": 10,
        },
    ],
}


S2_PAPER_WITH_CITATIONS = {
    **S2_PAPER,
    "citations": [
        {
            "paperId": "cit001",
            "title": "Citing paper A",
            "authors": [{"name": "Author A"}],
            "year": 2023,
            "externalIds": {"DOI": "10.9999/cit-a"},
            "citationCount": 50,
        },
        {
            "paperId": "cit002",
            "title": "Citing paper B",
            "authors": [{"name": "Author B"}],
            "year": 2024,
            "externalIds": {"DOI": "10.9999/cit-b"},
            "citationCount": 100,
        },
    ],
}


OPENALEX_WORK = {
    "id": "https://openalex.org/W3113245274",
    "doi": "https://doi.org/10.1371/journal.pcbi.1009041",
    "display_name": "Ten simple rules for making a vocabulary FAIR",
    "publication_year": 2021,
    "cited_by_count": 40,
    "authorships": [
        {"author": {"display_name": "Simon J. D. Cox"}},
        {"author": {"display_name": "Alejandra N. Gonzalez-Beltran"}},
    ],
    "open_access": {"is_oa": True, "oa_url": "https://doi.org/10.1371/..."},
    "abstract_inverted_index": {
        "We": [0],
        "present": [1],
        "ten": [2],
        "simple": [3],
        "rules": [4],
    },
    "referenced_works": [
        "https://openalex.org/W1234",
        "https://openalex.org/W5678",
    ],
}


# ============================================================================
# Tests: normalisation
# ============================================================================


class TestNormaliseCrossRef:
    """Tests for CrossRef record normalisation."""

    def test_basic_fields(self):
        record = lit_search._normalise_crossref(CROSSREF_WORK["message"])
        assert record["title"] == "Ten simple rules for making a vocabulary FAIR"
        assert record["year"] == 2021
        assert record["doi"] == "10.1371/journal.pcbi.1009041"
        assert record["source"] == "crossref"

    def test_authors_formatted(self):
        record = lit_search._normalise_crossref(CROSSREF_WORK["message"])
        assert record["authors"] == [
            "Cox, Simon J. D.",
            "Gonzalez-Beltran, Alejandra N.",
        ]

    def test_missing_fields_are_none(self):
        record = lit_search._normalise_crossref({})
        assert record["title"] is None
        assert record["year"] is None
        assert record["doi"] is None
        assert record["authors"] == []


class TestNormaliseS2:
    """Tests for Semantic Scholar record normalisation."""

    def test_basic_fields(self):
        record = lit_search._normalise_s2(S2_PAPER)
        assert record["title"] == "Ten simple rules for making a vocabulary FAIR"
        assert record["year"] == 2021
        assert record["doi"] == "10.1371/journal.pcbi.1009041"
        assert record["s2_id"] == "7e2451a298b1c5c6dd7c7c881861a8cb3621f6fa"
        assert record["source"] == "s2"

    def test_authors_are_names(self):
        record = lit_search._normalise_s2(S2_PAPER)
        assert "Simon J. D. Cox" in record["authors"]

    def test_missing_external_ids(self):
        paper = {**S2_PAPER, "externalIds": None}
        record = lit_search._normalise_s2(paper)
        assert record["doi"] is None


class TestNormaliseOpenAlex:
    """Tests for OpenAlex record normalisation."""

    def test_basic_fields(self):
        record = lit_search._normalise_openalex(OPENALEX_WORK)
        assert record["title"] == "Ten simple rules for making a vocabulary FAIR"
        assert record["year"] == 2021
        assert record["doi"] == "10.1371/journal.pcbi.1009041"
        assert record["openalex_id"] == "https://openalex.org/W3113245274"
        assert record["source"] == "openalex"

    def test_doi_prefix_stripped(self):
        record = lit_search._normalise_openalex(OPENALEX_WORK)
        assert not record["doi"].startswith("https://")

    def test_abstract_reconstructed(self):
        record = lit_search._normalise_openalex(OPENALEX_WORK)
        assert record["abstract"] == "We present ten simple rules"


# ============================================================================
# Tests: deduplication
# ============================================================================


class TestDeduplication:
    """Tests for cross-source deduplication."""

    def test_same_doi_kept_once(self):
        papers = [
            {"doi": "10.1234/test", "title": "Paper A", "source": "crossref",
             "authors": None, "year": None},
            {"doi": "10.1234/test", "title": "Paper A", "source": "s2",
             "authors": ["Author"], "year": 2021},
        ]
        result = lit_search._deduplicate(papers)
        assert len(result) == 1

    def test_prefers_more_complete_record(self):
        papers = [
            {"doi": "10.1234/test", "title": None, "source": "crossref",
             "authors": None, "year": None, "abstract": None},
            {"doi": "10.1234/test", "title": "Full Title", "source": "s2",
             "authors": ["Author"], "year": 2021, "abstract": "Text"},
        ]
        result = lit_search._deduplicate(papers)
        assert result[0]["title"] == "Full Title"

    def test_papers_without_doi_kept(self):
        papers = [
            {"doi": None, "title": "Paper A", "source": "crossref"},
            {"doi": None, "title": "Paper B", "source": "s2"},
        ]
        result = lit_search._deduplicate(papers)
        assert len(result) == 2

    def test_case_insensitive_doi_matching(self):
        papers = [
            {"doi": "10.1234/TEST", "title": "Paper A", "source": "crossref"},
            {"doi": "10.1234/test", "title": "Paper A", "source": "s2"},
        ]
        result = lit_search._deduplicate(papers)
        assert len(result) == 1


# ============================================================================
# Tests: subcommands with mocked HTTP
# ============================================================================


class TestMetadata:
    """Tests for the metadata subcommand."""

    @patch.object(lit_search, "_safe_get")
    def test_merges_multiple_sources(self, mock_get):
        """Metadata from multiple sources is merged into one record."""
        mock_get.side_effect = [
            CROSSREF_WORK,        # CrossRef
            S2_PAPER,             # S2
            OPENALEX_WORK,        # OpenAlex
        ]
        client = MagicMock()
        result = lit_search.cmd_metadata("10.1371/journal.pcbi.1009041", client)
        assert result["title"] == "Ten simple rules for making a vocabulary FAIR"
        assert result["s2_id"] is not None
        assert result["openalex_id"] is not None
        assert "crossref" in result["sources"]

    @patch.object(lit_search, "_safe_get")
    def test_handles_all_sources_failing(self, mock_get):
        """Returns error when all sources fail."""
        mock_get.return_value = None
        client = MagicMock()
        result = lit_search.cmd_metadata("10.9999/nonexistent", client)
        assert "error" in result


class TestReferences:
    """Tests for the references (backward chaining) subcommand."""

    @patch.object(lit_search, "_safe_get")
    def test_crossref_references_parsed(self, mock_get):
        """CrossRef reference array is correctly parsed."""
        mock_get.side_effect = [
            CROSSREF_WORK,    # CrossRef
            None,             # S2 fails
            None,             # OpenAlex fails
        ]
        client = MagicMock()
        result = lit_search.cmd_references("10.1371/journal.pcbi.1009041", client)
        # CrossRef fixture has 3 references (one unstructured)
        assert len(result) >= 2
        dois = [p["doi"] for p in result if p.get("doi")]
        assert "10.1038/sdata.2016.18" in dois

    @patch.object(lit_search, "_safe_get")
    def test_crossref_fails_s2_fallback(self, mock_get):
        """Falls back to S2 when CrossRef returns nothing."""
        mock_get.side_effect = [
            {"message": {}},           # CrossRef: no references
            S2_PAPER_WITH_REFS,        # S2: has references
            None,                      # OpenAlex fails
        ]
        client = MagicMock()
        result = lit_search.cmd_references("10.1371/journal.pcbi.1009041", client)
        assert len(result) >= 1
        # Should have the unique S2 reference
        dois = [p["doi"] for p in result if p.get("doi")]
        assert "10.9999/unique" in dois

    @patch.object(lit_search, "_safe_get")
    def test_deduplicates_across_sources(self, mock_get):
        """Same DOI from CrossRef and S2 appears only once."""
        mock_get.side_effect = [
            CROSSREF_WORK,             # CrossRef: has 10.1038/sdata.2016.18
            S2_PAPER_WITH_REFS,        # S2: also has 10.1038/sdata.2016.18
            None,                      # OpenAlex fails
        ]
        client = MagicMock()
        result = lit_search.cmd_references("10.1371/journal.pcbi.1009041", client)
        fair_refs = [
            p for p in result if p.get("doi") == "10.1038/sdata.2016.18"
        ]
        assert len(fair_refs) == 1


class TestCitations:
    """Tests for the citations (forward chaining) subcommand."""

    @patch.object(lit_search, "_safe_get")
    def test_sorted_by_citation_count(self, mock_get):
        """Citations are sorted by citation count descending."""
        mock_get.side_effect = [
            S2_PAPER_WITH_CITATIONS,   # S2
            None,                       # OpenAlex DOI resolve fails
        ]
        client = MagicMock()
        result = lit_search.cmd_citations(
            "10.1371/journal.pcbi.1009041", client
        )
        assert len(result) == 2
        # Citation counts should be descending
        counts = [p.get("citation_count", 0) for p in result]
        assert counts == sorted(counts, reverse=True)

    @patch.object(lit_search, "_safe_get")
    def test_respects_limit(self, mock_get):
        """Limit parameter caps the number of results."""
        mock_get.side_effect = [
            S2_PAPER_WITH_CITATIONS,
            None,
        ]
        client = MagicMock()
        result = lit_search.cmd_citations(
            "10.1371/journal.pcbi.1009041", client, limit=1
        )
        assert len(result) <= 1


# ============================================================================
# Tests: helpers
# ============================================================================


class TestParseYear:
    """Tests for year parsing from various formats."""

    def test_string_year(self):
        assert lit_search._parse_year("2021") == 2021

    def test_int_year(self):
        assert lit_search._parse_year(2021) == 2021

    def test_none_year(self):
        assert lit_search._parse_year(None) is None

    def test_garbage_year(self):
        assert lit_search._parse_year("not-a-year") is None

    def test_date_string(self):
        assert lit_search._parse_year("2021-06-24") == 2021


class TestReconstructAbstract:
    """Tests for OpenAlex inverted index abstract reconstruction."""

    def test_basic_reconstruction(self):
        raw = {
            "abstract_inverted_index": {
                "Hello": [0],
                "world": [1],
                "foo": [2],
            }
        }
        result = lit_search._reconstruct_openalex_abstract(raw)
        assert result == "Hello world foo"

    def test_missing_index(self):
        assert lit_search._reconstruct_openalex_abstract({}) is None

    def test_repeated_words(self):
        raw = {
            "abstract_inverted_index": {
                "the": [0, 2],
                "cat": [1],
                "sat": [3],
            }
        }
        result = lit_search._reconstruct_openalex_abstract(raw)
        assert result == "the cat the sat"


class TestParseYearRangeValidation:
    """Tests for year range validation (audit fix)."""

    def test_nonsensical_small_year(self):
        assert lit_search._parse_year(3) is None

    def test_nonsensical_two_digit(self):
        assert lit_search._parse_year(20) is None

    def test_valid_historical_year(self):
        assert lit_search._parse_year(1850) == 1850

    def test_boundary_low(self):
        assert lit_search._parse_year(1400) == 1400

    def test_boundary_high(self):
        assert lit_search._parse_year(2100) == 2100

    def test_out_of_range_high(self):
        assert lit_search._parse_year(2101) is None


# ============================================================================
# Tests: _safe_get (HTTP layer)
# ============================================================================


class TestSafeGet:
    """Tests for the HTTP request wrapper with rate limiting and retries."""

    def _make_mock_response(
        self, status_code: int = 200, json_data: dict | None = None,
        raise_json_error: bool = False,
    ) -> MagicMock:
        """Create a mock httpx response."""
        mock = MagicMock()
        mock.status_code = status_code
        # Real dict, not an auto-MagicMock: headers.get("Retry-After") must
        # return a genuine miss — float(MagicMock) is 1.0, which would smuggle
        # a phantom Retry-After hint into the retry-delay calculation.
        mock.headers = {}
        if raise_json_error:
            mock.json.side_effect = json.JSONDecodeError(
                "test", "doc", 0
            )
        else:
            mock.json.return_value = json_data or {}
        return mock

    @patch.object(lit_search, "_rate_limit")
    def test_success_returns_json(self, mock_rl):
        """200 response with valid dict JSON returns the dict."""
        client = MagicMock()
        expected = {"message": {"title": "Test"}}
        client.get.return_value = self._make_mock_response(
            200, expected
        )
        result = lit_search._safe_get(client, "http://test", "crossref")
        assert result == expected

    @patch.object(lit_search, "_rate_limit")
    def test_non_200_returns_none(self, mock_rl):
        """Non-200 status code returns None."""
        client = MagicMock()
        client.get.return_value = self._make_mock_response(404)
        result = lit_search._safe_get(client, "http://test", "crossref")
        assert result is None

    @patch("time.sleep")
    def test_429_then_success_returns_second_response(self, mock_sleep):
        """429 then 200: one backed-off retry recovers the response.

        The delay itself is jittered (fbe743c, 2026-06-06), so assert that
        a sleep happened — never its exact value.
        """
        client = MagicMock()
        expected = {"message": "ok"}
        client.get.side_effect = [
            self._make_mock_response(429),
            self._make_mock_response(200, expected),
        ]
        result = lit_search._safe_get(client, "http://test", "s2")
        assert result == expected
        assert client.get.call_count == 2
        assert mock_sleep.called

    @patch("time.sleep")
    def test_429_exhausts_retries_returns_none(self, mock_sleep):
        """429 on every attempt: MAX_RETRIES attempts, then None."""
        client = MagicMock()
        client.get.side_effect = [
            self._make_mock_response(429)
            for _ in range(lit_search.MAX_RETRIES)
        ]
        result = lit_search._safe_get(client, "http://test", "s2")
        assert result is None
        assert client.get.call_count == lit_search.MAX_RETRIES

    @patch("time.sleep")
    def test_network_error_returns_none(self, mock_sleep):
        """Connection errors are retried, then degrade to None.

        time.sleep MUST be patched here: connection errors became
        retryable in fbe743c, and the unpatched backoff slept ~16 real
        seconds per run while the test still passed.
        """
        client = MagicMock()
        client.get.side_effect = httpx.ConnectError("Connection refused")
        result = lit_search._safe_get(client, "http://test", "crossref")
        assert result is None
        assert client.get.call_count == lit_search.MAX_RETRIES

    @patch.object(lit_search, "_rate_limit")
    def test_invalid_json_returns_none(self, mock_rl):
        """Valid HTTP but invalid JSON returns None."""
        client = MagicMock()
        client.get.return_value = self._make_mock_response(
            200, raise_json_error=True
        )
        result = lit_search._safe_get(client, "http://test", "crossref")
        assert result is None

    @patch.object(lit_search, "_rate_limit")
    def test_non_dict_json_returns_none(self, mock_rl):
        """JSON response that is a list (not dict) returns None."""
        client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = ["not", "a", "dict"]
        client.get.return_value = mock_resp
        result = lit_search._safe_get(client, "http://test", "crossref")
        assert result is None


# ============================================================================
# Tests: cmd_search
# ============================================================================


CROSSREF_SEARCH_RESPONSE = {
    "message": {
        "items": [
            {
                "DOI": "10.1234/paper-a",
                "title": ["Paper A about FAIR"],
                "author": [{"given": "Alice", "family": "Smith"}],
                "published-print": {"date-parts": [[2021]]},
                "is-referenced-by-count": 10,
            },
            {
                "DOI": "10.1234/paper-b",
                "title": ["Paper B about SKOS"],
                "author": [{"given": "Bob", "family": "Jones"}],
                "published-print": {"date-parts": [[2022]]},
                "is-referenced-by-count": 5,
            },
        ]
    }
}


OPENALEX_SEARCH_RESPONSE = {
    "results": [
        {
            "id": "https://openalex.org/W999",
            "doi": "https://doi.org/10.1234/paper-a",
            "display_name": "Paper A about FAIR",
            "publication_year": 2021,
            "cited_by_count": 12,
            "authorships": [
                {"author": {"display_name": "Alice Smith"}}
            ],
        },
        {
            "id": "https://openalex.org/W888",
            "doi": "https://doi.org/10.5678/paper-c",
            "display_name": "Paper C unique to OpenAlex",
            "publication_year": 2023,
            "cited_by_count": 3,
            "authorships": [
                {"author": {"display_name": "Carol Lee"}}
            ],
        },
    ]
}


class TestOpenAlexApiKey:
    """Tests for OpenAlex key attachment (`_with_openalex_key`).

    A free OpenAlex key raises the daily budget from $0.10 to $1.00. It is
    attached per request rather than as a client header because one
    `httpx.Client` serves five APIs; sending the user's credential to the
    other four would be a leak, so `test_key_not_sent_to_other_hosts` is
    the load-bearing case here.
    """

    OPENALEX_URL = "https://api.openalex.org/works"
    CROSSREF_URL = "https://api.crossref.org/works"

    def test_no_key_leaves_params_untouched(self):
        """Absent a key, params pass through unchanged — same object."""
        with patch.object(lit_search, "OPENALEX_API_KEY", ""):
            params = {"filter": "doi:10.1234/x"}
            result = lit_search._with_openalex_key(
                "api.openalex.org", params
            )
            assert result is params

    def test_no_key_leaves_none_as_none(self):
        """Absent a key, a None params stays None (no empty dict)."""
        with patch.object(lit_search, "OPENALEX_API_KEY", ""):
            assert lit_search._with_openalex_key(
                "api.openalex.org", None
            ) is None

    def test_key_attached_for_openalex_host(self):
        """With a key, OpenAlex requests carry it as `api_key`."""
        with patch.object(lit_search, "OPENALEX_API_KEY", "secret-key"):
            result = lit_search._with_openalex_key(
                "api.openalex.org", {"filter": "doi:10.1234/x"}
            )
            assert result["api_key"] == "secret-key"
            assert result["filter"] == "doi:10.1234/x"

    def test_key_attached_when_params_is_none(self):
        """A keyed request with no other params still gets the key."""
        with patch.object(lit_search, "OPENALEX_API_KEY", "secret-key"):
            assert lit_search._with_openalex_key(
                "api.openalex.org", None
            ) == {"api_key": "secret-key"}

    def test_caller_params_not_mutated(self):
        """The caller's dict is copied, not modified in place."""
        with patch.object(lit_search, "OPENALEX_API_KEY", "secret-key"):
            params = {"filter": "doi:10.1234/x"}
            lit_search._with_openalex_key("api.openalex.org", params)
            assert "api_key" not in params

    def test_explicit_api_key_wins(self):
        """A caller-supplied api_key is left alone."""
        with patch.object(lit_search, "OPENALEX_API_KEY", "env-key"):
            result = lit_search._with_openalex_key(
                "api.openalex.org", {"api_key": "caller-key"}
            )
            assert result["api_key"] == "caller-key"

    @pytest.mark.parametrize(
        "host",
        [
            "api.crossref.org",
            "api.datacite.org",
            "api.semanticscholar.org",
            "export.arxiv.org",
        ],
    )
    def test_key_not_sent_to_other_hosts(self, host):
        """The key never travels to a non-OpenAlex host."""
        with patch.object(lit_search, "OPENALEX_API_KEY", "secret-key"):
            params = {"query": "archaeology"}
            result = lit_search._with_openalex_key(host, params)
            assert result is params
            assert "api_key" not in result

    @patch.object(lit_search, "_rate_limit")
    def test_safe_get_sends_key_to_openalex(self, mock_rl):
        """End to end: `_safe_get` puts the key on an OpenAlex call."""
        client = MagicMock()
        resp = MagicMock()
        resp.status_code = 200
        resp.headers = {}
        resp.json.return_value = {"results": []}
        client.get.return_value = resp
        with patch.object(lit_search, "OPENALEX_API_KEY", "secret-key"):
            lit_search._safe_get(
                client, self.OPENALEX_URL, "openalex",
                params={"filter": "doi:10.1234/x"},
            )
        sent = client.get.call_args.kwargs["params"]
        assert sent["api_key"] == "secret-key"

    @patch.object(lit_search, "_rate_limit")
    def test_safe_get_withholds_key_from_crossref(self, mock_rl):
        """End to end: a CrossRef call carries no OpenAlex key."""
        client = MagicMock()
        resp = MagicMock()
        resp.status_code = 200
        resp.headers = {}
        resp.json.return_value = {"message": {}}
        client.get.return_value = resp
        with patch.object(lit_search, "OPENALEX_API_KEY", "secret-key"):
            lit_search._safe_get(
                client, self.CROSSREF_URL, "crossref",
                params={"query": "archaeology"},
            )
        sent = client.get.call_args.kwargs["params"]
        assert "api_key" not in sent


class TestSearch:
    """Tests for the search subcommand."""

    @patch.object(lit_search, "_safe_get")
    def test_crossref_and_openalex_merged(self, mock_get):
        """Results from both sources are merged and deduplicated."""
        mock_get.side_effect = [
            CROSSREF_SEARCH_RESPONSE,
            OPENALEX_SEARCH_RESPONSE,
        ]
        client = MagicMock()
        result = lit_search.cmd_search("FAIR vocabulary", client)
        # Paper A appears in both — should be deduped
        # Papers B and C are unique → 3 total
        assert len(result) == 3
        dois = [p.get("doi") for p in result if p.get("doi")]
        assert "10.1234/paper-a" in dois
        assert "10.1234/paper-b" in dois
        assert "10.5678/paper-c" in dois

    @patch.object(lit_search, "_safe_get")
    def test_respects_limit_after_dedup(self, mock_get):
        """Limit is enforced after deduplication."""
        mock_get.side_effect = [
            CROSSREF_SEARCH_RESPONSE,     # 2 papers
            OPENALEX_SEARCH_RESPONSE,     # 1 unique + 1 dup = 3 total
        ]
        client = MagicMock()
        result = lit_search.cmd_search("FAIR", client, limit=2)
        assert len(result) <= 2


# ============================================================================
# Tests: cmd_openalex_cited_by
# ============================================================================


OPENALEX_RESOLVE_RESPONSE = {
    "id": "https://openalex.org/W3113245274",
    "cited_by_count": 40,
}


OPENALEX_CITED_BY_RESPONSE = {
    "results": [
        {
            "id": "https://openalex.org/W111",
            "doi": "https://doi.org/10.9999/citer-1",
            "display_name": "Paper that cites target",
            "publication_year": 2023,
            "cited_by_count": 25,
            "authorships": [
                {"author": {"display_name": "Dan Brown"}}
            ],
        },
    ]
}


class TestOpenAlexCitedBy:
    """Tests for the openalex-cited-by subcommand."""

    @patch.object(lit_search, "_safe_get")
    def test_returns_citing_papers(self, mock_get):
        """DOI resolves and citing papers are returned."""
        mock_get.side_effect = [
            OPENALEX_RESOLVE_RESPONSE,
            OPENALEX_CITED_BY_RESPONSE,
        ]
        client = MagicMock()
        result = lit_search.cmd_openalex_cited_by(
            "10.1371/journal.pcbi.1009041", client
        )
        assert len(result) == 1
        assert result[0]["doi"] == "10.9999/citer-1"

    @patch.object(lit_search, "_safe_get")
    def test_doi_not_found_returns_empty(self, mock_get):
        """DOI resolution fails → empty list."""
        mock_get.return_value = None
        client = MagicMock()
        result = lit_search.cmd_openalex_cited_by(
            "10.9999/nonexistent", client
        )
        assert result == []

    @patch.object(lit_search, "_safe_get")
    def test_no_citations_returns_empty(self, mock_get):
        """DOI resolves but no citing papers → empty list."""
        mock_get.side_effect = [
            OPENALEX_RESOLVE_RESPONSE,
            {"results": []},
        ]
        client = MagicMock()
        result = lit_search.cmd_openalex_cited_by(
            "10.1371/journal.pcbi.1009041", client
        )
        assert result == []


# ============================================================================
# Tests: cmd_bibtex
# ============================================================================


SAMPLE_BIBTEX = (
    "@article{Walters_2023, title={Fabrication and errors in the "
    "bibliographic citations generated by ChatGPT}, author={Walters, "
    "William H. and Wilder, Esther Isabelle}, year={2023} }"
)


class TestBibtex:
    """Tests for the bibtex subcommand."""

    @patch.object(lit_search, "_rate_limit")
    def test_single_doi_returns_entry(self, mock_rl):
        """Single DOI returns its BibTeX entry."""
        client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = SAMPLE_BIBTEX
        client.get.return_value = mock_resp

        result = lit_search.cmd_bibtex(
            ["10.1038/s41598-023-41032-5"], client
        )
        assert "Walters_2023" in result
        assert "Fabrication and errors" in result

    @patch.object(lit_search, "_rate_limit")
    def test_multiple_dois_concatenated(self, mock_rl):
        """Multiple DOIs return concatenated entries."""
        client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = SAMPLE_BIBTEX
        client.get.return_value = mock_resp

        result = lit_search.cmd_bibtex(
            ["10.1/a", "10.1/b", "10.1/c"], client
        )
        assert result.count("Walters_2023") == 3
        assert client.get.call_count == 3

    @patch.object(lit_search, "_rate_limit")
    def test_failed_doi_leaves_comment(self, mock_rl):
        """A 404 response leaves a comment marker, not blank."""
        client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        client.get.return_value = mock_resp

        result = lit_search.cmd_bibtex(["10.9999/nonexistent"], client)
        assert "FAILED" in result
        assert "10.9999/nonexistent" in result

    @patch.object(lit_search, "_rate_limit")
    def test_mixed_success_and_failure(self, mock_rl):
        """One DOI succeeds, one fails — both represented in output."""
        client = MagicMock()
        good_resp = MagicMock()
        good_resp.status_code = 200
        good_resp.text = SAMPLE_BIBTEX
        bad_resp = MagicMock()
        bad_resp.status_code = 404
        client.get.side_effect = [good_resp, bad_resp]

        result = lit_search.cmd_bibtex(
            ["10.1/good", "10.1/bad"], client
        )
        assert "Walters_2023" in result
        assert "FAILED" in result

    @patch("time.sleep")
    @patch.object(lit_search, "_rate_limit")
    def test_network_error_leaves_comment(self, mock_rl, mock_sleep):
        """httpx network error leaves a comment marker.

        time.sleep MUST be patched: connection errors are retried with
        real backoff since fbe743c (~12 s unpatched)."""
        client = MagicMock()
        client.get.side_effect = httpx.ConnectError("refused")

        result = lit_search.cmd_bibtex(["10.9999/oops"], client)
        assert "FAILED" in result
        assert "10.9999/oops" in result


# ============================================================================
# Tests: Batch 9 — Cluster D pagination correctness (D-M4, D-M5, D-M6)
# ============================================================================


def _openalex_page(results, next_cursor):
    """Build an OpenAlex-shaped response page for pagination tests."""
    return {
        "results": results,
        "meta": {"next_cursor": next_cursor},
    }


def _openalex_work(idx: int, citations: int = 0) -> dict:
    """Synthesise a minimal OpenAlex work record for pagination tests."""
    return {
        "id": f"https://openalex.org/W{idx:06d}",
        "doi": f"https://doi.org/10.9999/page-{idx}",
        "display_name": f"Paper {idx}",
        "publication_year": 2024,
        "cited_by_count": citations,
        "authorships": [
            {"author": {"display_name": f"Author {idx}"}}
        ],
    }


class TestOpenAlexCursorPagination:
    """
    D-M6 pin: OpenAlex cursor pagination must use the API's documented
    `cursor=*` opaque-token mechanism, not page-number / offset paging,
    and must follow `meta.next_cursor` until exhausted or `limit` met.
    """

    @patch.object(lit_search, "_safe_get")
    def test_initial_request_uses_star_cursor(self, mock_get):
        """First request sets cursor=* — the OpenAlex initial token."""
        mock_get.return_value = _openalex_page(
            [_openalex_work(1)], next_cursor=None,
        )
        client = MagicMock()
        lit_search._openalex_paginate(
            client, "http://test/works", {"filter": "x"}, limit=5,
        )
        # Inspect the params actually passed
        first_call_kwargs = mock_get.call_args_list[0].kwargs
        params = first_call_kwargs["params"]
        assert params["cursor"] == "*"
        # And we should NOT be using `page=` offset paging.
        assert "page" not in params

    @patch.object(lit_search, "_safe_get")
    def test_follows_next_cursor_to_completion(self, mock_get):
        """The helper follows meta.next_cursor across multiple pages."""
        mock_get.side_effect = [
            _openalex_page(
                [_openalex_work(i) for i in range(3)],
                next_cursor="cursor-page-2",
            ),
            _openalex_page(
                [_openalex_work(i) for i in range(3, 6)],
                next_cursor="cursor-page-3",
            ),
            _openalex_page(
                [_openalex_work(i) for i in range(6, 8)],
                next_cursor=None,
            ),
        ]
        client = MagicMock()
        results = lit_search._openalex_paginate(
            client, "http://test/works", {"filter": "x"}, limit=100,
        )
        assert len(results) == 8
        # Subsequent requests pass the cursor returned by the previous
        # page — proving cursor-token threading.
        cursors_used = [
            call.kwargs["params"]["cursor"]
            for call in mock_get.call_args_list
        ]
        assert cursors_used == ["*", "cursor-page-2", "cursor-page-3"]

    @patch.object(lit_search, "_safe_get")
    def test_limit_caps_total_results(self, mock_get):
        """The helper stops once `limit` results have been collected."""
        # Each page returns 50 records and a cursor; we ask for 75.
        mock_get.side_effect = [
            _openalex_page(
                [_openalex_work(i) for i in range(50)],
                next_cursor="page-2",
            ),
            _openalex_page(
                [_openalex_work(i) for i in range(50, 100)],
                next_cursor="page-3",
            ),
        ]
        client = MagicMock()
        results = lit_search._openalex_paginate(
            client, "http://test/works", {"filter": "x"}, limit=75,
        )
        assert len(results) == 75

    @patch.object(lit_search, "_safe_get")
    def test_stops_on_repeated_cursor(self, mock_get):
        """A misbehaving API echoing the same cursor must not infinite-loop."""
        # API returns the same cursor over and over with one record each.
        mock_get.side_effect = [
            _openalex_page([_openalex_work(0)], next_cursor="stuck"),
            _openalex_page([_openalex_work(1)], next_cursor="stuck"),
            _openalex_page([_openalex_work(2)], next_cursor="stuck"),
        ]
        client = MagicMock()
        # The helper deduplicates seen cursors, so the second time it
        # encounters "stuck" it stops.
        results = lit_search._openalex_paginate(
            client, "http://test/works", {"filter": "x"}, limit=100,
        )
        # First page (cursor=*) yields 1 record; second page
        # (cursor=stuck) yields another, then we refuse to chase
        # "stuck" again. So at most 2 records.
        assert len(results) <= 2

    @patch.object(lit_search, "_safe_get")
    def test_per_page_never_exceeds_api_max(self, mock_get):
        """`per_page` must never exceed OPENALEX_PER_PAGE_MAX (200)."""
        mock_get.return_value = _openalex_page(
            [_openalex_work(i) for i in range(200)],
            next_cursor=None,
        )
        client = MagicMock()
        lit_search._openalex_paginate(
            client, "http://test/works", {"filter": "x"}, limit=10_000,
        )
        for call in mock_get.call_args_list:
            params = call.kwargs["params"]
            assert int(params["per_page"]) <= lit_search.OPENALEX_PER_PAGE_MAX

    @patch.object(lit_search, "_safe_get")
    def test_safe_get_failure_terminates(self, mock_get):
        """A `None` return from `_safe_get` stops the loop cleanly."""
        mock_get.return_value = None
        client = MagicMock()
        results = lit_search._openalex_paginate(
            client, "http://test/works", {"filter": "x"}, limit=50,
        )
        assert results == []


class TestCitationsLimitHonoured:
    """
    D-M6 pin: cmd_citations must return more than 50 results when the
    user asks for more and the API has them.
    """

    @patch.object(lit_search, "_safe_get")
    def test_citations_returns_more_than_50_when_requested(self, mock_get):
        """`--limit 100` returns ~100 results, not silently capped at 50."""
        # First call: S2 paper (no citations envelope to keep it simple)
        # Second call: OpenAlex DOI resolve
        # Subsequent calls: paginated `_safe_get` for the cursor walk
        s2_response = {**S2_PAPER, "citations": []}
        oa_resolve = {"id": "https://openalex.org/W123"}
        # Two pages of 50 OpenAlex citing papers → 100 records total.
        page_1 = _openalex_page(
            [_openalex_work(i, citations=100 - i) for i in range(50)],
            next_cursor="page-2",
        )
        page_2 = _openalex_page(
            [_openalex_work(i, citations=100 - i) for i in range(50, 100)],
            next_cursor=None,
        )
        mock_get.side_effect = [
            s2_response,
            oa_resolve,
            page_1,
            page_2,
        ]
        client = MagicMock()
        result = lit_search.cmd_citations(
            "10.1371/journal.pcbi.1009041", client, limit=100,
        )
        # Each OpenAlex paper has a unique DOI so no dedup collapse.
        assert len(result) == 100


class TestOpenAlexCitedByLimitHonoured:
    """
    D-M6 pin: cmd_openalex_cited_by must paginate beyond the first 50.
    """

    @patch.object(lit_search, "_safe_get")
    def test_returns_more_than_50_when_requested(self, mock_get):
        """`--limit 75` returns 75 papers, not 50."""
        oa_resolve = {
            "id": "https://openalex.org/W123",
            "cited_by_count": 200,
        }
        page_1 = _openalex_page(
            [_openalex_work(i, citations=100 - i) for i in range(50)],
            next_cursor="page-2",
        )
        page_2 = _openalex_page(
            [_openalex_work(i, citations=100 - i) for i in range(50, 100)],
            next_cursor="page-3",
        )
        mock_get.side_effect = [oa_resolve, page_1, page_2]
        client = MagicMock()
        result = lit_search.cmd_openalex_cited_by(
            "10.1371/journal.pcbi.1009041", client, limit=75,
        )
        assert len(result) == 75


class TestReferencesLimitHonoured:
    """
    D-M5 pin: cmd_references' OpenAlex contribution must respect the
    user's `--limit`, not silently truncate at DEFAULT_CITATION_LIMIT (50).
    """

    @patch.object(lit_search, "_safe_get")
    def test_openalex_contribution_uses_limit_not_default(self, mock_get):
        """When --limit=100, OpenAlex resolves up to 100 referenced_works."""
        # 1) CrossRef returns no useful refs
        # 2) S2 returns no refs
        # 3) OpenAlex DOI resolve returns 100 referenced_works
        # 4) The paginated batch resolves them all
        crossref_empty = {"message": {}}
        s2_empty = {"references": []}
        oa_resolve = {
            "referenced_works": [
                f"https://openalex.org/W{i:06d}" for i in range(100)
            ],
        }
        page_1 = _openalex_page(
            [_openalex_work(i) for i in range(100)],
            next_cursor=None,
        )
        mock_get.side_effect = [
            crossref_empty,
            s2_empty,
            oa_resolve,
            page_1,
        ]
        client = MagicMock()
        result = lit_search.cmd_references(
            "10.1371/journal.pcbi.1009041", client, limit=100,
        )
        # Each OpenAlex work has a unique DOI; no dedup loss.
        assert len(result) == 100

    @patch.object(lit_search, "_safe_get")
    def test_openalex_truncates_to_limit_not_default(self, mock_get):
        """
        Inverse of the bug: when `referenced_works` has 200 entries and
        the user asks for `--limit 30`, OpenAlex should request only 30,
        not the old hard-coded 50.
        """
        crossref_empty = {"message": {}}
        s2_empty = {"references": []}
        oa_resolve = {
            "referenced_works": [
                f"https://openalex.org/W{i:06d}" for i in range(200)
            ],
        }
        page_1 = _openalex_page(
            [_openalex_work(i) for i in range(30)],
            next_cursor=None,
        )
        mock_get.side_effect = [
            crossref_empty, s2_empty, oa_resolve, page_1,
        ]
        client = MagicMock()
        result = lit_search.cmd_references(
            "10.1371/journal.pcbi.1009041", client, limit=30,
        )
        assert len(result) <= 30
        # Final result is capped at limit — pin the cap.
        # And we should not have asked OpenAlex to resolve more than 30
        # IDs; inspect the filter parameter on the paginated call.
        # Calls: CrossRef(0), S2(1), OpenAlex resolve(2), paginate page(3).
        paginate_call_params = mock_get.call_args_list[3].kwargs["params"]
        id_filter = paginate_call_params["filter"]
        # The filter is "openalex:id1|id2|..." — count the ids.
        ids_passed = id_filter.split(":", 1)[1].split("|")
        assert len(ids_passed) <= 30


class TestDedupeMergesAcrossPageBoundaries:
    """
    D-M4 pin: when the same record appears across two paginated pages
    (e.g., concurrent edits or sort-tie reorderings), `_deduplicate`
    must merge complementary fields, not emit two records.
    """

    def test_complementary_fields_are_merged_not_dropped(self):
        """
        CrossRef record on page 1 has DOI+year+title but no abstract;
        OpenAlex record on page 2 has DOI+abstract+citation_count but
        no year. The merged record retains both year and abstract.
        """
        page_one_record = {
            "doi": "10.1234/dup",
            "title": "Paper",
            "year": 2021,
            "authors": ["Smith"],
            "abstract": None,
            "citation_count": None,
            "source": "crossref",
        }
        page_two_record = {
            "doi": "10.1234/dup",
            "title": "Paper",
            "year": None,
            "authors": [],
            "abstract": "Long-form abstract text.",
            "citation_count": 42,
            "source": "openalex",
        }
        merged = lit_search._deduplicate(
            [page_one_record, page_two_record]
        )
        assert len(merged) == 1
        record = merged[0]
        assert record["year"] == 2021
        assert record["abstract"] == "Long-form abstract text."
        assert record["citation_count"] == 42

    def test_record_emitted_once_not_twice(self):
        """Two API responses for the same DOI collapse to one record."""
        page_one = [
            {"doi": "10.1234/a", "title": "A", "source": "crossref"},
            {"doi": "10.1234/b", "title": "B", "source": "crossref"},
        ]
        page_two = [
            # 'a' reappears on page 2 (e.g., concurrent edit shifts pos)
            {"doi": "10.1234/a", "title": "A", "source": "openalex"},
            {"doi": "10.1234/c", "title": "C", "source": "openalex"},
        ]
        result = lit_search._deduplicate(page_one + page_two)
        dois = sorted([p["doi"] for p in result])
        assert dois == ["10.1234/a", "10.1234/b", "10.1234/c"]
        # And the merged 'a' record carries both contributing sources.
        a_record = next(p for p in result if p["doi"] == "10.1234/a")
        sources = a_record.get("sources") or []
        assert "crossref" in sources
        assert "openalex" in sources

    def test_merge_preserves_when_one_record_has_extra_field(self):
        """
        Field present on only one record survives the merge — this is
        the heart of D-M4: complementary fields no longer dropped.
        """
        record_a = {
            "doi": "10.1234/x",
            "title": "X",
            "s2_id": "S2-XYZ",
            "abstract": None,
            "source": "s2",
        }
        record_b = {
            "doi": "10.1234/x",
            "title": "X",
            "abstract": "Abstract from CrossRef",
            "source": "crossref",
        }
        merged = lit_search._deduplicate([record_a, record_b])
        assert len(merged) == 1
        assert merged[0]["s2_id"] == "S2-XYZ"
        assert merged[0]["abstract"] == "Abstract from CrossRef"


# ============================================================================
# ET4 / ET17 / E3 / E18 / E19 — the transport layer and the missing shapes
#
# Every test above patches `_safe_get` or `client.get`, so the transport
# itself was unpinned: deleting per-host pacing (:262), ignoring
# `Retry-After` entirely (:395), and flattening or uncapping the backoff
# (:322, :324) all survived the suite (lens B, tranche 5, findings 4 and
# 17). And the Semantic Scholar credential was set on the shared client, so
# it went to CrossRef, DataCite, and OpenAlex on every call (lens A, 3).
#
# All keys, hostnames, and payloads below are invented.
# ============================================================================



class FakeResponse:
    """A minimal stand-in for ``httpx.Response``."""

    def __init__(self, status_code=200, payload=None, headers=None, text=""):
        """Store the status, JSON payload, headers, and body text."""
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.headers = headers or {}
        self.text = text

    def json(self):
        """Return the stored payload."""
        return self._payload


class RecordingClient:
    """An ``httpx.Client`` stand-in recording every ``get`` call."""

    def __init__(self, responses=None):
        """Queue ``responses`` (or always answer 200 with an empty body)."""
        self.calls = []
        self._responses = list(responses or [])

    def get(self, url, params=None, headers=None):
        """Record the call and return the next queued response."""
        self.calls.append({"url": url, "params": params, "headers": headers})
        if self._responses:
            return self._responses.pop(0)
        return FakeResponse()


@pytest.fixture
def no_real_sleep(monkeypatch):
    """Record every sleep instead of performing it."""
    slept: list[float] = []
    monkeypatch.setattr(lit_search.time, "sleep", slept.append)
    return slept


@pytest.fixture
def reset_pacing(monkeypatch):
    """Give each test a clean per-host pacing state."""
    monkeypatch.setattr(lit_search, "_last_request", {})


class TestPerHostPacing:
    """ET4 — the pacing floor, which deleting made the suite 17x faster."""

    def test_two_calls_to_one_host_are_spaced(
        self, monkeypatch, no_real_sleep, reset_pacing
    ):
        """The second call sleeps at least the host's floor."""
        # A frozen clock well past zero: the first call to a host sees no
        # prior timestamp and must not sleep; the second sees the first.
        monkeypatch.setattr(lit_search.time, "monotonic", lambda: 1000.0)
        client = RecordingClient()
        url = f"https://{lit_search.CROSSREF_HOST}/works/10.1/a"

        lit_search._safe_get(client, url, "crossref")
        lit_search._safe_get(client, url, "crossref")

        floor = lit_search.HOST_MIN_INTERVAL[lit_search.CROSSREF_HOST]
        assert no_real_sleep, "no pacing sleep between two calls to one host"
        assert max(no_real_sleep) >= floor

    def test_different_hosts_are_not_paced_against_each_other(
        self, monkeypatch, no_real_sleep, reset_pacing
    ):
        """A CrossRef call must not wait on an OpenAlex one."""
        monkeypatch.setattr(lit_search.time, "monotonic", lambda: 1000.0)
        client = RecordingClient()

        lit_search._safe_get(
            client, f"https://{lit_search.CROSSREF_HOST}/works/1", "crossref"
        )
        lit_search._safe_get(
            client, f"https://{lit_search.OPENALEX_HOST}/works/1", "openalex"
        )

        assert no_real_sleep == [], no_real_sleep


class TestRetryAfterAndBackoff:
    """ET4 / ET17 — the 429 contract and the shape of the backoff."""

    def test_retry_after_is_honoured_on_429(
        self, monkeypatch, no_real_sleep, reset_pacing
    ):
        """A generous Retry-After wins over the exponential floor."""
        monkeypatch.setattr(lit_search.time, "monotonic", lambda: 1000.0)
        monkeypatch.setattr(lit_search, "MAX_BACKOFF", 120.0)
        monkeypatch.setattr(lit_search, "_backoff_delay", lambda attempt: 1.0)
        client = RecordingClient(
            [
                FakeResponse(429, headers={"Retry-After": "42"}),
                FakeResponse(200, {"ok": True}),
            ]
        )

        result = lit_search._safe_get(
            client, f"https://{lit_search.S2_HOST}/graph/v1/paper/x", "s2"
        )

        assert result == {"ok": True}
        assert 42.0 in no_real_sleep, no_real_sleep

    def test_backoff_grows_and_is_capped(self, monkeypatch):
        """ET17 — the delay is exponential, and never exceeds the cap."""
        monkeypatch.setattr(lit_search.random, "uniform", lambda a, b: 0.0)
        monkeypatch.setattr(lit_search, "BASE_BACKOFF", 2.0)
        monkeypatch.setattr(lit_search, "MAX_BACKOFF", 10.0)

        delays = [lit_search._backoff_delay(n) for n in range(5)]

        assert delays[0] == 2.0
        assert delays[1] == 4.0
        assert delays[2] == 8.0
        assert delays[1] > delays[0], "the backoff is flat, not exponential"
        assert all(d <= 10.0 for d in delays), delays
        assert delays[-1] == 10.0, "the cap is not applied"


class TestCredentialScope:
    """E3 — the Semantic Scholar key goes to Semantic Scholar only."""

    def test_the_key_is_sent_to_semantic_scholar(
        self, monkeypatch, reset_pacing
    ):
        """The S2 request carries x-api-key."""
        monkeypatch.setattr(
            lit_search, "S2_API_KEY", "synthetic-s2-key-not-a-secret"
        )
        client = RecordingClient()

        lit_search._safe_get(
            client, f"https://{lit_search.S2_HOST}/graph/v1/paper/x", "s2"
        )

        headers = client.calls[0]["headers"] or {}
        assert headers.get("x-api-key") == "synthetic-s2-key-not-a-secret"

    @pytest.mark.parametrize(
        "host",
        ["api.crossref.org", "api.openalex.org", "api.datacite.org"],
    )
    def test_the_key_is_never_sent_elsewhere(
        self, monkeypatch, reset_pacing, host
    ):
        """CrossRef, OpenAlex, and DataCite see no Semantic Scholar key."""
        monkeypatch.setattr(
            lit_search, "S2_API_KEY", "synthetic-s2-key-not-a-secret"
        )
        client = RecordingClient()

        lit_search._safe_get(client, f"https://{host}/works/10.1/a", host)

        headers = client.calls[0]["headers"] or {}
        assert "x-api-key" not in headers, headers

    def test_the_shared_client_carries_no_credential(self, monkeypatch):
        """The client's own headers must hold neither key."""
        monkeypatch.setattr(
            lit_search, "S2_API_KEY", "synthetic-s2-key-not-a-secret"
        )
        client = lit_search._get_client()
        try:
            assert "x-api-key" not in client.headers
            assert "api_key" not in client.headers
        finally:
            client.close()

    def test_a_cross_host_redirect_cannot_carry_the_key(self):
        """The request hook strips the key from a non-S2 request."""
        request = httpx.Request(
            "GET",
            "https://api.crossref.org/works/10.1/a",
            headers={"x-api-key": "synthetic-s2-key-not-a-secret"},
        )

        lit_search._enforce_credential_scope(request)

        assert "x-api-key" not in request.headers

    def test_the_hook_leaves_a_genuine_s2_request_alone(self):
        """The same hook must not break the authenticated call."""
        request = httpx.Request(
            "GET",
            f"https://{lit_search.S2_HOST}/graph/v1/paper/x",
            headers={"x-api-key": "synthetic-s2-key-not-a-secret"},
        )

        lit_search._enforce_credential_scope(request)

        assert request.headers["x-api-key"] == (
            "synthetic-s2-key-not-a-secret"
        )

    def test_the_client_installs_the_hook(self):
        """The scope guard must be wired into the shared client."""
        client = lit_search._get_client()
        try:
            hooks = client.event_hooks.get("request", [])
            assert lit_search._enforce_credential_scope in hooks
        finally:
            client.close()


class TestMissingAuthorShapes:
    """E19 and the fixture gaps lens B named."""

    def test_an_organisation_author_survives(self):
        """CrossRef's ``{"name": …}`` author must not vanish."""
        record = {
            "DOI": "10.9999/corporate",
            "title": ["A Corporate Report"],
            "author": [{"name": "The Synthetic Survey Consortium"}],
            "issued": {"date-parts": [[2031]]},
        }

        normalised = lit_search._normalise_crossref(record)

        assert normalised["authors"] == [
            "The Synthetic Survey Consortium"
        ]

    def test_a_family_only_author_survives(self):
        """A mononym or family-only record keeps its author."""
        record = {
            "DOI": "10.9999/mononym",
            "title": ["A Mononymous Work"],
            "author": [{"family": "Marinova"}],
        }

        assert lit_search._normalise_crossref(record)["authors"] == [
            "Marinova"
        ]

    def test_null_date_parts_yield_no_year(self):
        """``[[None]]`` must produce None, not a crash or a "None" year."""
        record = {
            "DOI": "10.9999/nodate",
            "title": ["Undated"],
            "issued": {"date-parts": [[None]]},
        }

        assert lit_search._normalise_crossref(record)["year"] is None

    def test_html_in_a_crossref_title_is_preserved_verbatim(self):
        """The normaliser is not a sanitiser; downstream strips markup."""
        record = {
            "DOI": "10.9999/markup",
            "title": ["Terraces <i>in situ</i>"],
        }

        assert lit_search._normalise_crossref(record)["title"] == (
            "Terraces <i>in situ</i>"
        )

    def test_a_null_openalex_authorship_is_tolerated(self):
        """``authorships[].author: null`` must not raise."""
        record = {
            "id": "https://openalex.org/W1",
            "display_name": "A Work",
            "authorships": [{"author": None}, {"author": {
                "display_name": "Iva Marinova"
            }}],
        }

        normalised = lit_search._normalise_openalex(record)

        assert "Iva Marinova" in normalised["authors"]

    def test_an_empty_openalex_record_normalises(self):
        """``_normalise_openalex({})`` must return the common schema."""
        normalised = lit_search._normalise_openalex({})
        assert normalised["source"] == "openalex"
        assert normalised["authors"] == []


class TestBibtexKeyCollisions:
    """E18 — two works by one author in one year must not collide."""

    def test_a_repeated_key_is_suffixed(self):
        """The second entry gains a letter suffix."""
        seen: set[str] = set()
        first = lit_search._dedupe_bibtex_key(
            "@article{Marinova2031,\n  title = {First},\n}", seen
        )
        second = lit_search._dedupe_bibtex_key(
            "@article{Marinova2031,\n  title = {Second},\n}", seen
        )

        assert "@article{Marinova2031," in first
        assert "@article{Marinova2031a," in second
        assert "{Second}" in second

    def test_distinct_keys_are_untouched(self):
        """A non-colliding entry is returned byte for byte."""
        seen: set[str] = set()
        entry = "@book{Dvorak2030,\n  title = {Only One},\n}"
        assert lit_search._dedupe_bibtex_key(entry, seen) == entry

    def test_cmd_bibtex_deduplicates_across_dois(self, reset_pacing):
        """Two DOIs whose entries share a key both survive the run."""
        client = RecordingClient(
            [
                FakeResponse(
                    200, text="@article{Marinova2031,\n  title = {A},\n}"
                ),
                FakeResponse(
                    200, text="@article{Marinova2031,\n  title = {B},\n}"
                ),
            ]
        )

        out = lit_search.cmd_bibtex(
            ["10.1/a", "10.1/b"], client  # type: ignore[arg-type]
        )

        assert "@article{Marinova2031," in out
        assert "@article{Marinova2031a," in out


# ============================================================================
# Release review L1 (9 November 2026): credentials never reach the logs or
# the output. A real httpx client on a mock transport, so httpx's own logging
# runs as it would against the API; a synthetic key; no network.
# ============================================================================

SYNTHETIC_KEY = "synthetic-openalex-key-" + "0123456789abcdef"


def _client_on(handler) -> httpx.Client:
    """An httpx client that answers from `handler`, with the helper's own hooks."""
    return httpx.Client(
        transport=httpx.MockTransport(handler),
        event_hooks={"request": [lit_search._enforce_credential_scope]},
    )


@pytest.fixture
def keyed(monkeypatch):
    """A configured OpenAlex key, and no pacing or retry delays."""
    monkeypatch.setattr(lit_search, "OPENALEX_API_KEY", SYNTHETIC_KEY)
    monkeypatch.setattr(lit_search, "_last_request", {})
    monkeypatch.setattr(lit_search.time, "sleep", lambda seconds: None)


def test_l1_a_keyed_request_logs_no_key(keyed, caplog, capfd):
    import logging

    sent: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:
        sent.append(str(request.url))
        return httpx.Response(200, json={"results": []})

    caplog.set_level(logging.DEBUG)
    with _client_on(answer) as client:
        data = lit_search._safe_get(
            client, f"https://{lit_search.OPENALEX_HOST}/works", "openalex",
            params={"search": "fair vocabularies"},
        )
    assert data == {"results": []}
    assert any(SYNTHETIC_KEY in url for url in sent), "the key should still be sent"
    assert SYNTHETIC_KEY not in caplog.text
    assert SYNTHETIC_KEY not in capfd.readouterr().err


def test_l1_a_failed_keyed_request_reports_no_key(keyed, caplog, capfd):
    import logging

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {request.url}", request=request)

    caplog.set_level(logging.DEBUG)
    with _client_on(refuse) as client:
        data = lit_search._safe_get(
            client, f"https://{lit_search.OPENALEX_HOST}/works", "openalex",
            params={"search": "fair vocabularies"},
        )
    assert data is None
    assert "request failed" in caplog.text
    assert "api_key=<redacted>" in caplog.text
    assert SYNTHETIC_KEY not in caplog.text
    assert SYNTHETIC_KEY not in capfd.readouterr().err


def test_l1_exception_text_in_the_output_is_redacted(keyed):
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach https://x.invalid/?api_key={SYNTHETIC_KEY}",
                                 request=request)

    with _client_on(refuse) as client:
        output = lit_search.cmd_bibtex(["10.1371/journal.pcbi.1009041"], client)
    assert "% FAILED" in output
    assert SYNTHETIC_KEY not in output


def test_l1_redact_covers_keys_and_api_key_parameters(monkeypatch):
    monkeypatch.setattr(lit_search, "S2_API_KEY", "synthetic-s2-key-42")
    text = f"x-api-key synthetic-s2-key-42 and ?q=a&api_key=other-value&b=c and {SYNTHETIC_KEY}"
    monkeypatch.setattr(lit_search, "OPENALEX_API_KEY", SYNTHETIC_KEY)
    clean = lit_search._redact(text)
    assert "synthetic-s2-key-42" not in clean
    assert "other-value" not in clean and "api_key=<redacted>&b=c" in clean
    assert SYNTHETIC_KEY not in clean


class TestCrossrefSubtitleAndReferenceCount:
    """CrossRef keeps a subtitle and a reference count in fields of their own.

    Found by a smoke test: `metadata` returned "Mobilization as Mediation"
    for a paper whose full title has a subtitle, while `bibtex` returned the
    full title, and it reported no CrossRef reference count at all.
    """

    def test_the_subtitle_is_joined_to_the_title(self):
        record = {"title": ["Mobilization as Mediation"],
                  "subtitle": ["Implementing a Tablet-Based Recording System"]}
        assert lit_search._normalise_crossref(record)["title"] == (
            "Mobilization as Mediation: Implementing a Tablet-Based Recording System"
        )

    def test_a_title_that_already_holds_the_subtitle_is_left_alone(self):
        record = {"title": ["A Study: of two parts"], "subtitle": ["Of Two Parts"]}
        assert lit_search._normalise_crossref(record)["title"] == "A Study: of two parts"

    def test_a_trailing_colon_on_the_title_is_not_doubled(self):
        record = {"title": ["A Study:"], "subtitle": ["Part two"]}
        assert lit_search._normalise_crossref(record)["title"] == "A Study: Part two"

    @pytest.mark.parametrize("subtitle", [None, [], [""], ["  "], [None]])
    def test_a_missing_or_empty_subtitle_changes_nothing(self, subtitle):
        record = {"title": ["Plain title"], "subtitle": subtitle}
        assert lit_search._normalise_crossref(record)["title"] == "Plain title"

    def test_no_title_stays_none_even_with_a_subtitle(self):
        assert lit_search._normalise_crossref({"subtitle": ["Orphan"]})["title"] is None

    def test_the_crossref_reference_count_is_reported(self):
        record = {"title": ["T"], "references-count": 67}
        assert lit_search._normalise_crossref(record)["reference_count"] == 67
        assert lit_search._normalise_crossref({"title": ["T"]})["reference_count"] is None
