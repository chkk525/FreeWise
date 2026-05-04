"""Allow ``python -m scrapers.kindle <login|scrape>``."""

from scrapers.kindle.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
