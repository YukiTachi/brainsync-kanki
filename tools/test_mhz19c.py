#!/usr/bin/env python3
import mh_z19
import time
import sys
import os
import argparse
from contextlib import contextmanager

# 設定
WARMUP_TIME = 60      # ウォームアップ時間（秒）
MEASURE_COUNT = 5     # 測定回数
MEASURE_INTERVAL = 10 # 測定間隔（秒）
MAX_RETRIES = 3       # リトライ回数
RETRY_DELAY = 2       # リトライ間隔（秒）


def parse_args():
    """コマンドライン引数をパース"""
    parser = argparse.ArgumentParser(
        description='MH-Z19C CO2センサー動作確認テスト'
    )
    parser.add_argument(
        '-s', '--skip-warmup',
        action='store_true',
        help='ウォームアップをスキップする'
    )
    parser.add_argument(
        '-n', '--count',
        type=int,
        default=MEASURE_COUNT,
        help=f'測定回数（デフォルト: {MEASURE_COUNT}）'
    )
    return parser.parse_args()


@contextmanager
def suppress_stderr():
    """標準エラー出力を一時的に抑制"""
    stderr_fd = sys.stderr.fileno()
    old_stderr = os.dup(stderr_fd)
    devnull = os.open(os.devnull, os.O_WRONLY)
    os.dup2(devnull, stderr_fd)
    try:
        yield
    finally:
        os.dup2(old_stderr, stderr_fd)
        os.close(old_stderr)
        os.close(devnull)


def read_with_retry(max_retries=MAX_RETRIES, delay=RETRY_DELAY):
    """リトライ付きでセンサーを読み取る"""
    for attempt in range(max_retries):
        # ライブラリ内部のエラー出力を抑制
        with suppress_stderr():
            result = mh_z19.read_all()
        
        # 結果が有効かチェック（空の辞書でないこと）
        if result and 'co2' in result:
            return result
        
        if attempt < max_retries - 1:
            print(f"    (リトライ {attempt + 1}/{max_retries - 1}...)")
            time.sleep(delay)
    
    return None


def evaluate_co2(co2):
    """CO2濃度を評価"""
    if co2 < 600:
        return "✓ 優良（新鮮な空気）"
    elif co2 < 1000:
        return "✓ 良好"
    elif co2 < 1500:
        return "⚠ 注意（換気推奨）"
    else:
        return "✗ 要換気（集中力低下の可能性）"


def main():
    args = parse_args()
    measure_count = args.count
    
    print("=" * 50)
    print("MH-Z19C CO2センサー 動作確認テスト")
    print("=" * 50)

    if args.skip_warmup:
        print("\n⚡ ウォームアップをスキップしました")
    else:
        print(f"\nウォームアップ中... ({WARMUP_TIME}秒待機)")
        print("※ MH-Z19Cは電源投入後1分で安定します")
        
        for i in range(WARMUP_TIME, 0, -10):
            print(f"  残り {i} 秒...")
            time.sleep(10)
        
        print("\n✓ ウォームアップ完了")

    print("\n" + "=" * 50)
    print(f"{measure_count}回測定を開始します...")
    print(f"（測定間隔: {MEASURE_INTERVAL}秒、リトライ: 最大{MAX_RETRIES}回）")
    print("=" * 50)

    success_count = 0
    measurements = []

    for i in range(measure_count):
        print(f"\n【{i+1}回目の測定】")
        
        # リトライ付きで読み取り
        result = read_with_retry()
        
        if result:
            co2 = result.get('co2')
            temp = result.get('temperature')
            
            print(f"  CO2濃度: {co2} ppm")
            print(f"  温度:    {temp} ℃")
            print(f"  評価:    {evaluate_co2(co2)}")
            
            success_count += 1
            measurements.append({'co2': co2, 'temp': temp})
        else:
            print("  ✗ 読み取り失敗（リトライ後も失敗）")
            print("  → 配線を確認してください")
        
        if i < measure_count - 1:  # 最後の測定後は待たない
            time.sleep(MEASURE_INTERVAL)

    print("\n" + "=" * 50)
    print("テスト完了！")
    print("=" * 50)

    # サマリー表示
    print(f"\n成功率: {success_count}/{measure_count} ({success_count/measure_count*100:.0f}%)")

    if measurements:
        avg_co2 = sum(m['co2'] for m in measurements) / len(measurements)
        avg_temp = sum(m['temp'] for m in measurements) / len(measurements)
        print(f"平均CO2濃度: {avg_co2:.0f} ppm")
        print(f"平均温度:    {avg_temp:.1f} ℃")


if __name__ == '__main__':
    main()