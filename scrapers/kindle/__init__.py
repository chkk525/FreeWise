"""Kindle Notebook (read.amazon.com/kp/notebook) scraper.

Public surface:

- ``models``: frozen dataclasses for the JSON contract documented in
  ``docs/KINDLE_JSON_SCHEMA.md``.
- ``scraper``: async Playwright implementation of ``run_login`` /
  ``run_scrape``.
- ``cli``: ``python -m scrapers.kindle <login|scrape>`` entrypoint.

The scraper output MUST conform exactly to the JSON schema; see
``scrapers/kindle/fixtures/kindle_notebook_sample.json`` for an example.
"""

from scrapers.kindle.models import (
    KindleBook,
    KindleHighlight,
    SCHEMA_VERSION,
    SOURCE_NAME,
    ScrapeOutput,
)

__all__ = [
    "KindleBook",
    "KindleHighlight",
    "SCHEMA_VERSION",
    "SOURCE_NAME",
    "ScrapeOutput",
]
