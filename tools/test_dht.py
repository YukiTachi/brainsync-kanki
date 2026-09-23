#!/usr/bin/env python3
import board
import adafruit_dht
import time
import argparse

# 設定
MEASURE_COUNT = 5     # 測定回数
MEASURE_INTERVAL = 2  # 測定間隔（秒）
MAX_RETRIES = 3       # リトライ回数
RETRY_DELAY = 1       # リトライ間隔（秒）

# デフォルトGPIOピン（BCM番号）
DEFAULT_PIN = 4


def parse_args():
    """コマンドライン引数をパース"""
    parser = argparse.ArgumentParser(
        description='DHT22/DHT11 温湿度センサー動作確認テスト'
    )
    parser.add_argument(
        '-n', '--count',
        type=int,
        default=MEASURE_COUNT,
        help=f'測定回数（デフォルト: {MEASURE_COUNT}）'
    )
    parser.add_argument(
        '-p', '--pin',
        type=int,
        default=DEFAULT_PIN,
        help=f'GPIOピン番号（BCM、デフォルト: {DEFAULT_PIN}）'
    )
    parser.add_argument(
        '-t', '--type',
        choices=['DHT22', 'DHT11'],
        default='DHT22',
        help='センサータイプ（デフォルト: DHT22）'
    )
    return parser.parse_args()


def get_board_pin(pin_number):
    """GPIOピン番号からboardピンオブジェクトを取得"""
    pin_map = {
        4: board.D4,
        17: board.D17,
        18: board.D18,
        22: board.D22,
        23: board.D23,
        24: board.D24,
        25: board.D25,
        27: board.D27,
    }
    if pin_number in pin_map:
        return pin_map[pin_number]
    else:
        # 動的にピンを取得
        return getattr(board, f'D{pin_number}', None)


def evaluate_humidity(humidity):
    """湿度を評価"""
    if humidity < 30:
        return "⚠ 乾燥（加湿推奨）"
    elif humidity < 40:
        return "✓ やや乾燥"
    elif humidity <= 60:
        return "✓ 快適"
    elif humidity <= 70:
        return "✓ やや多湿"
    else:
        return "⚠ 多湿（除湿推奨）"


def evaluate_temperature(temp):
    """温度を評価"""
    if temp < 18:
        return "❄ 寒い"
    elif temp < 22:
        return "✓ やや涼しい"
    elif temp <= 26:
        return "✓ 快適"
    elif temp <= 28:
        return "✓ やや暑い"
    else:
        return "🔥 暑い"


def read_with_retry(dht, max_retries=MAX_RETRIES, delay=RETRY_DELAY):
    """リトライ付きでセンサーを読み取る"""
    for attempt in range(max_retries):
        try:
            temperature = dht.temperature
            humidity = dht.humidity
            
            if temperature is not None and humidity is not None:
                return {'temperature': temperature, 'humidity': humidity}
        except RuntimeError as e:
            if attempt < max_retries - 1:
                print(f"    (リトライ {attempt + 1}/{max_retries - 1}...)")
                time.sleep(delay)
        except Exception as e:
            print(f"    エラー: {e}")
            break
    
    return None


def main():
    args = parse_args()
    measure_count = args.count
    pin_number = args.pin
    sensor_type = args.type
    
    print("=" * 50)
    print(f"{sensor_type} 温湿度センサー 動作確認テスト")
    print("=" * 50)
    
    # ピンを取得
    board_pin = get_board_pin(pin_number)
    if board_pin is None:
        print(f"\n✗ エラー: GPIO{pin_number}は無効なピンです")
        return
    
    print(f"\nセンサー設定:")
    print(f"  タイプ: {sensor_type}")
    print(f"  GPIOピン: {pin_number}")
    
    # DHTセンサーを初期化
    try:
        if sensor_type == 'DHT22':
            dht = adafruit_dht.DHT22(board_pin)
        else:
            dht = adafruit_dht.DHT11(board_pin)
    except Exception as e:
        print(f"\n✗ センサー初期化エラー: {e}")
        return
    
    print("\n" + "=" * 50)
    print(f"{measure_count}回測定を開始します...")
    print(f"（測定間隔: {MEASURE_INTERVAL}秒、リトライ: 最大{MAX_RETRIES}回）")
    print("=" * 50)

    success_count = 0
    measurements = []

    try:
        for i in range(measure_count):
            print(f"\n【{i+1}回目の測定】")
            
            # リトライ付きで読み取り
            result = read_with_retry(dht)
            
            if result:
                temp = result['temperature']
                humidity = result['humidity']
                
                print(f"  温度:   {temp:.1f} ℃  {evaluate_temperature(temp)}")
                print(f"  湿度:   {humidity:.1f} %  {evaluate_humidity(humidity)}")
                
                success_count += 1
                measurements.append(result)
            else:
                print("  ✗ 読み取り失敗（リトライ後も失敗）")
                print("  → 配線を確認してください")
            
            if i < measure_count - 1:  # 最後の測定後は待たない
                time.sleep(MEASURE_INTERVAL)
    finally:
        dht.exit()

    print("\n" + "=" * 50)
    print("テスト完了！")
    print("=" * 50)

    # サマリー表示
    print(f"\n成功率: {success_count}/{measure_count} ({success_count/measure_count*100:.0f}%)")

    if measurements:
        avg_temp = sum(m['temperature'] for m in measurements) / len(measurements)
        avg_humidity = sum(m['humidity'] for m in measurements) / len(measurements)
        print(f"平均温度: {avg_temp:.1f} ℃")
        print(f"平均湿度: {avg_humidity:.1f} %")


if __name__ == '__main__':
    main()
