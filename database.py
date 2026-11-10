"""
database.py — Conductor database connection.

Dev  (DEV_MODE=true  or DB_PATH set): SQLite via DB_PATH
Prod (DEV_MODE=false):                MS SQL Server via CONDUCTOR_DB_* vars

.env variables:
  # Dev only
  DB_PATH=C:\\path\\to\\conductor.db

  # Prod only
  CONDUCTOR_DB_SERVER=MPMEDW1
  CONDUCTOR_DB_DATABASE=Audittables
  CONDUCTOR_DB_SCHEMA=MPMC
  CONDUCTOR_DB_DRIVER=ODBC Driver 17 for SQL Server

  # Controls which DB is used
  DEV_MODE=true   → SQLite
  DEV_MODE=false  → MSSQL
"""
from sqlalchemy import create_engine, event, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
import os

load_dotenv()

# ── Determine which DB to use ──────────────────────────────────────────────────
_dev_mode = os.getenv("DEV_MODE", "false").lower() == "true"

if _dev_mode:
    # ── SQLite (local dev) ─────────────────────────────────────────────────
    DB_PATH      = os.getenv("DB_PATH", os.path.join(os.path.dirname(__file__), "conductor.db"))
    DATABASE_URL = f"sqlite:///{DB_PATH}"

    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        echo=False,
    )

    # SQLite doesn't enforce FK constraints by default — enable on every connection
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    print("🗄️  Database: SQLite (dev mode)")

else:
    # ── MS SQL Server (production) ─────────────────────────────────────────
    _server   = os.getenv("CONDUCTOR_DB_SERVER",   "MPMEDW1")
    _database = os.getenv("CONDUCTOR_DB_DATABASE", "Audittables")
    _driver   = os.getenv("CONDUCTOR_DB_DRIVER",   "ODBC Driver 17 for SQL Server")

    DATABASE_URL = (
        f"mssql+pyodbc://@{_server}/{_database}"
        f"?driver={_driver.replace(' ', '+')}"
        f"&trusted_connection=yes"   # Windows auth — same service account as GS
    )

    engine = create_engine(
        DATABASE_URL,
        echo=False,
        fast_executemany=True,   # performance boost for bulk inserts
        # ── Connection pool tuning ─────────────────────────────────────────
        pool_size=10,            # keep 10 warm connections ready (default was 5)
        max_overflow=20,         # allow up to 20 extra under burst load
        pool_pre_ping=True,      # health-check before reusing a connection
        pool_recycle=1800,       # recycle connections every 30 min to avoid
                                 # "connection broken" errors from SQL Server
                                 # dropping idle connections at the firewall
        pool_timeout=30,         # raise after 30 s if no connection available
    )

    print(f"🗄️  Database: SQL Server ({_server}/{_database})")

# ── Schema prefix for SQL Server ──────────────────────────────────────────────
# In prod all tables live under MPMC schema e.g. MPMC.users
# SQLAlchemy needs to know this so queries are routed correctly
DB_SCHEMA = None if _dev_mode else os.getenv("CONDUCTOR_DB_SCHEMA", "MPMC")

# ── Session & Base ─────────────────────────────────────────────────────────────
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base         = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """
    Dev:  creates all tables automatically from models (SQLite).
    Prod: tables already exist (created by IT via SQL script) — skip create_all.
          Only seeds the default admin if the users table is empty.
    """
    from models import User, Script, Schedule, RunLog, Feedback, Dashboard  # noqa

    if _dev_mode:
        Base.metadata.create_all(bind=engine)
        db = SessionLocal()
        try:
            if db.query(User).count() == 0:
                from passlib.context import CryptContext
                pwd   = CryptContext(schemes=["bcrypt"])
                admin = User(
                    name            = "Admin",
                    email           = "admin@medpointmanagement.com",
                    hashed_password = pwd.hash("admin"),
                    role            = "admin",
                    department      = "HIT",
                    title           = "Administrator",
                    is_active       = True,
                )
                db.add(admin)
                db.commit()
                print("✅ Default admin: admin@medpointmanagement.com / admin")
        finally:
            db.close()
    else:
        # Prod — tables exist, just verify connection works
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            print("✅ SQL Server connection verified")
        except Exception as e:
            print(f"❌ SQL Server connection failed: {e}")
            raise
