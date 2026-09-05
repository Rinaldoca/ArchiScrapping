"""
Run StepStone scraping from a local/residential IP and push results to the
Railway-hosted app. Railway's datacenter IP gets blocked by Akamai; a home
connection generally isn't.

Usage:
    RAILWAY_URL=https://archiscrapping-production.up.railway.app \
    INGEST_API_KEY=... \
    python scrape_stepstone_local.py

Schedule with cron/launchd to run periodically.
"""
import os
import sys
import json
import logging

import requests

from config import settings
from scraper import scrape_stepstone, GERMAN_LOCATIONS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger("stepstone_local")

RAILWAY_URL = os.environ.get("RAILWAY_URL", "").rstrip("/")
API_KEY = os.environ.get("INGEST_API_KEY", "")


def main():
    if not RAILWAY_URL or not API_KEY:
        sys.exit("Set RAILWAY_URL and INGEST_API_KEY environment variables.")

    all_jobs = []
    for term in settings.search_terms_list[:3]:
        for location in ["Germany"] + GERMAN_LOCATIONS[:3]:
            jobs = scrape_stepstone(term, location, max_results=settings.results_per_site)
            all_jobs.extend(jobs)

    if not all_jobs:
        logger.info("No StepStone jobs found (possibly still blocked).")
        return

    for job in all_jobs:
        if job.get("date_posted") is not None:
            job["date_posted"] = job["date_posted"].isoformat()

    resp = requests.post(
        f"{RAILWAY_URL}/api/jobs/ingest",
        headers={"X-API-Key": API_KEY},
        json={"jobs": all_jobs},
        timeout=30,
    )
    resp.raise_for_status()
    logger.info(f"Ingest result: {json.dumps(resp.json())}")


if __name__ == "__main__":
    main()
