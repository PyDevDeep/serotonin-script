import asyncio

import structlog
from llama_index.readers.web import (  # type: ignore[import-untyped]  # noqa: E402
    BeautifulSoupWebReader,
)

logger = structlog.get_logger()

MAX_CHARS = 12000


class WebScraper:
    def __init__(self) -> None:
        self.reader = BeautifulSoupWebReader()

    async def scrape(self, url: str) -> str | None:
        """Повертає текст сторінки або None при помилці/порожньому результаті."""
        logger.info("web_scraper_started", url=url)
        try:
            documents = await asyncio.to_thread(self.reader.load_data, urls=[url])
            if not documents:
                logger.warning("web_scraper_empty", url=url)
                return None

            content = documents[0].get_content()[:MAX_CHARS].strip()
            logger.info("web_scraper_success", url=url, chars=len(content))
            return f"--- Джерело: WEB ({url}) ---\n{content}"
        except Exception as e:
            logger.error("web_scraper_failed", url=url, error=str(e))
            return None
