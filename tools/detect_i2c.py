#!/usr/bin/env python3
"""I2Cデバイス検出スクリプト（タイムアウト機能付き）"""

import smbus2
import signal
import sys
import argparse


# よく使われるI2Cデバイスのアドレス一覧
KNOWN_DEVICES = {
    0x20: "PCF8574 (I/O Expander)",
    0x21: "PCF8574 (I/O Expander)",
    0x22: "PCF8574 (I/O Expander)",
    0x23: "BH1750 (照度センサー)",
    0x27: "PCF8574 (LCD用I/O Expander)",
    0x38: "AHT10/AHT20 (温湿度センサー)",
    0x39: "APDS-9960 (ジェスチャーセンサー)",
    0x3C: "SSD1306 (OLEDディスプレイ)",
    0x3D: "SSD1306 (OLEDディスプレイ)",
    0x40: "INA219 (電流センサー) / HDC1080 (温湿度センサー)",
    0x44: "SHT30/SHT31 (温湿度センサー)",
    0x48: "ADS1115 (ADC) / TMP102 (温度センサー)",
    0x49: "ADS1115 (ADC)",
    0x4A: "ADS1115 (ADC)",
    0x4B: "ADS1115 (ADC)",
    0x50: "EEPROM (AT24C32等)",
    0x51: "EEPROM",
    0x53: "ADXL345 (加速度センサー)",
    0x57: "MAX30102 (心拍・SpO2センサー)",
    0x5A: "MLX90614 (非接触温度センサー) / CCS811 (空気品質センサー)",
    0x5B: "CCS811 (空気品質センサー)",
    0x68: "DS3231 (RTC) / MPU6050 (加速度・ジャイロ)",
    0x69: "MPU6050 (加速度・ジャイロ)",
    0x76: "BME280/BMP280 (温湿度・気圧センサー)",
    0x77: "BME280/BMP280 (温湿度・気圧センサー)",
}

# よく使われるアドレスのリスト（高速スキャン用）
COMMON_ADDRESSES = [
    0x20, 0x21, 0x22, 0x23, 0x27,  # I/O Expander, 照度
    0x38, 0x39, 0x3C, 0x3D,        # 温湿度, ジェスチャー, OLED
    0x40, 0x44, 0x48, 0x49, 0x4A, 0x4B,  # 電流, 温湿度, ADC
    0x50, 0x51, 0x53, 0x57,        # EEPROM, 加速度, 心拍
    0x5A, 0x5B,                    # 温度, 空気品質
    0x68, 0x69,                    # RTC, 加速度・ジャイロ
    0x76, 0x77,                    # BME280/BMP280
]


class TimeoutError(Exception):
    pass


def timeout_handler(signum, frame):
    raise TimeoutError("タイムアウト")


def check_address(bus: smbus2.SMBus, addr: int, timeout_sec: float = 0.5) -> bool:
    """
    特定のI2Cアドレスにデバイスがあるかチェック
    
    Args:
        bus: SMBusオブジェクト
        addr: チェックするアドレス
        timeout_sec: タイムアウト秒数
        
    Returns:
        デバイスが存在する場合True
    """
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.setitimer(signal.ITIMER_REAL, timeout_sec)
    
    try:
        bus.read_byte(addr)
        signal.setitimer(signal.ITIMER_REAL, 0)
        return True
    except TimeoutError:
        print(f"    警告: アドレス 0x{addr:02X} でタイムアウト", file=sys.stderr)
        return False
    except OSError:
        signal.setitimer(signal.ITIMER_REAL, 0)
        return False
    except Exception:
        signal.setitimer(signal.ITIMER_REAL, 0)
        return False


def scan_i2c_bus(bus_number: int, quick: bool = True) -> list[int]:
    """
    指定したI2Cバスをスキャンしてデバイスを検出する
    
    Args:
        bus_number: I2Cバス番号
        quick: True=よく使うアドレスのみ, False=全アドレス
        
    Returns:
        検出されたデバイスのアドレスリスト
    """
    devices = []
    
    try:
        bus = smbus2.SMBus(bus_number)
    except Exception as e:
        print(f"  エラー: バス {bus_number} を開けません - {e}")
        return devices
    
    # スキャン対象アドレス
    if quick:
        addresses = COMMON_ADDRESSES
    else:
        addresses = range(0x08, 0x78)  # 予約アドレスを避ける
    
    for addr in addresses:
        if check_address(bus, addr):
            devices.append(addr)
    
    bus.close()
    return devices


def check_specific_address(bus_number: int, address: int) -> bool:
    """
    特定のアドレスにデバイスがあるか確認
    
    Args:
        bus_number: I2Cバス番号
        address: チェックするアドレス
        
    Returns:
        デバイスが存在する場合True
    """
    try:
        bus = smbus2.SMBus(bus_number)
        result = check_address(bus, address)
        bus.close()
        return result
    except Exception as e:
        print(f"エラー: {e}")
        return False


def print_results(results: dict[int, list[int]]):
    """検出結果を表示"""
    print("=" * 55)
    print("I2Cデバイス検出結果")
    print("=" * 55)
    
    total_devices = 0
    
    for bus_num, devices in sorted(results.items()):
        print(f"\n【I2Cバス {bus_num}】(/dev/i2c-{bus_num})")
        
        if not devices:
            print("  デバイスは見つかりませんでした")
        else:
            print(f"  検出数: {len(devices)}")
            print("-" * 55)
            for addr in devices:
                device_name = KNOWN_DEVICES.get(addr, "不明なデバイス")
                print(f"  アドレス: 0x{addr:02X} ({addr:3d}) - {device_name}")
            total_devices += len(devices)
    
    print("\n" + "=" * 55)
    print(f"合計: {total_devices} 個のデバイスを検出")
    print("=" * 55)
    
    if total_devices == 0:
        print("\nヒント:")
        print("  - I2Cが有効か確認: sudo raspi-config → Interface Options → I2C")
        print("  - 配線を確認: SDA(GPIO2), SCL(GPIO3), VCC, GND")
        print("  - デバイスの電源が入っているか確認")


def parse_args():
    """コマンドライン引数をパース"""
    parser = argparse.ArgumentParser(
        description='I2Cデバイス検出ツール'
    )
    parser.add_argument(
        '-b', '--bus',
        type=int,
        default=1,
        help='スキャンするI2Cバス番号（デフォルト: 1）'
    )
    parser.add_argument(
        '-a', '--address',
        type=lambda x: int(x, 0),  # 0x表記に対応
        help='特定のアドレスのみチェック（例: 0x76）'
    )
    parser.add_argument(
        '--full',
        action='store_true',
        help='全アドレス(0x08-0x77)をスキャン（時間がかかる場合があります）'
    )
    parser.add_argument(
        '--all-buses',
        action='store_true',
        help='全てのI2Cバスをスキャン'
    )
    return parser.parse_args()


def main():
    args = parse_args()
    
    # 特定のアドレスのみチェック
    if args.address is not None:
        print(f"\nI2Cバス {args.bus} のアドレス 0x{args.address:02X} をチェック中...")
        if check_specific_address(args.bus, args.address):
            device_name = KNOWN_DEVICES.get(args.address, "不明なデバイス")
            print(f"✓ デバイスが見つかりました: 0x{args.address:02X} - {device_name}")
        else:
            print(f"✗ アドレス 0x{args.address:02X} にデバイスは見つかりませんでした")
        return
    
    print("\nI2Cデバイスをスキャン中...")
    if not args.full:
        print("(高速モード: よく使われるアドレスのみチェック)")
        print("(全アドレスをスキャンするには --full オプションを使用)")
    print()
    
    results = {}
    
    if args.all_buses:
        # 全バスをスキャン
        for bus_num in [0, 1, 2, 10, 11]:
            try:
                with open(f"/dev/i2c-{bus_num}", "r"):
                    pass
                print(f"バス {bus_num} をスキャン中...")
                devices = scan_i2c_bus(bus_num, quick=not args.full)
                results[bus_num] = devices
            except FileNotFoundError:
                pass
            except PermissionError:
                print(f"  警告: /dev/i2c-{bus_num} へのアクセス権限がありません")
    else:
        # 指定バスのみ
        print(f"バス {args.bus} をスキャン中...")
        results[args.bus] = scan_i2c_bus(args.bus, quick=not args.full)
    
    print_results(results)


if __name__ == "__main__":
    main()
