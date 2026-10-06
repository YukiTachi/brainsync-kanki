#!/usr/bin/env python3
"""MPL115A1 気圧センサー SPI読み取りプログラム

Freescale/NXP MPL115A1（50〜115 kPa）。工場出荷時の校正係数が内蔵されており、
それを読み出して気圧を補正計算する。

参考: MPL115A1 データシート Rev 4、アプリケーションノート AN3785
"""

import argparse
import time

import spidev

# SPI コマンド（レジスタアドレス << 1、読み出しは最上位ビットを立てる）
CMD_CONVERT = 0x24      # 気圧と温度の変換開始（書き込み）
CMD_PADC_MSB = 0x80
CMD_PADC_LSB = 0x82
CMD_TADC_MSB = 0x84
CMD_TADC_LSB = 0x86
CMD_COEFF_A0 = 0x88     # 以降 0x8A, 0x8C, ... と2つ飛びで係数が並ぶ

CONVERSION_TIME = 0.005  # 変換待ち（データシートの最大値 1ms に余裕を持たせる）

# 温度 ADC の基準（データシート: 25℃ で 472 カウント、-5.35 カウント/℃）
TADC_AT_25C = 472.0
TADC_PER_DEGREE = -5.35


def _to_signed16(value: int) -> int:
    return value - 65536 if value & 0x8000 else value


class MPL115A1:
    """MPL115A1 気圧センサークラス"""

    def __init__(self, bus: int = 0, device: int = 0, speed_hz: int = 1_000_000):
        self.spi = spidev.SpiDev()
        self.spi.open(bus, device)
        self.spi.max_speed_hz = speed_hz   # データシート上の上限は 8MHz
        self.spi.mode = 0b00               # データは立ち下がりで変化し立ち上がりで確定（モード0）
        self.a0 = self.b1 = self.b2 = self.c12 = None

    def _read_byte(self, command: int) -> int:
        """コマンドを送り、続く1バイトを受け取る"""
        return self.spi.xfer2([command, 0x00])[1]

    def _read_word(self, command_msb: int) -> int:
        return (self._read_byte(command_msb) << 8) | self._read_byte(command_msb + 2)

    def read_coefficients(self):
        """内蔵の校正係数を読み出す（固定小数点なので実数に直す）"""
        raw = [self._read_word(CMD_COEFF_A0 + i * 4) for i in range(4)]
        a0, b1, b2, c12 = (_to_signed16(v) for v in raw)
        # 小数部のビット数: a0=3, b1=13, b2=14, c12=13（+9ビットのゼロ詰め、下位2ビットは未使用）
        self.a0 = a0 / 8.0
        self.b1 = b1 / 8192.0
        self.b2 = b2 / 16384.0
        self.c12 = (c12 >> 2) / 4194304.0

    def init(self):
        self.read_coefficients()

    def read_raw(self) -> tuple[int, int]:
        """変換を開始し、気圧と温度の生の ADC 値（10bit）を返す"""
        self.spi.xfer2([CMD_CONVERT, 0x00])
        time.sleep(CONVERSION_TIME)
        # 10bit のデータが上位詰めで入っているので 6ビット右へ寄せる
        padc = self._read_word(CMD_PADC_MSB) >> 6
        tadc = self._read_word(CMD_TADC_MSB) >> 6
        return padc, tadc

    def read(self) -> tuple[float, float]:
        """
        気圧と温度を読み取り

        Returns:
            (気圧 hPa, 温度℃) のタプル
        """
        if self.a0 is None:
            self.read_coefficients()

        padc, tadc = self.read_raw()

        # Pcomp = a0 + (b1 + c12 * Tadc) * Padc + b2 * Tadc
        # Pcomp は 0 が 50 kPa、1023 が 115 kPa に対応する
        pcomp = self.a0 + (self.b1 + self.c12 * tadc) * padc + self.b2 * tadc
        kpa = pcomp * ((115.0 - 50.0) / 1023.0) + 50.0
        temperature = 25.0 + (tadc - TADC_AT_25C) / TADC_PER_DEGREE

        return kpa * 10.0, temperature  # hPa に直して返す

    def close(self):
        self.spi.close()

    def __enter__(self):
        self.init()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


def sea_level_pressure(pressure_hpa: float, altitude_m: float, temperature_c: float) -> float:
    """標高を考慮した海面更正気圧（天気予報で使われる値に合わせるため）"""
    return pressure_hpa * (1 - 0.0065 * altitude_m / (temperature_c + 0.0065 * altitude_m + 273.15)) ** -5.257


def evaluate_pressure(hpa: float) -> str:
    """気圧を評価（海面更正値を前提とした一般的な目安）"""
    if hpa < 980:
        return "⚠ 非常に低い（荒天）"
    elif hpa < 1000:
        return "低い（雨になりやすい）"
    elif hpa < 1013:
        return "やや低い"
    elif hpa < 1023:
        return "✓ 標準"
    else:
        return "高い（晴れになりやすい）"


def parse_args():
    parser = argparse.ArgumentParser(description="MPL115A1 気圧センサー読み取り")
    parser.add_argument("-n", "--count", type=int, default=5, help="測定回数（デフォルト: 5）")
    parser.add_argument("-i", "--interval", type=float, default=2.0, help="測定間隔（秒、デフォルト: 2.0）")
    parser.add_argument("-c", "--continuous", action="store_true", help="連続測定モード（Ctrl+Cで停止）")
    parser.add_argument("-a", "--altitude", type=float, help="設置場所の標高(m)。指定すると海面更正値も表示する")
    return parser.parse_args()


def main():
    args = parse_args()

    print("=" * 50)
    print("MPL115A1 気圧センサー")
    print("=" * 50)

    try:
        with MPL115A1() as sensor:
            print("✓ センサー初期化完了")
            print(f"  校正係数: a0={sensor.a0:.4f} b1={sensor.b1:.6f} "
                  f"b2={sensor.b2:.6f} c12={sensor.c12:.9f}")
            print()

            count = 0
            try:
                while args.continuous or count < args.count:
                    count += 1
                    hpa, temp = sensor.read()
                    print(f"【測定 {count}】")
                    print(f"  気圧: {hpa:.1f} hPa")
                    if args.altitude is not None:
                        sea = sea_level_pressure(hpa, args.altitude, temp)
                        print(f"  海面更正: {sea:.1f} hPa  {evaluate_pressure(sea)}")
                    print(f"  温度: {temp:.1f} ℃（センサー内蔵・参考値）")
                    print()

                    if args.continuous or count < args.count:
                        time.sleep(args.interval)
            except KeyboardInterrupt:
                print("\n中断されました")

    except (OSError, FileNotFoundError) as e:
        print(f"✗ エラー: {e}")
        print("  SPI が有効か（/dev/spidev0.0）、配線が正しいか確認してください")
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
