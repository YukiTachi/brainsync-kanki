#!/usr/bin/env python3
"""CO2・温湿度・照度を定期測定して SQLite に記録する常駐プログラム

MH-Z19C (シリアル)、DHT20 (I2C)、VEML7700 (I2C) を INTERVAL 秒ごとに読み取り、
data/brainsync.db の measurements テーブルに追記する。
シリアルポートの権限のため root で動かす前提 (systemd: brainsync-logger.service)。
"""
import logging
import os
import signal
import sqlite3
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

import mh_z19  # noqa: E402
from dht20 import DHT20  # noqa: E402
from veml7700 import VEML7700  # noqa: E402

DB_PATH = os.path.join(BASE_DIR, "data", "brainsync.db")
INTERVAL = 60          # 測定間隔（秒）
WARMUP_TIME = 60       # MH-Z19C のウォームアップ時間（秒）
MAX_RETRIES = 3
RETRY_DELAY = 2

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("brainsync-logger")

_running = True


def _handle_sigterm(signum, frame):
    global _running
    _running = False


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS measurements (
               ts          INTEGER PRIMARY KEY,
               co2         INTEGER,
               temperature REAL,
               humidity    REAL,
               lux         REAL
           )"""
    )
    # 既存の DB には lux 列がないので、なければ追加する
    columns = {row[1] for row in conn.execute("PRAGMA table_info(measurements)")}
    if "lux" not in columns:
        conn.execute("ALTER TABLE measurements ADD COLUMN lux REAL")
        log.info("measurements テーブルに lux 列を追加しました")
    conn.commit()
    return conn


def read_co2():
    # serial_console_untouched: mh_z19 が serial-getty を停止/起動するのを抑止する。
    # getty を起動されると /dev/ttyS0 が root:tty に変わり、一般ユーザーで開けなくなる。
    for attempt in range(MAX_RETRIES):
        result = mh_z19.read_all(serial_console_untouched=True)
        if result and "co2" in result:
            return result["co2"]
        if attempt < MAX_RETRIES - 1:
            time.sleep(RETRY_DELAY)
    return None


def read_dht(sensor):
    for attempt in range(MAX_RETRIES):
        try:
            return sensor.read()
        except (RuntimeError, OSError) as e:
            log.warning("DHT20 読み取り失敗 (%d/%d): %s", attempt + 1, MAX_RETRIES, e)
            try:
                sensor.reset()
            except OSError:
                pass
            time.sleep(RETRY_DELAY)
    return None, None


def read_lux(sensor):
    for attempt in range(MAX_RETRIES):
        try:
            return round(sensor.read(), 1)
        except OSError as e:
            log.warning("VEML7700 読み取り失敗 (%d/%d): %s", attempt + 1, MAX_RETRIES, e)
            time.sleep(RETRY_DELAY)
    return None


def wait_for_warmup():
    """電源投入直後（ブート直後）のみウォームアップを待つ"""
    with open("/proc/uptime") as f:
        uptime = float(f.read().split()[0])
    if uptime < WARMUP_TIME * 2:
        wait = max(0, WARMUP_TIME - uptime)
        if wait > 0:
            log.info("ブート直後のためウォームアップ待機 %.0f 秒", wait)
            time.sleep(wait)


def main():
    signal.signal(signal.SIGTERM, _handle_sigterm)
    signal.signal(signal.SIGINT, _handle_sigterm)

    conn = init_db()
    dht = DHT20()
    try:
        dht.init()
    except OSError as e:
        log.warning("DHT20 初期化失敗（温湿度なしで続行）: %s", e)

    light = VEML7700()
    try:
        light.init()
    except OSError as e:
        log.warning("VEML7700 初期化失敗（照度なしで続行）: %s", e)

    wait_for_warmup()
    log.info("測定開始（間隔 %d 秒）", INTERVAL)

    while _running:
        ts = int(time.time())
        co2 = read_co2()
        temp, hum = read_dht(dht)
        lux = read_lux(light)

        if co2 is None and temp is None and lux is None:
            log.error("全センサーの読み取りに失敗、この周期はスキップ")
        else:
            conn.execute(
                "INSERT OR REPLACE INTO measurements (ts, co2, temperature, humidity, lux)"
                " VALUES (?, ?, ?, ?, ?)",
                (ts, co2, round(temp, 2) if temp is not None else None,
                 round(hum, 2) if hum is not None else None, lux),
            )
            conn.commit()
            log.info("記録: co2=%s ppm temp=%s ℃ hum=%s %% lux=%s",
                     co2, f"{temp:.1f}" if temp is not None else "-",
                     f"{hum:.1f}" if hum is not None else "-",
                     f"{lux:.1f}" if lux is not None else "-")

        # 次の分境界まで待機（SIGTERM に素早く反応できるよう小刻みに）
        next_ts = ts + INTERVAL - (ts % INTERVAL) if ts % INTERVAL else ts + INTERVAL
        while _running and time.time() < next_ts:
            time.sleep(1)

    log.info("終了します")
    conn.close()
    dht.close()
    light.close()


if __name__ == "__main__":
    main()
