"""
etl/extract.py
==============
Extracts raw operational (OLTP) tables from PostgreSQL into pandas DataFrames.

All downstream transforms operate purely on these DataFrames — no further
direct DB reads occur outside this module.  Every column is kept as-is so
that transform modules can make explicit decisions about what they use.

Connection:
    Uses the same DSN / .env convention as the data-generation pipeline.
    Place a .env file in the project root with:
        DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
"""

import os
import logging

import pandas as pd
import psycopg2
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CONNECTION
# ---------------------------------------------------------------------------

def get_connection():
    """
    Build a DSN string from environment variables.
    Credentials never appear as a plain dict at module level.
    """
    dsn = (
        f"host={os.getenv('DB_HOST', 'localhost')} "
        f"port={os.getenv('DB_PORT', '5433')} "
        f"dbname={os.getenv('DB_NAME', 'postgres')} "
        f"user={os.getenv('DB_USER', 'postgres')} "
        f"password={os.getenv('DB_PASSWORD', 'Quortha296!')}"
    )
    return psycopg2.connect(dsn)


def read_table(conn, schema: str, table: str) -> pd.DataFrame:
    """Generic helper — reads an entire table into a DataFrame."""
    query = f'SELECT * FROM {schema}."{table}"'
    df    = pd.read_sql(query, conn)
    log.info(f"  Extracted {schema}.{table}: {len(df):,} rows")
    return df

# ---------------------------------------------------------------------------
# PUBLIC EXTRACT FUNCTIONS
# ---------------------------------------------------------------------------

def extract_all(schema: str = "gym_analytics") -> dict[str, pd.DataFrame]:
    """
    Extract every operational table needed for the analytics layer.

    Returns a dict keyed by logical table name so callers can do:
        raw["members"], raw["bookings"], etc.
    """
    log.info("Extracting operational tables …")
    conn = get_connection()

    try:
        raw = {
            "members":          read_table(conn, schema, "members"),
            "trainers":         read_table(conn, schema, "trainers"),
            "classes":          read_table(conn, schema, "classes"),
            "schedules":        read_table(conn, schema, "schedules"),
            "bookings":         read_table(conn, schema, "bookings"),
            "cancellations":    read_table(conn, schema, "cancellations"),
            "attendance":       read_table(conn, schema, "attendance"),
            "payments":         read_table(conn, schema, "payments"),
            "trainer_sessions": read_table(conn, schema, "trainer_sessions"),
        }
    finally:
        conn.close()

    log.info("Extraction complete.")
    return raw