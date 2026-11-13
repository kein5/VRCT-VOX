"""WASAPI/PortAudio 操作 (デバイス列挙・ストリーム open/close) を直列化するプロセス共通ロック。

別スレッドから同一 WASAPI エンドポイントに対して並行にオペレーションを発行すると
PortAudio 内部で待ち合ってデッドロックすることがある (例: monitoring 側の update() で
ループバックデバイス列挙中に、transcription 側で同じデバイスの loopback stream を open すると hang)。
PortAudio の初期化と終了も同時に呼ぶとアクセス違反で落ちる (起動中のデバイス一覧の取得で実際に起きた)。
device_manager、recorder の Microphone open、Windows の音声入出力で共通に使う。
"""
from threading import Lock

pyaudio_op_lock: Lock = Lock()
