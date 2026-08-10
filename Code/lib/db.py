"""
SQLite 存储层：指数日线、估值、评估、定投记录与元数据。

02_IndexETF 的所有数据统一存放在 data/market.db，不再使用按年 CSV。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)   # 首次运行自动创建 data/
DB_PATH = DATA_DIR / "market_index.db"


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection | None = None) -> sqlite3.Connection:
    """建表；返回传入的连接（若未传则新建并初始化后返回）。"""
    close = conn is None
    conn = conn or connect()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS indices(
                slug TEXT NOT NULL,
                date TEXT NOT NULL,
                open REAL, high REAL, low REAL, close REAL,
                adj_close REAL, volume REAL,
                symbol TEXT, name TEXT, region TEXT, currency TEXT, source TEXT,
                PRIMARY KEY(slug, date));
            CREATE TABLE IF NOT EXISTS valuations(
                slug TEXT NOT NULL,
                date TEXT NOT NULL,
                index_close REAL, pe_ttm REAL, equal_weight_pe_ttm REAL,
                median_pe_ttm REAL, pe_static REAL,
                pb REAL, equal_weight_pb REAL, median_pb REAL,
                earnings_yield REAL, name TEXT, source TEXT,
                PRIMARY KEY(slug, date));
            CREATE TABLE IF NOT EXISTS assessments(
                slug TEXT NOT NULL,
                date TEXT NOT NULL,
                close REAL, price_percentile REAL, drawdown_pct REAL,
                price_score REAL, drawdown_score REAL, trend_score REAL,
                valuation_score REAL, extra_investment_score REAL,
                method TEXT, confidence TEXT,
                PRIMARY KEY(slug, date));
            CREATE TABLE IF NOT EXISTS dca_records(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                code TEXT NOT NULL,
                fund TEXT,
                currency TEXT,
                position REAL,
                cost REAL,
                note TEXT);
            CREATE TABLE IF NOT EXISTS metadata(
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL);
            """
        )
        conn.commit()
    finally:
        if close:
            conn.close()
    return conn


# ---------------------------------------------------------------------------
# 指数日线
# ---------------------------------------------------------------------------

def upsert_indices(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    conn = connect()
    try:
        conn.executemany(
            """INSERT OR REPLACE INTO indices
               (slug, date, open, high, low, close, adj_close, volume,
                symbol, name, region, currency, source)
               VALUES (:slug, :date, :open, :high, :low, :close, :adj_close, :volume,
                       :symbol, :name, :region, :currency, :source)""",
            rows,
        )
        conn.commit()
    finally:
        conn.close()


def read_indices(slug: str) -> pd.DataFrame:
    conn = connect()
    try:
        df = pd.read_sql_query(
            "SELECT * FROM indices WHERE slug = ? ORDER BY date", conn, params=(slug,)
        )
    finally:
        conn.close()
    return df


def indices_latest_date(slug: str) -> str | None:
    conn = connect()
    try:
        row = conn.execute(
            "SELECT MAX(date) AS d FROM indices WHERE slug = ?", (slug,)
        ).fetchone()
        return row["d"] if row and row["d"] else None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 估值
# ---------------------------------------------------------------------------

def upsert_valuations(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    conn = connect()
    try:
        conn.executemany(
            """INSERT OR REPLACE INTO valuations
               (slug, date, index_close, pe_ttm, equal_weight_pe_ttm, median_pe_ttm,
                pe_static, pb, equal_weight_pb, median_pb, earnings_yield, name, source)
               VALUES (:slug, :date, :index_close, :pe_ttm, :equal_weight_pe_ttm,
                       :median_pe_ttm, :pe_static, :pb, :equal_weight_pb, :median_pb,
                       :earnings_yield, :name, :source)""",
            rows,
        )
        conn.commit()
    finally:
        conn.close()


def read_valuations(slug: str) -> pd.DataFrame:
    conn = connect()
    try:
        df = pd.read_sql_query(
            "SELECT * FROM valuations WHERE slug = ? ORDER BY date", conn, params=(slug,)
        )
    finally:
        conn.close()
    return df


def valuations_latest_date(slug: str) -> str | None:
    conn = connect()
    try:
        row = conn.execute(
            "SELECT MAX(date) AS d FROM valuations WHERE slug = ?", (slug,)
        ).fetchone()
        return row["d"] if row and row["d"] else None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 评估
# ---------------------------------------------------------------------------

def upsert_assessments(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    conn = connect()
    try:
        conn.executemany(
            """INSERT OR REPLACE INTO assessments
               (slug, date, close, price_percentile, drawdown_pct, price_score,
                drawdown_score, trend_score, valuation_score,
                extra_investment_score, method, confidence)
               VALUES (:slug, :date, :close, :price_percentile, :drawdown_pct,
                       :price_score, :drawdown_score, :trend_score, :valuation_score,
                       :extra_investment_score, :method, :confidence)""",
            rows,
        )
        conn.commit()
    finally:
        conn.close()


def read_assessments(slug: str) -> pd.DataFrame:
    conn = connect()
    try:
        df = pd.read_sql_query(
            "SELECT * FROM assessments WHERE slug = ? ORDER BY date", conn, params=(slug,)
        )
    finally:
        conn.close()
    return df


def assessments_latest_date(slug: str) -> str | None:
    conn = connect()
    try:
        row = conn.execute(
            "SELECT MAX(date) AS d FROM assessments WHERE slug = ?", (slug,)
        ).fetchone()
        return row["d"] if row and row["d"] else None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 定投记录
# ---------------------------------------------------------------------------

def read_dca_records() -> list[dict[str, Any]]:
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT date, code, fund, currency, position, cost, note "
            "FROM dca_records ORDER BY date, id"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def insert_dca_record(row: dict[str, Any]) -> dict[str, Any]:
    conn = connect()
    try:
        cur = conn.execute(
            """INSERT INTO dca_records(date, code, fund, currency, position, cost, note)
               VALUES (:date, :code, :fund, :currency, :position, :cost, :note)""",
            row,
        )
        conn.commit()
        row["id"] = cur.lastrowid
        return row
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 元数据（原来存放在 data/metadata.json）
# ---------------------------------------------------------------------------

def get_metadata() -> dict[str, Any]:
    conn = connect()
    try:
        row = conn.execute("SELECT value FROM metadata WHERE key = 'app'").fetchone()
        return json.loads(row["value"]) if row else {}
    finally:
        conn.close()


def save_metadata(metadata: dict[str, Any]) -> None:
    conn = connect()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES ('app', ?)",
            (json.dumps(metadata, ensure_ascii=False),),
        )
        conn.commit()
    finally:
        conn.close()
