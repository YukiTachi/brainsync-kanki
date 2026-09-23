#!/usr/bin/env python3
"""Kanki（BrainSync 室内環境モニター）Web ダッシュボード (FastAPI)

SQLite の測定データを JSON で返す API と、静的ダッシュボードを配信する。
起動: uvicorn webapp:app --host 0.0.0.0 --port 8000
"""
import os
import sqlite3
import time
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "brainsync.db")
MAX_POINTS = 360  # 1グラフあたりの最大点数（超える範囲はバケット平均に集約）

# 不快指数 = 0.81T + 0.01H(0.99T - 14.3) + 46.3（T: 気温℃、H: 相対湿度%）
DI_SQL = "(0.81 * temperature + 0.01 * humidity * (0.99 * temperature - 14.3) + 46.3)"


def discomfort_index(temperature, humidity):
    if temperature is None or humidity is None:
        return None
    return round(0.81 * temperature + 0.01 * humidity * (0.99 * temperature - 14.3) + 46.3, 1)

app = FastAPI(title="Kanki")


def query(sql, params=()):
    if not os.path.exists(DB_PATH):
        raise HTTPException(status_code=503, detail="まだ測定データがありません")
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        conn.row_factory = sqlite3.Row
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


@app.get("/api/latest")
def latest():
    rows = query("SELECT ts, co2, temperature, humidity FROM measurements ORDER BY ts DESC LIMIT 1")
    if not rows:
        raise HTTPException(status_code=404, detail="まだ測定データがありません")
    result = dict(rows[0])
    result["discomfort"] = discomfort_index(result["temperature"], result["humidity"])
    return result


MAX_RANGE_SEC = 90 * 86400


def resolve_range(hours, start, end):
    """期間を (start, end) の UNIX 秒で返す。start 指定時は日時指定、なければ直近 hours 時間"""
    now = int(time.time())
    if start is None:
        return int(now - (hours or 24) * 3600), now
    if end is None:
        end = start + 86400
    if end <= start:
        raise HTTPException(status_code=400, detail="終了は開始より後にしてください")
    if end - start > MAX_RANGE_SEC:
        raise HTTPException(status_code=400, detail="指定できる期間は最大90日です")
    return start, end


RangeHours = Query(None, gt=0, le=24 * 90)
RangeStart = Query(None, ge=0, description="開始（UNIX秒）")
RangeEnd = Query(None, ge=0, description="終了（UNIX秒、この時刻は含まない）")


@app.get("/api/history")
def history(hours: float | None = RangeHours, start: int | None = RangeStart, end: int | None = RangeEnd):
    start, end = resolve_range(hours, start, end)
    # 測定間隔（60秒）の倍数に揃えて、バケットごとのサンプル数がばらつかないようにする
    bucket = max(1, -(-(end - start) // (MAX_POINTS * 60))) * 60
    rows = query(
        """SELECT (ts / :bucket) * :bucket AS t,
                  ROUND(AVG(co2))            AS co2,
                  ROUND(AVG(temperature), 1) AS temperature,
                  ROUND(AVG(humidity), 1)    AS humidity,
                  ROUND(AVG({DI_SQL}), 1)    AS discomfort
           FROM measurements
           WHERE ts >= :start AND ts < :end
           GROUP BY t ORDER BY t""".format(DI_SQL=DI_SQL),
        {"bucket": bucket, "start": start, "end": end},
    )
    return {"start": start, "end": end, "bucket_sec": bucket, "points": [dict(r) for r in rows]}


@app.get("/api/stats")
def stats(hours: float | None = RangeHours, start: int | None = RangeStart, end: int | None = RangeEnd):
    """選択期間の統計（バケット平均ではなく生データから算出）"""
    start, end = resolve_range(hours, start, end)
    rows = query(
        """SELECT MIN(co2) AS co2_min, ROUND(AVG(co2)) AS co2_avg, MAX(co2) AS co2_max,
                  SUM(co2 >= 1000) AS co2_high_minutes,
                  ROUND(MIN(temperature), 1) AS temp_min,
                  ROUND(AVG(temperature), 1) AS temp_avg,
                  ROUND(MAX(temperature), 1) AS temp_max,
                  ROUND(MIN(humidity)) AS hum_min,
                  ROUND(AVG(humidity)) AS hum_avg,
                  ROUND(MAX(humidity)) AS hum_max,
                  ROUND(MIN({DI_SQL}), 1) AS di_min,
                  ROUND(AVG({DI_SQL}), 1) AS di_avg,
                  ROUND(MAX({DI_SQL}), 1) AS di_max,
                  COUNT(*) AS samples
           FROM measurements WHERE ts >= :start AND ts < :end""".format(DI_SQL=DI_SQL),
        {"start": start, "end": end},
    )
    result = dict(rows[0])
    # 1分間隔での期待サンプル数に対する記録率（%）。未来の部分は分母に含めない
    expected = (min(end, int(time.time())) - start) / 60
    result["coverage_pct"] = round(min(100, result["samples"] / expected * 100)) if expected > 0 else 0
    return result


@app.get("/api/daily")
def daily(days: int = Query(7, gt=0, le=90)):
    """日次サマリー（ローカル日付ごと、今日を含む days 日分）

    起点をローカル0時に揃え、集計最古日が「日の途中から」にならないようにする
    （途中からだと記録率が実態より低く見えてしまう）。
    """
    today0 = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    since = int((today0 - timedelta(days=days - 1)).timestamp())
    rows = query(
        """SELECT date(ts, 'unixepoch', 'localtime') AS day,
                  ROUND(AVG(co2)) AS co2_avg, MAX(co2) AS co2_max,
                  SUM(co2 >= 1000) AS co2_high_minutes,
                  ROUND(AVG(temperature), 1) AS temp_avg,
                  ROUND(AVG(humidity)) AS hum_avg,
                  COUNT(*) AS samples
           FROM measurements WHERE ts >= :since
           GROUP BY day ORDER BY day DESC""",
        {"since": since},
    )
    return {"days": [dict(r) for r in rows]}


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE_DIR, "static", "index.html"))


app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
