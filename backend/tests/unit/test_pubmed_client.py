"""
Tests for backend.integrations.external.pubmed_client.PubMedClient.

Coverage:
- _make_request: success, 429 rate-limit, HTTPStatusError, generic Exception
- search_articles: full flow, empty id_list, missing uid in summary
- fetch_abstracts: empty input, HTTP error, delegates to _parse_abstracts_xml
- _parse_abstracts_xml: valid XML, labelled sections, missing PMID, missing abstract,
  malformed XML (ParseError)
- search_and_fetch: clinical filter hit, fallback (no clinical results), total empty
"""

import textwrap
from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backend.integrations.external.pubmed_client import PubMedClient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client(monkeypatch) -> Generator[PubMedClient, None, None]:
    """PubMedClient with mocked settings — no real network, no real secrets."""
    mock_settings = MagicMock()
    mock_settings.PUBMED_API_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    mock_settings.PUBMED_WEB_URL = "https://pubmed.ncbi.nlm.nih.gov"
    mock_settings.PUBMED_API_KEY = None  # no API key by default
    mock_settings.CLINICAL_PUBLICATION_TYPES = (
        "Randomized Controlled Trial[pt] OR Meta-Analysis[pt]"
    )

    with patch("backend.integrations.external.pubmed_client.settings", mock_settings):
        c = PubMedClient()
        # Replace the real httpx client so nothing leaves the process
        c.client = AsyncMock()
        yield c


@pytest.fixture
def client_with_key(monkeypatch) -> Generator[PubMedClient, None, None]:
    """PubMedClient variant that has an API key configured."""
    mock_key = MagicMock()
    mock_key.get_secret_value.return_value = "test_api_key_123"

    mock_settings = MagicMock()
    mock_settings.PUBMED_API_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    mock_settings.PUBMED_WEB_URL = "https://pubmed.ncbi.nlm.nih.gov"
    mock_settings.PUBMED_API_KEY = mock_key
    mock_settings.CLINICAL_PUBLICATION_TYPES = "Randomized Controlled Trial[pt]"

    with patch("backend.integrations.external.pubmed_client.settings", mock_settings):
        c = PubMedClient()
        c.client = AsyncMock()
        yield c


def _mock_response(
    status_code: int = 200, json_data: dict[str, Any] | None = None, text: str = ""
) -> MagicMock:
    """Build a mock httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        error = httpx.HTTPStatusError(
            message=f"HTTP {status_code}",
            request=MagicMock(),
            response=MagicMock(status_code=status_code),
        )
        resp.raise_for_status.side_effect = error
    return resp


SIMPLE_XML = textwrap.dedent("""\
    <PubmedArticleSet>
      <PubmedArticle>
        <MedlineCitation>
          <PMID>12345678</PMID>
          <Article>
            <ArticleTitle>Serotonin and mood regulation</ArticleTitle>
            <Abstract>
              <AbstractText>This study investigates serotonin.</AbstractText>
            </Abstract>
          </Article>
        </MedlineCitation>
      </PubmedArticle>
    </PubmedArticleSet>
""")

LABELLED_XML = textwrap.dedent("""\
    <PubmedArticleSet>
      <PubmedArticle>
        <MedlineCitation>
          <PMID>99999999</PMID>
          <Article>
            <ArticleTitle>RCT on dopamine</ArticleTitle>
            <Abstract>
              <AbstractText Label="BACKGROUND">Background text.</AbstractText>
              <AbstractText Label="CONCLUSION">Conclusion text.</AbstractText>
            </Abstract>
          </Article>
        </MedlineCitation>
      </PubmedArticle>
    </PubmedArticleSet>
""")


# ---------------------------------------------------------------------------
# _make_request
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMakeRequest:
    @pytest.mark.asyncio
    async def test_success_returns_json(self, client: PubMedClient) -> None:
        """200 response: parsed JSON is returned as-is."""
        payload = {"esearchresult": {"idlist": ["111"]}}
        client.client.get = AsyncMock(return_value=_mock_response(200, payload))

        result = await client._make_request("esearch.fcgi", {"term": "serotonin"})

        assert result == payload

    @pytest.mark.asyncio
    async def test_rate_limit_429_returns_empty_dict(
        self, client: PubMedClient
    ) -> None:
        """HTTP 429 must return {} without raising."""
        client.client.get = AsyncMock(return_value=_mock_response(429))

        result = await client._make_request("esearch.fcgi", {})

        assert result == {}

    @pytest.mark.asyncio
    async def test_http_status_error_returns_empty_dict(
        self, client: PubMedClient
    ) -> None:
        """Non-429 HTTP errors are caught and return {}."""
        client.client.get = AsyncMock(return_value=_mock_response(503))

        result = await client._make_request("esearch.fcgi", {})

        assert result == {}

    @pytest.mark.asyncio
    async def test_generic_exception_returns_empty_dict(
        self, client: PubMedClient
    ) -> None:
        """Network-level exceptions (timeout, DNS) return {} without propagating."""
        client.client.get = AsyncMock(side_effect=httpx.ConnectError("timeout"))

        result = await client._make_request("esearch.fcgi", {})

        assert result == {}

    @pytest.mark.asyncio
    async def test_api_key_appended_when_configured(
        self, client_with_key: PubMedClient
    ) -> None:
        """API key is injected into request params when settings provide one."""
        payload = {"esearchresult": {"idlist": []}}
        client_with_key.client.get = AsyncMock(
            return_value=_mock_response(200, payload)
        )

        await client_with_key._make_request("esearch.fcgi", {"term": "test"})

        call_kwargs = client_with_key.client.get.call_args
        params_sent = (
            call_kwargs.kwargs.get("params") or call_kwargs.args[1]
            if len(call_kwargs.args) > 1
            else call_kwargs.kwargs["params"]
        )
        assert params_sent.get("api_key") == "test_api_key_123"

    @pytest.mark.asyncio
    async def test_no_api_key_when_not_configured(self, client: PubMedClient) -> None:
        """api_key param is NOT added when PUBMED_API_KEY is None."""
        payload = {"esearchresult": {"idlist": []}}
        client.client.get = AsyncMock(return_value=_mock_response(200, payload))

        await client._make_request("esearch.fcgi", {"term": "test"})

        call_kwargs = client.client.get.call_args
        params_sent = call_kwargs.kwargs.get("params", {})
        assert "api_key" not in params_sent


# ---------------------------------------------------------------------------
# search_articles
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSearchArticles:
    @pytest.mark.asyncio
    async def test_full_flow_returns_structured_results(
        self, client: PubMedClient
    ) -> None:
        """search_articles assembles results from search + summary responses."""
        search_resp = {"esearchresult": {"idlist": ["111", "222"]}}
        summary_resp = {
            "result": {
                "111": {
                    "title": "Article One",
                    "authors": [{"name": "Doe J"}],
                    "source": "JAMA",
                    "pubdate": "2024",
                },
                "222": {
                    "title": "Article Two",
                    "authors": [],
                    "source": "Lancet",
                    "pubdate": "2023",
                },
            }
        }

        client._make_request = AsyncMock(side_effect=[search_resp, summary_resp])

        results = await client.search_articles("serotonin", max_results=2)

        assert len(results) == 2
        assert results[0]["uid"] == "111"
        assert results[0]["title"] == "Article One"
        assert results[0]["authors"] == ["Doe J"]
        assert "pubmed.ncbi.nlm.nih.gov/111/" in results[0]["url"]

    @pytest.mark.asyncio
    async def test_empty_id_list_returns_empty(self, client: PubMedClient) -> None:
        """No search hits → no second request, returns []."""
        client._make_request = AsyncMock(return_value={"esearchresult": {"idlist": []}})

        results = await client.search_articles("nonexistent query")

        assert results == []
        client._make_request.assert_called_once()

    @pytest.mark.asyncio
    async def test_uid_missing_from_summary_skipped(self, client: PubMedClient) -> None:
        """UIDs absent from summary['result'] are silently skipped."""
        search_resp = {"esearchresult": {"idlist": ["333"]}}
        summary_resp = {"result": {}}  # uid '333' absent

        client._make_request = AsyncMock(side_effect=[search_resp, summary_resp])

        results = await client.search_articles("test")

        assert results == []

    @pytest.mark.asyncio
    async def test_make_request_failure_propagates_empty(
        self, client: PubMedClient
    ) -> None:
        """If _make_request returns {} (error), function returns []."""
        client._make_request = AsyncMock(return_value={})

        results = await client.search_articles("test")

        assert results == []


# ---------------------------------------------------------------------------
# fetch_abstracts
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFetchAbstracts:
    @pytest.mark.asyncio
    async def test_empty_uid_list_returns_empty(self, client: PubMedClient) -> None:
        """No UIDs → early return [], no HTTP call made."""
        mock_get = AsyncMock()
        client.client.get = mock_get

        result = await client.fetch_abstracts([])

        assert result == []
        mock_get.assert_not_called()

    @pytest.mark.asyncio
    async def test_successful_fetch_calls_parse(self, client: PubMedClient) -> None:
        """Valid XML response delegates to _parse_abstracts_xml."""
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.text = SIMPLE_XML
        client.client.get = AsyncMock(return_value=resp)

        results = await client.fetch_abstracts(["12345678"])

        assert len(results) == 1
        assert results[0]["uid"] == "12345678"
        assert "serotonin" in results[0]["abstract"].lower()

    @pytest.mark.asyncio
    async def test_http_error_returns_empty(self, client: PubMedClient) -> None:
        """HTTP error during efetch returns [] without propagating."""
        resp = _mock_response(500)
        client.client.get = AsyncMock(return_value=resp)

        result = await client.fetch_abstracts(["12345678"])

        assert result == []

    @pytest.mark.asyncio
    async def test_api_key_injected_in_efetch(
        self, client_with_key: PubMedClient
    ) -> None:
        """API key is added to efetch params when configured."""
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.text = SIMPLE_XML
        client_with_key.client.get = AsyncMock(return_value=resp)

        await client_with_key.fetch_abstracts(["12345678"])

        call_kwargs = client_with_key.client.get.call_args
        params_sent = call_kwargs.kwargs.get("params", {})
        assert params_sent.get("api_key") == "test_api_key_123"


# ---------------------------------------------------------------------------
# _parse_abstracts_xml
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestParseAbstractsXml:
    def test_plain_abstract_parsed_correctly(self, client: PubMedClient) -> None:
        """Single unlabelled AbstractText is extracted as-is."""
        results = client._parse_abstracts_xml(SIMPLE_XML, ["12345678"])

        assert len(results) == 1
        assert results[0]["uid"] == "12345678"
        assert results[0]["title"] == "Serotonin and mood regulation"
        assert results[0]["abstract"] == "This study investigates serotonin."

    def test_labelled_sections_joined_with_label(self, client: PubMedClient) -> None:
        """Labelled sections get 'LABEL: text' format joined by space."""
        results = client._parse_abstracts_xml(LABELLED_XML, ["99999999"])

        assert len(results) == 1
        abstract = results[0]["abstract"]
        assert "BACKGROUND: Background text." in abstract
        assert "CONCLUSION: Conclusion text." in abstract

    def test_article_without_abstract_excluded(self, client: PubMedClient) -> None:
        """Articles where abstract is empty string are not included in results."""
        xml = textwrap.dedent("""\
            <PubmedArticleSet>
              <PubmedArticle>
                <MedlineCitation>
                  <PMID>55555555</PMID>
                  <Article>
                    <ArticleTitle>No abstract article</ArticleTitle>
                  </Article>
                </MedlineCitation>
              </PubmedArticle>
            </PubmedArticleSet>
        """)
        results = client._parse_abstracts_xml(xml, ["55555555"])

        assert results == []

    def test_article_without_pmid_excluded(self, client: PubMedClient) -> None:
        """Articles missing PMID element are skipped."""
        xml = textwrap.dedent("""\
            <PubmedArticleSet>
              <PubmedArticle>
                <MedlineCitation>
                  <Article>
                    <ArticleTitle>No PMID</ArticleTitle>
                    <Abstract>
                      <AbstractText>Some text.</AbstractText>
                    </Abstract>
                  </Article>
                </MedlineCitation>
              </PubmedArticle>
            </PubmedArticleSet>
        """)
        results = client._parse_abstracts_xml(xml, [])

        assert results == []

    def test_malformed_xml_returns_empty(self, client: PubMedClient) -> None:
        """ParseError on malformed XML returns [] without raising."""
        results = client._parse_abstracts_xml("<broken><unclosed>", [])

        assert results == []

    def test_url_contains_pmid(self, client: PubMedClient) -> None:
        """Constructed URL must embed the PMID for the article."""
        results = client._parse_abstracts_xml(SIMPLE_XML, ["12345678"])

        assert "12345678" in results[0]["url"]

    def test_empty_xml_string_returns_empty(self, client: PubMedClient) -> None:
        """Empty string input yields ParseError → returns []."""
        results = client._parse_abstracts_xml("", [])

        assert results == []


# ---------------------------------------------------------------------------
# search_and_fetch
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSearchAndFetch:
    @pytest.mark.asyncio
    async def test_clinical_filter_hit_returns_abstracts(
        self, client: PubMedClient
    ) -> None:
        """When clinical filter yields results, fetch_abstracts is called once."""
        uid_list = ["12345678"]
        client._make_request = AsyncMock(
            return_value={"esearchresult": {"idlist": uid_list}}
        )

        mock_article = MagicMock()
        client.fetch_abstracts = AsyncMock(return_value=[mock_article])

        results = await client.search_and_fetch("serotonin depression")

        client._make_request.assert_called_once()
        client.fetch_abstracts.assert_called_once_with(uid_list)
        assert results == [mock_article]

    @pytest.mark.asyncio
    async def test_no_clinical_results_retries_without_filter(
        self, client: PubMedClient
    ) -> None:
        """First call (clinical filter) returns empty → retry without filter."""
        uid_list = ["99999999"]
        client._make_request = AsyncMock(
            side_effect=[
                {"esearchresult": {"idlist": []}},  # clinical filter: empty
                {"esearchresult": {"idlist": uid_list}},  # fallback: has results
            ]
        )
        client.fetch_abstracts = AsyncMock(return_value=[MagicMock()])

        results = await client.search_and_fetch("serotonin")

        assert client._make_request.call_count == 2
        client.fetch_abstracts.assert_called_once_with(uid_list)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_both_searches_empty_returns_empty(
        self, client: PubMedClient
    ) -> None:
        """Both clinical and fallback searches return no results → return []."""
        client._make_request = AsyncMock(return_value={"esearchresult": {"idlist": []}})
        client.fetch_abstracts = AsyncMock()

        results = await client.search_and_fetch("completely unknown term xyz")

        client.fetch_abstracts.assert_not_called()
        assert results == []

    @pytest.mark.asyncio
    async def test_close_calls_aclose(self, client: PubMedClient) -> None:
        """close() delegates to underlying httpx client's aclose()."""
        client.client.aclose = AsyncMock()

        await client.close()

        client.client.aclose.assert_called_once()
