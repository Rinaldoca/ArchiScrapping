"""
ArchiScrapping — Job scraper module.
Uses python-jobspy to scrape architect jobs from multiple boards across Germany.
"""
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

import pandas as pd
from jobspy import scrape_jobs

from config import settings

logger = logging.getLogger("archiscrapping.scraper")

# Job boards to scrape
JOB_BOARDS = ["indeed", "linkedin", "glassdoor", "google", "zip_recruiter"]

# German cities to search across for better coverage
GERMAN_LOCATIONS = [
    "Germany",
    "Berlin, Germany",
    "Munich, Germany",
    "Hamburg, Germany",
    "Frankfurt, Germany",
    "Cologne, Germany",
    "Stuttgart, Germany",
    "Düsseldorf, Germany",
    "Leipzig, Germany",
    "Dresden, Germany",
    "Hannover, Germany",
    "Nuremberg, Germany",
]


def _normalize_job(row: pd.Series, search_term: str) -> Dict[str, Any]:
    """Convert a pandas row from jobspy into a normalized dict."""

    def safe_str(val):
        if pd.isna(val) or val is None:
            return None
        return str(val).strip()

    def safe_float(val):
        if pd.isna(val) or val is None:
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    def safe_date(val):
        if pd.isna(val) or val is None:
            return None
        if isinstance(val, datetime):
            return val.replace(tzinfo=timezone.utc) if val.tzinfo is None else val
        try:
            return datetime.fromisoformat(str(val)).replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            return None

    # Parse location field (e.g. "Stuttgart, BW, DE" or "Berlin, BE, DE")
    location_raw = safe_str(row.get("location"))
    city = None
    state = None
    if location_raw:
        parts = [p.strip() for p in location_raw.split(",")]
        if len(parts) >= 1:
            city = parts[0]
        if len(parts) >= 2:
            state = parts[1]

    return {
        "site_name": safe_str(row.get("site")),
        "title": safe_str(row.get("title")),
        "company": safe_str(row.get("company")),
        "city": city,
        "state": state,
        "job_type": safe_str(row.get("job_type")),
        "salary_min": safe_float(row.get("min_amount")),
        "salary_max": safe_float(row.get("max_amount")),
        "salary_interval": safe_str(row.get("interval")),
        "salary_currency": safe_str(row.get("currency")) or "EUR",
        "description": safe_str(row.get("description")),
        "job_url": safe_str(row.get("job_url")),
        "date_posted": safe_date(row.get("date_posted")),
        "search_term_used": search_term,
    }


def scrape_architect_jobs(
    search_terms: Optional[List[str]] = None,
    locations: Optional[List[str]] = None,
    results_per_site: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Scrape architect jobs from all configured job boards.

    Args:
        search_terms: List of search terms (defaults to config)
        locations: List of locations to search (defaults to Germany-wide + major cities)
        results_per_site: Max results per site per search (defaults to config)

    Returns:
        List of normalized job dicts
    """
    if search_terms is None:
        search_terms = settings.search_terms_list
    if locations is None:
        # Use just "Germany" for broader coverage, add cities for depth
        locations = ["Germany"]
    if results_per_site is None:
        results_per_site = settings.results_per_site

    all_jobs: List[Dict[str, Any]] = []
    proxies = settings.proxies

    for search_term in search_terms:
        for location in locations:
            logger.info(f"Scraping: '{search_term}' in '{location}'")

            try:
                google_term = f"{search_term} jobs in {location} since last week"

                df = scrape_jobs(
                    site_name=JOB_BOARDS,
                    search_term=search_term,
                    google_search_term=google_term,
                    location=location,
                    results_wanted=results_per_site,
                    hours_old=168,  # last 7 days
                    country_indeed="Germany",
                    linkedin_fetch_description=True,
                    proxies=proxies,
                )

                if df is not None and not df.empty:
                    for _, row in df.iterrows():
                        job = _normalize_job(row, search_term)
                        if job["title"]:  # skip entries without a title
                            all_jobs.append(job)

                    logger.info(
                        f"  Found {len(df)} results for '{search_term}' in '{location}'"
                    )
                else:
                    logger.info(
                        f"  No results for '{search_term}' in '{location}'"
                    )

            except Exception as e:
                logger.warning(
                    f"  Error scraping '{search_term}' in '{location}': {e}"
                )
                continue

    logger.info(f"Total raw jobs scraped: {len(all_jobs)}")
    return all_jobs
