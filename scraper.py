"""
ArchiScrapping — Job scraper module.
Uses python-jobspy to scrape architect jobs from multiple boards across Germany.
"""
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

import pandas as pd
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from jobspy import scrape_jobs

from config import settings

logger = logging.getLogger("archiscrapping.scraper")

# Job boards to scrape
JOB_BOARDS = ["indeed", "linkedin", "glassdoor", "google", "zip_recruiter"]


def _session_with_retries() -> requests.Session:
    """Session that retries transient network errors (connection resets, 502/503/504)."""
    session = requests.Session()
    retry = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.mount("http://", HTTPAdapter(max_retries=retry))
    return session

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


def scrape_baunetz(max_pages: int = 3) -> List[Dict[str, Any]]:
    """
    Scrape premier architecture jobs directly from BauNetz (baunetz.de/stellenmarkt).
    BauNetz is Germany's top specialized architecture job portal.
    """
    logger.info(f"Scraping BauNetz (pages 1..{max_pages})")
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    jobs: List[Dict[str, Any]] = []
    session = _session_with_retries()

    for page in range(1, max_pages + 1):
        url = f"https://www.baunetz.de/stellenmarkt/suche?page={page}"
        try:
            r = session.get(url, headers=headers, timeout=10)
            if r.status_code != 200:
                logger.warning(f"BauNetz page {page} returned status {r.status_code}")
                continue

            soup = BeautifulSoup(r.text, "html.parser")
            links = soup.find_all("a", href=lambda h: h and "/stellenmarkt/job/" in h)

            for a in links:
                title_elem = a.find("span", class_="title")
                company_elem = a.find(class_="company-title")
                loc_elem = a.find(class_="location")
                intro_elem = a.find(class_="intro")

                title = title_elem.get_text(strip=True) if title_elem else None
                company = company_elem.get_text(strip=True) if company_elem else None
                city = loc_elem.get_text(strip=True) if loc_elem else None
                desc = intro_elem.get_text(strip=True) if intro_elem else None

                href = a.get("href", "")
                full_url = f"https://www.baunetz.de{href}" if href.startswith("/") else href

                if title:
                    jobs.append({
                        "site_name": "baunetz",
                        "title": title,
                        "company": company,
                        "city": city,
                        "state": None,
                        "job_type": "fulltime",
                        "salary_min": None,
                        "salary_max": None,
                        "salary_interval": None,
                        "salary_currency": "EUR",
                        "description": desc,
                        "job_url": full_url,
                        "date_posted": None,
                        "search_term_used": "baunetz",
                    })

        except Exception as e:
            logger.warning(f"Error scraping BauNetz page {page}: {e}")
            continue

    logger.info(f"BauNetz scraping complete: {len(jobs)} jobs extracted")
    return jobs


def scrape_architect_jobs(
    search_terms: Optional[List[str]] = None,
    locations: Optional[List[str]] = None,
    results_per_site: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Scrape architect jobs from all configured job boards across Germany.

    Returns:
        List of normalized job dicts
    """
    if search_terms is None:
        search_terms = settings.search_terms_list
    if locations is None:
        locations = ["Germany"]
    if results_per_site is None:
        results_per_site = settings.results_per_site

    all_jobs: List[Dict[str, Any]] = []

    # 1. Scrape BauNetz (Top architecture portal in Germany — 100% reliable)
    try:
        baunetz_jobs = scrape_baunetz(max_pages=3)
        all_jobs.extend(baunetz_jobs)
    except Exception as e:
        logger.warning(f"BauNetz scraping error: {e}")

    # StepStone dropped: Akamai's JS/TLS challenge blocks even residential IPs
    # using plain HTTP requests, not just Railway's datacenter IP.

    # 2. Scrape JobSpy boards (Indeed, LinkedIn, Google, Glassdoor, ZipRecruiter)
    for search_term in search_terms:
        for location in locations:
            logger.info(f"Scraping: '{search_term}' in '{location}'")
            google_term = f"{search_term} jobs in {location} since last week"

            # Scrape board by board so that a 429/403 on one board (e.g. Google Jobs on cloud IPs)
            # never causes the entire search term or other boards (Indeed, LinkedIn) to be discarded.
            for board in JOB_BOARDS:
                try:
                    df = scrape_jobs(
                        site_name=[board],
                        search_term=search_term,
                        google_search_term=google_term if board == "google" else None,
                        location=location,
                        results_wanted=results_per_site,
                        hours_old=168,  # last 7 days
                        country_indeed="Germany",
                        linkedin_fetch_description=True,
                        proxies=proxies,
                    )

                    if df is not None and not df.empty:
                        board_jobs_count = 0
                        for _, row in df.iterrows():
                            job = _normalize_job(row, search_term)
                            if job["title"]:
                                all_jobs.append(job)
                                board_jobs_count += 1

                        logger.info(
                            f"  [{board}] Found {board_jobs_count} results for '{search_term}'"
                        )
                except Exception as e:
                    logger.warning(
                        f"  [{board}] Unavailable for '{search_term}': {e}"
                    )
                    continue

    logger.info(f"Total raw jobs scraped across all sources: {len(all_jobs)}")
    return all_jobs
