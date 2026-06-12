"""WSGI entry + APScheduler with file lock."""
import os
import fcntl
import logging
from app import app, db

logger = logging.getLogger(__name__)

LOCK_FILE = '/tmp/ainstein-scheduler.lock'
_lock_fd = None


def acquire_scheduler_lock():
    global _lock_fd
    try:
        _lock_fd = open(LOCK_FILE, 'a')
        fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _lock_fd.seek(0)
        _lock_fd.truncate()
        _lock_fd.write(str(os.getpid()))
        _lock_fd.flush()
        return True
    except (IOError, OSError):
        return False


def start_scheduler():
    from apscheduler.schedulers.background import BackgroundScheduler
    scheduler = BackgroundScheduler(timezone='UTC')

    # Researcher: daily 03:30 UTC
    def scheduled_researcher():
        projects = db.get_projects()
        for p in projects:
            try:
                from agents.researcher import run_research_session
                run_research_session(p['id'])
            except Exception as e:
                logger.error(f"Researcher failed for project {p['id']}: {e}")

    scheduler.add_job(scheduled_researcher, 'cron', hour=3, minute=30,
                      id='daily_researcher', max_instances=1, coalesce=True)

    # Director: daily 10:00 UTC
    def scheduled_director():
        projects = db.get_projects()
        for p in projects:
            try:
                from agents.director import run_director_daily
                run_director_daily(p['id'])
            except Exception as e:
                logger.error(f"Director failed for project {p['id']}: {e}")

    scheduler.add_job(scheduled_director, 'cron', hour=10, minute=0,
                      id='daily_director', max_instances=1, coalesce=True)

    # Scientist: weekly Monday 06:00 UTC
    def scheduled_scientist():
        projects = db.get_projects()
        for p in projects:
            try:
                from agents.scientist import run_scientist
                run_scientist(p['id'])
            except Exception as e:
                logger.error(f"Scientist failed for project {p['id']}: {e}")

    scheduler.add_job(scheduled_scientist, 'cron', day_of_week='mon', hour=6, minute=0,
                      id='weekly_scientist', max_instances=1, coalesce=True)

    scheduler.start()
    logger.info("APScheduler started")


db.init_db()

if acquire_scheduler_lock():
    start_scheduler()
    logger.info("This worker owns the scheduler lock")
else:
    logger.info("Another worker owns the scheduler lock")

application = app
