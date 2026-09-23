#!/usr/bin/env python3
"""DHT20/AHT20 温湿度センサー I2C読み取りプログラム"""

import smbus2
import time
import argparse


# DHT20/AHT20 I2Cアドレス
DHT20_ADDRESS = 0x38

# コマンド
CMD_INIT = [0xBE, 0x08, 0x00]  # 初期化
CMD_TRIGGER = [0xAC, 0x33, 0x00]  # 測定トリガー
CMD_SOFT_RESET = 0xBA  # ソフトリセット


class DHT20:
    """DHT20/AHT20 温湿度センサークラス"""
    
    def __init__(self, bus_number: int = 1, address: int = DHT20_ADDRESS):
        """
        初期化
        
        Args:
            bus_number: I2Cバス番号
            address: I2Cアドレス
        """
        self.bus = smbus2.SMBus(bus_number)
        self.address = address
        self._initialized = False
    
    def _check_status(self) -> bool:
        """
        センサーのステータスをチェック
        
        Returns:
            キャリブレーション済みならTrue
        """
        status = self.bus.read_byte(self.address)
        # ビット3がキャリブレーション済みフラグ
        return (status & 0x08) == 0x08
    
    def init(self):
        """センサーを初期化"""
        # 電源投入後の待機
        time.sleep(0.1)
        
        # ステータス確認
        if not self._check_status():
            # 初期化コマンド送信
            self.bus.write_i2c_block_data(self.address, CMD_INIT[0], CMD_INIT[1:])
            time.sleep(0.01)
        
        self._initialized = True
    
    def reset(self):
        """ソフトリセット"""
        self.bus.write_byte(self.address, CMD_SOFT_RESET)
        time.sleep(0.02)
        self._initialized = False
    
    def read(self) -> tuple[float, float]:
        """
        温度と湿度を読み取り
        
        Returns:
            (温度℃, 湿度%) のタプル
            
        Raises:
            RuntimeError: 読み取り失敗時
        """
        if not self._initialized:
            self.init()
        
        # 測定トリガー送信
        self.bus.write_i2c_block_data(self.address, CMD_TRIGGER[0], CMD_TRIGGER[1:])
        
        # 測定完了待ち（80ms以上）
        time.sleep(0.08)
        
        # ビジーフラグが解除されるまで待機（i2c_msgで読み取り）
        for _ in range(20):
            msg = smbus2.i2c_msg.read(self.address, 1)
            self.bus.i2c_rdwr(msg)
            status = list(msg)[0]
            if (status & 0x80) == 0:  # ビジーフラグ解除
                break
            time.sleep(0.01)
        else:
            raise RuntimeError("センサーがビジー状態のままです")
        
        # 7バイト読み取り（i2c_msgで直接読み取り）
        msg = smbus2.i2c_msg.read(self.address, 7)
        self.bus.i2c_rdwr(msg)
        data = list(msg)
        
        # データデコード
        # 湿度: バイト1、バイト2、バイト3の上位4ビット（20ビット）
        humidity_raw = ((data[1] << 16) | (data[2] << 8) | data[3]) >> 4
        humidity = (humidity_raw / 1048576.0) * 100.0
        
        # 温度: バイト3の下位4ビット、バイト4、バイト5（20ビット）
        temp_raw = ((data[3] & 0x0F) << 16) | (data[4] << 8) | data[5]
        temperature = (temp_raw / 1048576.0) * 200.0 - 50.0
        
        return temperature, humidity
    
    def close(self):
        """バスを閉じる"""
        self.bus.close()
    
    def __enter__(self):
        self.init()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


def evaluate_humidity(humidity: float) -> str:
    """湿度を評価"""
    if humidity < 30:
        return "⚠ 乾燥（加湿推奨）"
    elif humidity < 40:
        return "やや乾燥"
    elif humidity < 60:
        return "✓ 快適"
    elif humidity < 70:
        return "やや多湿"
    else:
        return "⚠ 多湿（除湿推奨）"


def evaluate_temperature(temp: float) -> str:
    """温度を評価"""
    if temp < 18:
        return "寒い"
    elif temp < 22:
        return "やや涼しい"
    elif temp < 26:
        return "✓ 快適"
    elif temp < 28:
        return "やや暑い"
    else:
        return "⚠ 暑い"


def parse_args():
    """コマンドライン引数をパース"""
    parser = argparse.ArgumentParser(
        description='DHT20/AHT20 温湿度センサー読み取り'
    )
    parser.add_argument(
        '-n', '--count',
        type=int,
        default=5,
        help='測定回数（デフォルト: 5）'
    )
    parser.add_argument(
        '-i', '--interval',
        type=float,
        default=2.0,
        help='測定間隔（秒、デフォルト: 2.0）'
    )
    parser.add_argument(
        '-c', '--continuous',
        action='store_true',
        help='連続測定モード（Ctrl+Cで停止）'
    )
    return parser.parse_args()


def main():
    args = parse_args()
    
    print("=" * 50)
    print("DHT20/AHT20 温湿度センサー")
    print("=" * 50)
    
    try:
        with DHT20() as sensor:
            print("✓ センサー初期化完了")
            print()
            
            count = 0
            measurements = []
            
            try:
                while args.continuous or count < args.count:
                    count += 1
                    
                    try:
                        temp, humidity = sensor.read()
                        
                        print(f"【測定 {count}】")
                        print(f"  温度:   {temp:.1f} ℃  {evaluate_temperature(temp)}")
                        print(f"  湿度:   {humidity:.1f} %  {evaluate_humidity(humidity)}")
                        print()
                        
                        measurements.append({'temp': temp, 'humidity': humidity})
                        
                    except RuntimeError as e:
                        print(f"  ✗ 読み取りエラー: {e}")
                    
                    if args.continuous or count < args.count:
                        time.sleep(args.interval)
                        
            except KeyboardInterrupt:
                print("\n中断されました")
            
            # サマリー表示
            if measurements:
                print("=" * 50)
                print("測定サマリー")
                print("=" * 50)
                avg_temp = sum(m['temp'] for m in measurements) / len(measurements)
                avg_humidity = sum(m['humidity'] for m in measurements) / len(measurements)
                print(f"測定回数: {len(measurements)}")
                print(f"平均温度: {avg_temp:.1f} ℃")
                print(f"平均湿度: {avg_humidity:.1f} %")
                
    except Exception as e:
        print(f"✗ エラー: {e}")
        print("  センサーの接続を確認してください")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
