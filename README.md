# Kanki

室内の CO2 濃度・温度・湿度を Raspberry Pi で常時計測し、ブラウザから見られるようにするモニターです。
BrainSync プロダクト群の1つで、集中力や睡眠の質に影響する空気環境を振り返るために作りました。

名前の「Kanki」は、空気を入れ替える「換気」と、頭を呼び起こす「喚起」をかけたものです。

## できること

- CO2・温度・湿度を **60秒ごとに記録**（SQLite に保存）
- 現在値のタイル（CO2・温度・湿度・不快指数）と、それぞれの評価表示
- 4種類の折れ線グラフ。期間は 1時間〜30日の切り替えと、**日付＋時間帯の指定**（22:00〜翌6:00 のような日をまたぐ指定も可）
- 期間ごとの最小・平均・最大、CO2 が 1000 ppm を超えていた時間
- 日次サマリー表（直近7日。日付を押すとその日のグラフへ）
- CO2 1000 ppm と不快指数 75 の基準線
- 欠測区間はグラフの線を切って表示。測定が止まると警告
- ライト/ダークテーマ、スマートフォン表示に対応

## 必要なもの

| 部品 | 接続 |
|---|---|
| Raspberry Pi（3 Model B+ で動作確認） | Raspberry Pi OS (Bookworm), Python 3.11 以降 |
| MH-Z19C（CO2 センサー） | UART `/dev/serial0` 9600bps、5V 給電 |
| DHT20 / AHT20（温湿度センサー） | I2C bus1 アドレス `0x38`、3.3V 給電 |

I2C と、シリアルポートのハードウェア有効化が必要です。`raspi-config` で設定してください。

## セットアップ

```bash
git clone https://github.com/YukiTachi/brainsync-kanki.git
cd brainsync-kanki

python3 -m venv venv
./venv/bin/pip install -r requirements.txt

# ダッシュボードが使う Chart.js を取得（リポジトリには含めていません）
curl -sL https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js -o static/chart.umd.min.js
```

### シリアルコンソールを無効化する

MH-Z19C が使う `/dev/serial0` は、初期状態ではシリアルコンソールに占有されています。
無効化しないと、一般ユーザーで CO2 を読み取れません。

```bash
sudo raspi-config nonint do_serial_cons 1
sudo reboot
```

### サービスとして動かす

`systemd/` のユニットファイルは、このリポジトリを `/home/yukit/BrainSync` に置いた前提で書かれています。
別の場所に置く場合は、`User` と各パスを書き換えてください。

```bash
sudo cp systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now brainsync-logger brainsync-web
```

`http://<ラズパイのIPアドレス>:8000` でダッシュボードが開きます（同じ LAN 内から）。

## 構成

| ファイル | 役割 |
|---|---|
| `logger.py` | 計測デーモン。60秒ごとに両センサーを読み、SQLite `data/brainsync.db` に追記する |
| `dht20.py` | DHT20/AHT20 の I2C ドライバ |
| `webapp.py` | FastAPI のサーバー。JSON API とダッシュボードを配信する |
| `static/index.html` | ダッシュボード本体（Chart.js） |
| `systemd/` | 自動起動用のユニットファイル |
| `tools/` | 動作確認用スクリプト（I2C スキャン、各センサー単体の読み取り） |

### API

| エンドポイント | 内容 |
|---|---|
| `GET /api/latest` | 最新の測定値（不快指数を含む） |
| `GET /api/history?hours=24` | グラフ用の時系列。点数が多い期間は自動で平均に集約する |
| `GET /api/history?start=<UNIX秒>&end=<UNIX秒>` | 期間を指定して取得（`end` は含まない、最大90日） |
| `GET /api/stats?hours=24` | 期間の最小・平均・最大、1000 ppm 超の分数、記録率 |
| `GET /api/daily?days=7` | 日次サマリー |

### データ

`data/brainsync.db`（SQLite）の `measurements` テーブルに、1分ごとの行が入ります。

```sql
CREATE TABLE measurements (
    ts          INTEGER PRIMARY KEY,  -- UNIX 秒
    co2         INTEGER,              -- ppm
    temperature REAL,                 -- ℃
    humidity    REAL                  -- %
);
```

不快指数は保存せず、`0.81T + 0.01H(0.99T − 14.3) + 46.3` で都度計算しています。

## 開発メモ

- `mh_z19` ライブラリは既定で、読み取りのたびにシリアルコンソール（serial-getty）を停止・再起動します。
  この再起動で `/dev/ttyS0` の所有権が `root:tty` に戻り、2回目以降が Permission denied になります。
  そのため `logger.py` は `read_all(serial_console_untouched=True)` で呼んでいます。
- MH-Z19C は電源投入から約60秒で値が安定します。`logger.py` は起動時の uptime を見て、
  ブート直後だけウォームアップを待ちます。
- センサーは片方が失敗しても、もう片方の記録を続けます（3回までリトライ）。

## ライセンス

MIT
