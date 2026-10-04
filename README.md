# Kanki

室内の CO2 濃度・温度・湿度・明るさを Raspberry Pi で常時計測し、ブラウザから見られるようにするモニターです。
BrainSync プロダクト群の1つで、集中力や睡眠の質に影響する空気環境を振り返るために作りました。

名前の「Kanki」は、空気を入れ替える「換気」と、頭を呼び起こす「喚起」をかけたものです。

## できること

- CO2・温度・湿度・照度を **60秒ごとに記録**（SQLite に保存）
- 現在値のタイル（CO2・温度・湿度・不快指数・照度）と、それぞれの評価表示
- 5種類の折れ線グラフ。期間は 1時間〜30日の切り替えと、**日付＋時間帯の指定**（22:00〜翌6:00 のような日をまたぐ指定も可）
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
| VEML7700（環境光センサー） | I2C bus1 アドレス `0x10`、3.3V 給電 |

I2C の 2つのセンサーは、同じ SDA（GPIO2 / 物理3番ピン）と SCL（GPIO3 / 物理5番ピン）に並列でつなぎます。

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

### 更新の反映

ラズパイ上の `~/BrainSync` はこのリポジトリのクローンです（`data/` と `venv/` は git の管理外）。
コードを直したら、手元でコミットして push し、ラズパイで pull します。

```bash
# 手元で
git add -A && git commit -m "..." && git push

# ラズパイで
cd ~/BrainSync
git pull
sudo systemctl restart brainsync-web     # webapp.py / static/ を変えたとき
sudo systemctl restart brainsync-logger  # logger.py / dht20.py を変えたとき
```

ラズパイからの push には GitHub の認証が必要です（`gh auth login`、または書き込み可能なデプロイキーの登録）。
設定していない場合、ラズパイは pull のみ行えます。

## 構成

| ファイル | 役割 |
|---|---|
| `logger.py` | 計測デーモン。60秒ごとに両センサーを読み、SQLite `data/brainsync.db` に追記する |
| `dht20.py` | DHT20/AHT20 の I2C ドライバ |
| `veml7700.py` | VEML7700 の I2C ドライバ。明るさに応じてゲインと積分時間を自動で切り替える |
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
    humidity    REAL,                 -- %
    lux         REAL                  -- lx
);
```

不快指数は保存せず、`0.81T + 0.01H(0.99T − 14.3) + 46.3` で都度計算しています。
`lux` 列は後から追加したため、`logger.py` は起動時に列の有無を確認し、なければ自動で追加します。

## 開発メモ

- `mh_z19` ライブラリは既定で、読み取りのたびにシリアルコンソール（serial-getty）を停止・再起動します。
  この再起動で `/dev/ttyS0` の所有権が `root:tty` に戻り、2回目以降が Permission denied になります。
  そのため `logger.py` は `read_all(serial_console_untouched=True)` で呼んでいます。
- MH-Z19C は電源投入から約60秒で値が安定します。`logger.py` は起動時の uptime を見て、
  ブート直後だけウォームアップを待ちます。
- センサーは1つが失敗しても、残りの記録を続けます（3回までリトライ）。
- VEML7700 は積分時間を切り替えた直後、1回目の読み取りに前の設定の値が残ります。
  `veml7700.py` は設定変更後に待ち時間を取り、1回読み捨ててから測っています。
- 低ゲイン（x1/8、x1/4）は個体差で数%高めに出るため、自動調整は室内の明るさで
  ゲイン x1〜x2 に落ち着くようにしてあります。低ゲインを使うのは屋外並みに明るいときだけです。

## ライセンス

MIT
