"""
ArchiScrapping — Database models and session management.
Uses SQLAlchemy ORM with SQLite (or PostgreSQL on Railway).
"""
from datetime import datetime, timezone
from sqlalchemy import (
    create_engine, Column, Integer, String, Float, Text, DateTime,
    Boolean, ForeignKey, Index, event
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from config import settings

Base = declarative_base()


class Job(Base):
    """A deduplicated job posting, potentially found on multiple sites."""
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(500), nullable=False, index=True)
    company = Column(String(500), nullable=True)
    city = Column(String(200), nullable=True, index=True)
    state = Column(String(200), nullable=True)
    job_type = Column(String(50), nullable=True)  # fulltime, parttime, contract, internship
    salary_min = Column(Float, nullable=True)
    salary_max = Column(Float, nullable=True)
    salary_interval = Column(String(50), nullable=True)  # yearly, monthly, hourly
    salary_currency = Column(String(10), nullable=True, default="EUR")
    description = Column(Text, nullable=True)
    date_posted = Column(DateTime, nullable=True)
    first_seen = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_seen = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    is_active = Column(Boolean, default=True)
    search_term_used = Column(String(200), nullable=True)

    # Relationship to sources
    sources = relationship("JobSource", back_populates="job", cascade="all, delete-orphan")

    # Indexes for common queries
    __table_args__ = (
        Index("ix_jobs_company_city", "company", "city"),
        Index("ix_jobs_date_posted", "date_posted"),
        Index("ix_jobs_salary", "salary_min", "salary_max"),
    )

    @property
    def source_names(self):
        """List of site names where this job was found."""
        return list(set(s.site_name for s in self.sources))

    @property
    def source_count(self):
        """Number of different sites where this job was found."""
        return len(self.source_names)

    @property
    def salary_display(self):
        """Human-readable salary string."""
        if self.salary_min is None and self.salary_max is None:
            return None

        currency = self.salary_currency or "€"
        if currency == "EUR":
            currency = "€"

        interval_map = {"yearly": "/year", "monthly": "/month", "hourly": "/hr"}
        interval = interval_map.get(self.salary_interval, "")

        if self.salary_min and self.salary_max:
            return f"{currency}{self.salary_min:,.0f} – {currency}{self.salary_max:,.0f}{interval}"
        elif self.salary_min:
            return f"From {currency}{self.salary_min:,.0f}{interval}"
        elif self.salary_max:
            return f"Up to {currency}{self.salary_max:,.0f}{interval}"
        return None

    def to_dict(self):
        """Serialize job to dictionary for API responses."""
        return {
            "id": self.id,
            "title": self.title,
            "company": self.company,
            "city": self.city,
            "state": self.state,
            "job_type": self.job_type,
            "salary_min": self.salary_min,
            "salary_max": self.salary_max,
            "salary_interval": self.salary_interval,
            "salary_currency": self.salary_currency,
            "salary_display": self.salary_display,
            "description": self.description,
            "date_posted": self.date_posted.isoformat() if self.date_posted else None,
            "first_seen": self.first_seen.isoformat() if self.first_seen else None,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "is_active": self.is_active,
            "search_term_used": self.search_term_used,
            "sources": [s.to_dict() for s in self.sources],
            "source_names": self.source_names,
            "source_count": self.source_count,
        }


class JobSource(Base):
    """Tracks which job board site a job was found on."""
    __tablename__ = "job_sources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(Integer, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    site_name = Column(String(50), nullable=False)  # linkedin, indeed, glassdoor, etc.
    site_url = Column(String(2000), nullable=True)
    date_found = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    job = relationship("Job", back_populates="sources")

    __table_args__ = (
        Index("ix_job_sources_site", "site_name"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "site_name": self.site_name,
            "site_url": self.site_url,
            "date_found": self.date_found.isoformat() if self.date_found else None,
        }


class ScrapeLog(Base):
    """Tracks scraping runs for monitoring."""
    __tablename__ = "scrape_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    started_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    finished_at = Column(DateTime, nullable=True)
    status = Column(String(50), default="running")  # running, success, failed
    jobs_found = Column(Integer, default=0)
    jobs_new = Column(Integer, default=0)
    jobs_updated = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "status": self.status,
            "jobs_found": self.jobs_found,
            "jobs_new": self.jobs_new,
            "jobs_updated": self.jobs_updated,
            "error_message": self.error_message,
        }


# ─── Engine & Session ───────────────────────────────────────────────────────────

def _get_engine():
    """Create the SQLAlchemy engine based on settings."""
    url = settings.database_url
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)

    # SQLite-specific settings
    if url.startswith("sqlite"):
        engine = create_engine(url, connect_args={"check_same_thread": False}, echo=False)

        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()
    else:
        engine = create_engine(url, echo=False, pool_pre_ping=True)

    return engine


engine = _get_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """Create all tables if they don't exist."""
    Base.metadata.create_all(bind=engine)


def get_db():
    """Dependency for FastAPI — yields a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
