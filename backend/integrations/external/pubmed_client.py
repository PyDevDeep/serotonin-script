from typing import Any, Dict, List

import httpx
import structlog

from backend.config.settings import settings
from backend.models.schemas import PubMedArticle

logger = structlog.get_logger()


class PubMedClient:
    """Async client for the NCBI PubMed E-utilities API."""

    def __init__(self) -> None:
        self.client = httpx.AsyncClient(timeout=10.0)
        self.settings = settings
        self.base_url = settings.PUBMED_API_URL
        # Read the API key if configured
        self.api_key = (
            settings.PUBMED_API_KEY.get_secret_value()
            if settings.PUBMED_API_KEY
            else None
        )

    async def _make_request(
        self, endpoint: str, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Make an authenticated GET request to a PubMed endpoint with error handling."""
        url = f"{self.base_url}/{endpoint}"

        # Append API key to params if configured
        if self.api_key:
            params["api_key"] = self.api_key

        try:
            response = await self.client.get(url, params=params)

            if response.status_code == 429:
                logger.error("pubmed_rate_limit_exceeded", status=429)
                return {}

            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(
                "pubmed_api_error", status=e.response.status_code, detail=str(e)
            )
            return {}
        except Exception as e:
            logger.error(
                "pubmed_unexpected_error",
                error=repr(e),
                error_type=type(e).__name__,
            )
            return {}

    async def search_articles(
        self, query: str, max_results: int = 3
    ) -> List[Dict[str, Any]]:
        """Search PubMed for articles matching the query and return summary metadata."""
        logger.info("pubmed_search_started", query=query)

        # 1. Search for article IDs
        search_params = {
            "db": "pubmed",
            "term": query,
            "retmode": "json",
            "retmax": max_results,
        }
        search_data = await self._make_request("esearch.fcgi", search_params)

        id_list = search_data.get("esearchresult", {}).get("idlist", [])
        if not id_list:
            return []

        # 2. Fetch article details
        summary_params = {"db": "pubmed", "id": ",".join(id_list), "retmode": "json"}
        summary_data = await self._make_request("esummary.fcgi", summary_params)

        results: List[Dict[str, Any]] = []
        for uid in id_list:
            item = summary_data.get("result", {}).get(uid, {})
            if item:
                results.append(
                    {
                        "uid": uid,
                        "title": item.get("title", ""),
                        "authors": [
                            auth.get("name") for auth in item.get("authors", [])
                        ],
                        "source": item.get("source", ""),
                        "pubdate": item.get("pubdate", ""),
                        "url": f"{settings.PUBMED_WEB_URL}/{uid}/",
                    }
                )

        return results

    async def fetch_abstracts(self, uid_list: list[str]) -> list[PubMedArticle]:
        """Fetch full abstracts for a list of PubMed IDs via efetch."""
        if not uid_list:
            return []

        params = {
            "db": "pubmed",
            "id": ",".join(uid_list),
            "retmode": "xml",
            "rettype": "abstract",
        }
        try:
            url = f"{self.base_url}/efetch.fcgi"
            if self.api_key:
                params["api_key"] = self.api_key

            response = await self.client.get(url, params=params)
            response.raise_for_status()

            return self._parse_abstracts_xml(response.text, uid_list)
        except Exception as e:
            logger.error("pubmed_fetch_abstracts_error", error=str(e))
            return []

    def _parse_abstracts_xml(
        self, xml_text: str, uid_list: list[str]
    ) -> list[PubMedArticle]:
        """Parse the efetch XML response and extract AbstractText for each PMID."""
        import xml.etree.ElementTree as ET

        results: list[PubMedArticle] = []
        try:
            root = ET.fromstring(xml_text)
            for article in root.findall(".//PubmedArticle"):
                pmid_el = article.find(".//PMID")
                pmid = pmid_el.text if pmid_el is not None else None

                abstract_parts = article.findall(".//AbstractText")
                sections: list[str] = []
                for el in abstract_parts:
                    text = "".join(el.itertext()).strip()
                    if text:
                        label = el.get("Label")
                        sections.append(f"{label}: {text}" if label else text)
                abstract = " ".join(sections).strip()

                title_el = article.find(".//ArticleTitle")
                title = (title_el.text if title_el is not None else "") or ""

                if pmid and abstract:
                    results.append(
                        PubMedArticle(
                            uid=str(pmid),
                            title=str(title),
                            abstract=str(abstract),
                            url=f"{settings.PUBMED_WEB_URL}/{pmid}/",
                        )
                    )
        except ET.ParseError as e:
            logger.error("pubmed_xml_parse_error", error=str(e))

        return results

    async def search_and_fetch(
        self, query: str, max_results: int = 3
    ) -> list[PubMedArticle]:
        """Search PubMed and fetch abstracts in one call, filtering by clinical publication types."""
        logger.info("pubmed_search_and_fetch", query=query)

        search_params = {
            "db": "pubmed",
            "term": f"({query}) AND ({self.settings.CLINICAL_PUBLICATION_TYPES})",
            "retmode": "json",
            "retmax": max_results,
        }
        search_data = await self._make_request("esearch.fcgi", search_params)
        uid_list = search_data.get("esearchresult", {}).get("idlist", [])

        if not uid_list:
            logger.warning(
                "pubmed_no_clinical_results_retry_without_filter", query=query
            )
            # Fallback: retry without the clinical filter
            search_params["term"] = query
            search_data = await self._make_request("esearch.fcgi", search_params)
            uid_list = search_data.get("esearchresult", {}).get("idlist", [])

        if not uid_list:
            logger.warning("pubmed_no_results", query=query)
            return []

        return await self.fetch_abstracts(uid_list)

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self.client.aclose()
