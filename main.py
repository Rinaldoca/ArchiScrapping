"""
ArchiScrapping — Main FastAPI application.
Serves the dashboard, API endpoints, and manages background scraping.
"""
import logging
import threading
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Depends, Query, Request, BackgroundTasks, Header, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, desc
from sqlalchemy.orm import Session, joinedload
from apscheduler.schedulers.background import BackgroundScheduler

from config import settings
from database import init_db, get_db, SessionLocal, Job, JobSource, ScrapeLog
from scraper import scrape_architect_jobs
from deduplicator import process_scraped_jobs, is_traditional_architect_job
from telegram_notifier import notify_new_jobs, is_telegram_configured, test_telegram_connection

# ─── Logging ─────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("archiscrapping")

# ─── Concurrency & Scheduled Scraping ───────────────────────────────────────────

scheduler = BackgroundScheduler()
scrape_lock = threading.Lock()


def run_scrape_task():
    """Background task: scrape and process jobs with concurrency guard."""
    if not scrape_lock.acquire(blocking=False):
        logger.warning("Scrape already running — skipping duplicate request")
        return

    logger.info("═══ Starting scheduled scrape ═══")
    db = SessionLocal()
    try:
        # Create scrape log
        log = ScrapeLog(status="running")
        db.add(log)
        db.commit()

        try:
            raw_jobs = scrape_architect_jobs()
            total, new, updated, new_jobs_list = process_scraped_jobs(db, raw_jobs)

            log.finished_at = datetime.now(timezone.utc)
            log.status = "success"
            log.jobs_found = total
            log.jobs_new = new
            log.jobs_updated = updated
            db.commit()

            logger.info(
                f"═══ Scrape complete: {total} found, {new} new, {updated} updated ═══"
            )

            # Send Telegram notifications for newly discovered offers
            if new_jobs_list and is_telegram_configured():
                try:
                    logger.info(f"Triggering Telegram alerts for {len(new_jobs_list)} new jobs")
                    notify_new_jobs(new_jobs_list)
                except Exception as notify_err:
                    logger.error(f"Telegram notification error: {notify_err}")
        except Exception as e:
            log.finished_at = datetime.now(timezone.utc)
            log.status = "failed"
            log.error_message = str(e)
            db.commit()
            logger.error(f"═══ Scrape failed: {e} ═══", exc_info=True)

    finally:
        db.close()
        scrape_lock.release()


# ─── App Lifecycle ───────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # Initialize database
    init_db()
    logger.info("Database initialized")

    # Schedule periodic scraping
    scheduler.add_job(
        run_scrape_task,
        "interval",
        hours=settings.scrape_interval_hours,
        id="periodic_scrape",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(f"Scheduler started — scraping every {settings.scrape_interval_hours}h")

    # Run initial scrape only if database has no active jobs
    db = SessionLocal()
    try:
        # Clean up any legacy IT / software architecture jobs from database
        all_active = db.query(Job).filter(Job.is_active == True).all()
        purged = 0
        for j in all_active:
            if not is_traditional_architect_job(j.title):
                db.delete(j)
                purged += 1
        if purged > 0:
            db.commit()
            logger.info(f"Purged {purged} non-traditional / IT architecture jobs from database")

        existing_job = db.query(Job.id).filter(Job.is_active == True).first()
        if not existing_job:
            scheduler.add_job(run_scrape_task, id="initial_scrape")
            logger.info("Database is empty: initial scrape queued")
        else:
            logger.info("Database already populated: skipping redundant initial scrape")
    finally:
        db.close()

    yield

    # Shutdown
    scheduler.shutdown(wait=False)
    logger.info("Scheduler stopped")


# ─── FastAPI App ─────────────────────────────────────────────────────────────────

app = FastAPI(
    title="ArchiScrapping",
    description="Architect Job Aggregator for Germany",
    version="1.0.0",
    lifespan=lifespan,
)

# Mount static files and templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# ─── Dashboard Route ─────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    """Serve the main dashboard page."""
    return templates.TemplateResponse(request, "index.html")


# ─── API: Jobs ────────────────────────────────────────────────────────────────────

@app.get("/api/jobs")
async def get_jobs(
    search: Optional[str] = Query(None, description="Search in title, company, description"),
    city: Optional[str] = Query(None, description="Filter by city"),
    source: Optional[str] = Query(None, description="Filter by source site"),
    salary_min: Optional[float] = Query(None, description="Minimum salary"),
    job_type: Optional[str] = Query(None, description="Filter by job type"),
    has_salary: Optional[bool] = Query(None, description="Only jobs with salary info"),
    sort: Optional[str] = Query("newest", description="Sort: newest, salary_high, salary_low, sources"),
    page: int = Query(1, ge=1),
    per_page: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Get jobs with filtering, sorting, and pagination."""
    query = db.query(Job).options(joinedload(Job.sources)).filter(Job.is_active == True)

    # Apply filters
    if search:
        search_pattern = f"%{search}%"
        query = query.filter(
            (Job.title.ilike(search_pattern))
            | (Job.company.ilike(search_pattern))
            | (Job.description.ilike(search_pattern))
        )

    if city:
        query = query.filter(Job.city.ilike(f"%{city}%"))

    if source:
        query = query.join(Job.sources).filter(JobSource.site_name == source)

    if salary_min is not None:
        query = query.filter(
            (Job.salary_max >= salary_min) | (Job.salary_min >= salary_min)
        )

    if job_type:
        query = query.filter(Job.job_type == job_type)

    if has_salary:
        query = query.filter(
            (Job.salary_min.isnot(None)) | (Job.salary_max.isnot(None))
        )

    # Count total before pagination
    # Use subquery for correct count with joins
    total = query.with_entities(func.count(func.distinct(Job.id))).scalar()

    # Apply sorting
    if sort == "salary_high":
        query = query.order_by(desc(Job.salary_max).nulls_last())
    elif sort == "salary_low":
        query = query.order_by(Job.salary_min.asc().nulls_last())
    elif sort == "sources":
        # Sort by number of sources (most cross-posted first)
        query = query.order_by(desc(Job.last_seen))
    else:  # newest
        query = query.order_by(desc(Job.date_posted).nulls_last(), desc(Job.first_seen))

    # Paginate — deduplicate after join
    offset = (page - 1) * per_page
    jobs = query.distinct(Job.id).offset(offset).limit(per_page).all()

    # Deduplicate in Python (joinedload + distinct can cause issues)
    seen_ids = set()
    unique_jobs = []
    for job in jobs:
        if job.id not in seen_ids:
            seen_ids.add(job.id)
            unique_jobs.append(job)

    return {
        "jobs": [j.to_dict() for j in unique_jobs],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": max(1, (total + per_page - 1) // per_page),
    }


# ─── API: Stats ───────────────────────────────────────────────────────────────────

@app.get("/api/stats")
async def get_stats(db: Session = Depends(get_db)):
    """Get aggregated statistics for the dashboard."""
    total_jobs = db.query(func.count(Job.id)).filter(Job.is_active == True).scalar()

    # Jobs with salary
    jobs_with_salary = (
        db.query(func.count(Job.id))
        .filter(
            Job.is_active == True,
            (Job.salary_min.isnot(None)) | (Job.salary_max.isnot(None)),
        )
        .scalar()
    )

    # Average salary
    avg_salary = (
        db.query(func.avg(Job.salary_max))
        .filter(Job.is_active == True, Job.salary_max.isnot(None))
        .scalar()
    )

    # Jobs per city (top 20)
    cities_raw = (
        db.query(Job.city, func.count(Job.id).label("count"))
        .filter(Job.is_active == True, Job.city.isnot(None))
        .group_by(Job.city)
        .order_by(desc("count"))
        .limit(20)
        .all()
    )
    cities = [{"city": c[0], "count": c[1]} for c in cities_raw]

    # Jobs per source
    sources_raw = (
        db.query(JobSource.site_name, func.count(func.distinct(JobSource.job_id)).label("count"))
        .join(Job)
        .filter(Job.is_active == True)
        .group_by(JobSource.site_name)
        .all()
    )
    sources = [{"source": s[0], "count": s[1]} for s in sources_raw]

    # Multi-source jobs (duplicates found on multiple sites)
    multi_source_count = (
        db.query(func.count(func.distinct(JobSource.job_id)))
        .group_by(JobSource.job_id)
        .having(func.count(JobSource.id) > 1)
        .count()
    )

    # Recent scrape logs
    recent_scrapes = (
        db.query(ScrapeLog)
        .order_by(desc(ScrapeLog.started_at))
        .limit(5)
        .all()
    )

    # Job types distribution
    job_types_raw = (
        db.query(Job.job_type, func.count(Job.id).label("count"))
        .filter(Job.is_active == True, Job.job_type.isnot(None))
        .group_by(Job.job_type)
        .all()
    )
    job_types = [{"type": jt[0], "count": jt[1]} for jt in job_types_raw]

    # Unique cities count
    unique_cities = (
        db.query(func.count(func.distinct(Job.city)))
        .filter(Job.is_active == True, Job.city.isnot(None))
        .scalar()
    )

    return {
        "total_jobs": total_jobs,
        "jobs_with_salary": jobs_with_salary,
        "avg_salary": round(avg_salary, 0) if avg_salary else None,
        "unique_cities": unique_cities,
        "multi_source_jobs": multi_source_count,
        "cities": cities,
        "sources": sources,
        "job_types": job_types,
        "recent_scrapes": [s.to_dict() for s in recent_scrapes],
    }


# ─── API: Filters (for dropdowns) ────────────────────────────────────────────────

@app.get("/api/filters")
async def get_filters(db: Session = Depends(get_db)):
    """Get available filter options for the UI."""
    cities = (
        db.query(Job.city)
        .filter(Job.is_active == True, Job.city.isnot(None))
        .distinct()
        .order_by(Job.city)
        .all()
    )

    sources = (
        db.query(JobSource.site_name)
        .distinct()
        .order_by(JobSource.site_name)
        .all()
    )

    job_types = (
        db.query(Job.job_type)
        .filter(Job.is_active == True, Job.job_type.isnot(None))
        .distinct()
        .all()
    )

    return {
        "cities": [c[0] for c in cities],
        "sources": [s[0] for s in sources],
        "job_types": [jt[0] for jt in job_types],
    }


@app.get("/health")
async def health_check():
    """Lightweight health check endpoint for Railway and load balancers."""
    return {"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()}


# ─── API: Trigger Scrape ──────────────────────────────────────────────────────────

@app.post("/api/scrape")
async def trigger_scrape(background_tasks: BackgroundTasks):
    """Manually trigger a scrape run."""
    if scrape_lock.locked():
        return JSONResponse(
            status_code=409,
            content={"status": "busy", "message": "A scrape is already in progress. Please wait."}
        )
    background_tasks.add_task(run_scrape_task)
    return {"status": "ok", "message": "Scrape started in background"}


# ─── API: Ingest (push jobs scraped locally, e.g. StepStone from a residential IP) ─

@app.post("/api/jobs/ingest")
async def ingest_jobs(request: Request, x_api_key: Optional[str] = Header(None)):
    """Accept jobs scraped by an external/local process and merge them into the DB."""
    if not settings.ingest_api_key:
        raise HTTPException(status_code=503, detail="Ingest is not configured")
    if x_api_key != settings.ingest_api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")

    payload = await request.json()
    raw_jobs = payload.get("jobs", [])
    for job in raw_jobs:
        date_posted = job.get("date_posted")
        if isinstance(date_posted, str):
            try:
                job["date_posted"] = datetime.fromisoformat(date_posted)
            except ValueError:
                job["date_posted"] = None

    db = SessionLocal()
    try:
        total, new, updated, new_jobs_list = process_scraped_jobs(db, raw_jobs)
        if new_jobs_list and is_telegram_configured():
            try:
                notify_new_jobs(new_jobs_list)
            except Exception as notify_err:
                logger.error(f"Telegram notification error: {notify_err}")
    finally:
        db.close()

    return {"status": "ok", "total": total, "new": new, "updated": updated}


# ─── API: Scrape Status ──────────────────────────────────────────────────────────

@app.get("/api/scrape/status")
async def scrape_status(db: Session = Depends(get_db)):
    """Get the status of the most recent scrape."""
    latest = (
        db.query(ScrapeLog)
        .order_by(desc(ScrapeLog.started_at))
        .first()
    )
    if latest:
        return latest.to_dict()
    return {"status": "none", "message": "No scrapes have been run yet"}


# ─── API: Telegram Notifications ─────────────────────────────────────────────────

@app.get("/api/telegram/status")
async def telegram_status():
    """Check if Telegram notifications are configured and active."""
    return {
        "configured": is_telegram_configured(),
        "enabled": settings.telegram_enabled,
        "has_token": bool(settings.telegram_bot_token),
        "has_chat_id": bool(settings.telegram_chat_id),
    }


@app.post("/api/telegram/test")
async def telegram_test():
    """Send a test message to Telegram to verify credentials."""
    success, message = test_telegram_connection()
    if success:
        return {"status": "ok", "message": message}
    return JSONResponse(status_code=400, content={"status": "error", "message": message})


# ─── Run ──────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=True,
    )
