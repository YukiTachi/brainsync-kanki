#!/usr/bin/env python3
"""VEML7700 環境光センサー I2C読み取りプログラム

明るさに応じてゲインと積分時間を自動で切り替えるので、暗い室内から
直射日光下（約120,000 lx）まで測れる。
"""

import argparse
import time

import smbus2

VEML7700_ADDRESS = 0x10

# レジスタ
REG_ALS_CONF = 0x00
REG_ALS = 0x04      # 可視光（照度）
REG_WHITE = 0x05    # 白色光
REG_ID = 0x07

# ゲイン設定値 → (レジスタのビット値, 分解能計算用の倍率)
GAINS = {
    0.125: 0b10,
    0.25: 0b11,
    1.0: 0b00,
    2.0: 0b01,
}

# 積分時間(ms) → レジスタのビット値
INTEGRATION_TIMES = {
    25: 0b1100,
    50: 0b1000,
    100: 0b0000,
    200: 0b0001,
    400: 0b0010,
    800: 0b0011,
}

# 感度の低い順。自動調整はこの順にたどる。
# 室内の明るさではゲイン x1〜x2 に落ち着くようにしてある（低ゲイン側は
# 個体差で数%高めに出るため、使うのは屋外並みに明るいときだけにする）
SENSITIVITY_STEPS = [
    (0.125, 25), (0.125, 100), (0.25, 100), (1.0, 100),
    (2.0, 100), (2.0, 200), (2.0, 400), (2.0, 800),
]

# 自動調整の目標カウント範囲（16bit の上限 65535 に対して余裕を持たせる）
COUNT_LOW = 1000
COUNT_HIGH = 20000


class VEML7700:
    """VEML7700 環境光センサークラス"""

    def __init__(self, bus_number: int = 1, address: int = VEML7700_ADDRESS):
        self.bus = smbus2.SMBus(bus_number)
        self.address = address
        self.gain = 0.125
        self.integration_time = 100

    def _write_config(self, gain: float, integration_time: int, shutdown: bool = False):
        conf = (GAINS[gain] << 11) | (INTEGRATION_TIMES[integration_time] << 6) | (1 if shutdown else 0)
        previous_it = self.integration_time
        self.bus.write_word_data(self.address, REG_ALS_CONF, conf)
        self.gain = gain
        self.integration_time = integration_time
        if shutdown:
            return
        # 切り替え直後は前の設定の測定値が残っている。前後どちらの測定も
        # 終わるまで待ち、さらに1回読み捨てる（長い積分時間から短い設定へ
        # 変えたとき、1回目に古い値が返るため）
        time.sleep((previous_it + integration_time) / 1000 * 2 + 0.02)
        self.bus.read_word_data(self.address, REG_ALS)
        time.sleep(integration_time / 1000 + 0.01)

    def device_id(self) -> int:
        """デバイスIDの下位バイト（VEML7700 は 0x81）"""
        return self.bus.read_word_data(self.address, REG_ID) & 0xFF

    def init(self):
        """センサーを起動（最も感度の低い設定から始める）"""
        self._write_config(0.125, 100)

    @property
    def resolution(self) -> float:
        """現在の設定での 1カウントあたりの lx"""
        return 0.0036 * (2.0 / self.gain) * (800 / self.integration_time)

    def _read_counts(self) -> int:
        return self.bus.read_word_data(self.address, REG_ALS)

    def read(self) -> float:
        """照度を読み取り（lx）"""
        counts = self._read_counts()

        # 暗すぎる場合は感度を上げ、明るすぎる場合は下げる
        index = SENSITIVITY_STEPS.index((self.gain, self.integration_time))
        while True:
            if counts < COUNT_LOW and index < len(SENSITIVITY_STEPS) - 1:
                index += 1
            elif counts > COUNT_HIGH and index > 0:
                index -= 1
            else:
                break
            self._write_config(*SENSITIVITY_STEPS[index])
            counts = self._read_counts()

        lux = counts * self.resolution

        # 低感度（ゲイン 1/4 以下）の高照度側は出力が曲がるため、
        # データシートの補正式を当てる
        if self.gain <= 0.25 and lux > 1000:
            lux = (6.0135e-13 * lux ** 4 - 9.3924e-9 * lux ** 3
                   + 8.1488e-5 * lux ** 2 + 1.0023 * lux)

        return lux

    def read_white(self) -> float:
        """白色光チャンネルを読み取り（lx 相当）"""
        return self.bus.read_word_data(self.address, REG_WHITE) * self.resolution

    def shutdown(self):
        """省電力状態にする"""
        self._write_config(self.gain, self.integration_time, shutdown=True)

    def close(self):
        self.bus.close()

    def __enter__(self):
        self.init()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


def evaluate_lux(lux: float) -> str:
    """照度を評価"""
    if lux < 1:
        return "ほぼ暗闇"
    elif lux < 50:
        return "暗い（就寝向き）"
    elif lux < 200:
        return "やや暗い"
    elif lux < 500:
        return "✓ 室内照明として適切"
    elif lux < 1000:
        return "明るい"
    elif lux < 10000:
        return "とても明るい（窓際）"
    else:
        return "屋外並み"


def parse_args():
    parser = argparse.ArgumentParser(description="VEML7700 環境光センサー読み取り")
    parser.add_argument("-n", "--count", type=int, default=5, help="測定回数（デフォルト: 5）")
    parser.add_argument("-i", "--interval", type=float, default=2.0, help="測定間隔（秒、デフォルト: 2.0）")
    parser.add_argument("-c", "--continuous", action="store_true", help="連続測定モード（Ctrl+Cで停止）")
    return parser.parse_args()


def main():
    args = parse_args()

    print("=" * 50)
    print("VEML7700 環境光センサー")
    print("=" * 50)

    try:
        with VEML7700() as sensor:
            dev_id = sensor.device_id()
            if dev_id != 0x81:
                print(f"⚠ 予期しないデバイスID: 0x{dev_id:02X}（VEML7700 は 0x81）")
            print("✓ センサー初期化完了")
            print()

            count = 0
            try:
                while args.continuous or count < args.count:
                    count += 1
                    lux = sensor.read()
                    print(f"【測定 {count}】")
                    print(f"  照度: {lux:.1f} lx  {evaluate_lux(lux)}")
                    print(f"  設定: ゲイン x{sensor.gain}, 積分時間 {sensor.integration_time}ms")
                    print()

                    if args.continuous or count < args.count:
                        time.sleep(args.interval)
            except KeyboardInterrupt:
                print("\n中断されました")

    except OSError as e:
        print(f"✗ エラー: {e}")
        print("  センサーの接続を確認してください（I2C アドレス 0x10）")
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
