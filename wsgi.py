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

    # Master daily digest: daily 08:00 UTC (Task #17)
    def scheduled_master_digest():
        try:
            from master_brain_tactics import generate_master_brain_digest
            from distribution import publish_digest
            master_id = db.get_master_brain_id()
            if not master_id:
                logger.info("master brain not initialized, skip digest")
                return
            digest = generate_master_brain_digest(master_id)
            if not digest:
                logger.info("master digest skipped: no activity in last 24h")
                return
            digest['master_id'] = master_id
            result = publish_digest(digest)
            logger.info("master digest published: %s", result)
        except Exception as e:
            logger.exception("scheduled_master_digest failed: %s", e)

    scheduler.add_job(scheduled_master_digest, 'cron', hour=8, minute=0,
                      id='daily_master_digest', max_instances=1, coalesce=True)

    scheduler.start()
    logger.info("APScheduler started")


db.init_db()

if acquire_scheduler_lock():
    start_scheduler()
    logger.info("This worker owns the scheduler lock")

    # === 观察员事件订阅 ===
    try:
        import observer as _observer
        _observer.register_observer_handlers()
        logger.info("Observer handlers registered")
    except Exception:
        logger.exception("register_observer_handlers failed")

    # === ATA 编排器初始化（订阅事件 + 注册角色）===
    try:
        from orchestrator import ATAOrchestrator
        _ata = ATAOrchestrator.instance()
        logger.info("ATAOrchestrator initialized, handlers: %s", _ata.event_bus.list_handlers())
    except Exception:
        logger.exception("ATAOrchestrator init failed")
        _ata = None

    # === 恢复已有活跃大脑的思考循环 ===
    def _resume_active_brains():
        """应用启动时恢复所有 active/thinking 状态的大脑。"""
        if _ata is None:
            return
        try:
            with db.get_db() as conn:
                rows = conn.execute(
                    "SELECT id FROM brains WHERE state IN ('active', 'thinking')"
                ).fetchall()
            for row in rows:
                brain_id = row['id'] if isinstance(row, dict) else row[0]
                try:
                    started = _ata.start_brain(brain_id)
                    logger.info("Resume brain %s: %s", brain_id, "started" if started else "already running")
                except Exception as e:
                    logger.warning("Failed to resume brain %s: %s", brain_id, e)
        except Exception:
            logger.exception("_resume_active_brains failed")

    _resume_active_brains()

else:
    logger.info("Another worker owns the scheduler lock")

application = app
