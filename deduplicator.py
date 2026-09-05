"""
ArchiScrapping — Deduplication module.
Matches new scraped jobs against existing DB records using fuzzy matching,
merges duplicates by adding source entries, and inserts new jobs.
"""
import logging
import re
from datetime import datetime, timezone
from typing import List, Dict, Any, Tuple, Optional

from sqlalchemy.orm import Session
from thefuzz import fuzz

from database import Job, JobSource

logger = logging.getLogger("archiscrapping.deduplicator")

# Fuzzy match threshold (0–100). Higher = stricter matching.
TITLE_THRESHOLD = 82
COMPANY_THRESHOLD = 80

# ─── IT Architecture Exclusion Filter ──────────────────────────────────────────
# Excludes software, cloud, data, security, and IT architecture roles.
# Ensures only traditional building/interior/landscape/urban architecture is kept.

IT_EXCLUSION_PATTERNS = [
    r'\bsoftware\b',
    r'\bcloud\b',
    r'\bsolution(s)?\b',
    r'\benterprise\b',
    r'\bdata\b',
    r'\bsecurity\b',
    r'\bcyber\b',
    r'\bdevops\b',
    r'\bdevsecops\b',
    r'\baws\b',
    r'\bazure\b',
    r'\bsap\b',
    r'\bsalesforce\b',
    r'\bnetwork\b',
    r'\binfrastructure\b',
    r'\binfrastruktur\b',
    r'\bsystem(s)?\s+architect\b',
    r'\bsystem-architekt\b',
    r'\bplatform\b',
    r'\bplattform\b',
    r'\bfrontend\b',
    r'\bbackend\b',
    r'\bfull-?stack\b',
    r'\bapi\b',
    r'\bkubernetes\b',
    r'\bmachine\s+learning\b',
    r'\bai\s+architect\b',
    r'\bai\s*[/]?\s*ml\b',
    r'\biot\b',
    r'\btest\s+architect\b',
    r'\bintegration\s+architect\b',
    r'\bit[-\s]architekt(in)?\b',
    r'\bit[-\s]architect\b',
    r'\bit[-\s]projektleiter\b',
    r'\bit[-\s]infrastruktur\b',
    r'\bit[-\s]system\b',
    r'\bit[-\s]consultant\b',
    r'\bit[-\s]support\b',
    r'\bdomain\s+architect\b',
    r'\bbusiness\s+architect(ure)?\b',
    r'\bcrm\b',
    r'\berp\b',
    r'\bjava\b',
    r'\bpython\b',
    r'\b\.net\b',
    r'\bc\+\+\b',
    r'\bc#\b',
    r'\bdatabase\b',
    r'\bdatenbank\b',
    r'\bdeveloper\b',
    r'\bentwickler\b',
    r'\bprogrammer\b',
    r'\bprogramming\b',
    r'\bagentops\b',
    r'\btech\s+architect\b',
    r'\bdev\b',
    r'\blaravel\b',
    r'\bangular\b',
    r'\breact\b',
    r'\bvue\b',
    r'\bnode(\.js)?\b',
    r'\btypescript\b',
    r'\bjavascript\b',
    r'\bmysql\b',
]

_IT_REGEX = re.compile('|'.join(IT_EXCLUSION_PATTERNS), re.IGNORECASE)


def is_traditional_architect_job(title: Optional[str]) -> bool:
    """Return True if job is for traditional architecture, False if IT/software."""
    if not title:
        return False
    return not bool(_IT_REGEX.search(title))


def _normalize_text(text: str) -> str:
    """Lowercase and strip extra whitespace for comparison."""
    if not text:
        return ""
    return " ".join(text.lower().split())


def _to_naive(dt):
    """Normalize datetime to naive UTC for safe cross-database comparison."""
    if dt is None:
        return None
    if hasattr(dt, "tzinfo") and dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _find_matching_job(
    new_job: Dict[str, Any],
    existing_jobs: List[Job],
) -> Job | None:
    """
    Find an existing job that matches the new one.
    Uses fuzzy matching on title + company + city.
    """
    new_title = _normalize_text(new_job.get("title", ""))
    new_company = _normalize_text(new_job.get("company", ""))
    new_city = _normalize_text(new_job.get("city", ""))

    if not new_title:
        return None

    for existing in existing_jobs:
        ex_title = _normalize_text(existing.title or "")
        ex_company = _normalize_text(existing.company or "")
        ex_city = _normalize_text(existing.city or "")

        # Title must match well
        title_score = fuzz.token_sort_ratio(new_title, ex_title)
        if title_score < TITLE_THRESHOLD:
            continue

        # Company must match if both are present
        if new_company and ex_company:
            company_score = fuzz.token_sort_ratio(new_company, ex_company)
            if company_score < COMPANY_THRESHOLD:
                continue
        elif new_company != ex_company:
            # One has company, the other doesn't — weak match
            continue

        # City should match (exact or close)
        if new_city and ex_city:
            city_score = fuzz.ratio(new_city, ex_city)
            if city_score < 75:
                continue

        return existing

    return None


def _has_source(job: Job, site_name: str, site_url: str) -> bool:
    """Check if a job already has this specific source."""
    for source in job.sources:
        if source.site_name == site_name:
            if source.site_url == site_url:
                return True
    return False


def process_scraped_jobs(
    db: Session,
    scraped_jobs: List[Dict[str, Any]],
) -> Tuple[int, int, int, List[Job]]:
    """
    Process scraped jobs: deduplicate and store in database.

    Returns:
        Tuple of (total_found, new_jobs, updated_jobs, new_job_records)
    """
    # Load all active jobs from DB for matching
    existing_jobs = db.query(Job).filter(Job.is_active == True).all()

    new_count = 0
    updated_count = 0
    new_jobs: List[Job] = []
    now = _to_naive(datetime.now(timezone.utc))

    for raw_job in scraped_jobs:
        title = raw_job.get("title", "")
        # Filter out IT / tech architecture jobs (e.g. Cloud, Software, Solution, Data Architect)
        if not is_traditional_architect_job(title):
            logger.debug(f"Skipping IT/tech architecture job: '{title}'")
            continue

        site_name = raw_job.get("site_name", "unknown")
        site_url = raw_job.get("job_url", "")

        # Try to find a matching existing job
        match = _find_matching_job(raw_job, existing_jobs)

        if match:
            # Update last_seen
            match.last_seen = now

            # Update salary if we didn't have it before
            if match.salary_min is None and raw_job.get("salary_min"):
                match.salary_min = raw_job["salary_min"]
            if match.salary_max is None and raw_job.get("salary_max"):
                match.salary_max = raw_job["salary_max"]
            if match.salary_interval is None and raw_job.get("salary_interval"):
                match.salary_interval = raw_job["salary_interval"]

            # Update description if we didn't have one
            if not match.description and raw_job.get("description"):
                match.description = raw_job["description"]

            # Update date_posted if we get a more specific one
            raw_date = _to_naive(raw_job.get("date_posted"))
            match_date = _to_naive(match.date_posted)
            if raw_date and (match_date is None or raw_date < match_date):
                match.date_posted = raw_date

            # Add new source if not already tracked
            if not _has_source(match, site_name, site_url):
                new_source = JobSource(
                    job_id=match.id,
                    site_name=site_name,
                    site_url=site_url,
                    date_found=now,
                )
                db.add(new_source)
                updated_count += 1
                logger.debug(
                    f"  Updated: '{match.title}' — added source '{site_name}'"
                )
        else:
            # Create new job
            new_job = Job(
                title=raw_job.get("title"),
                company=raw_job.get("company"),
                city=raw_job.get("city"),
                state=raw_job.get("state"),
                job_type=raw_job.get("job_type"),
                salary_min=raw_job.get("salary_min"),
                salary_max=raw_job.get("salary_max"),
                salary_interval=raw_job.get("salary_interval"),
                salary_currency=raw_job.get("salary_currency", "EUR"),
                description=raw_job.get("description"),
                date_posted=_to_naive(raw_job.get("date_posted")),
                first_seen=now,
                last_seen=now,
                is_active=True,
                search_term_used=raw_job.get("search_term_used"),
            )
            db.add(new_job)
            db.flush()  # Get the ID for the source

            # Add the source
            source = JobSource(
                job_id=new_job.id,
                site_name=site_name,
                site_url=site_url,
                date_found=now,
            )
            db.add(source)

            existing_jobs.append(new_job)  # Add to in-memory list for dedup
            new_jobs.append(new_job)
            new_count += 1
            logger.debug(f"  New: '{new_job.title}' at '{new_job.company}'")

    db.commit()
    logger.info(
        f"Processed {len(scraped_jobs)} raw jobs → "
        f"{new_count} new, {updated_count} updated sources"
    )
    return len(scraped_jobs), new_count, updated_count, new_jobs
