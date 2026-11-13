"""応答が止まったときに、全スレッドのスタックを freeze_trace.log へ書き出す。

フロントエンドからの feed が期限までに来なければ、その時点のスタックを書く (プロセスは落とさない)。

以前は faulthandler.dump_traceback_later() だけで書いていた。この関数は C のスレッドが GIL を
持たずに各スレッドのフレームをたどる。固まってはいないのに feed だけが遅れたとき (ログの
ロック待ちで 35 秒遅れた例がある) は、ほかのスレッドが動いている最中のフレームを読むことになり、
プロセスごとアクセス違反で落ちることがある。CI では、タイマーを残したテストの 35 秒後に、
およそ 10 回に 1 回落ちていた (ネイティブのスタックは _Py_DumpTracebackThreads の中)。

そのため 2 段にする。

1. 期限が来たら、Python のスレッドが GIL を持ったまま書く。ほかのスレッドはその間フレームを
   書き換えられないので、動いている最中でも安全に読める。
2. GIL そのものが返ってこない固まり方 (C の呼び出しが GIL を持ったまま止まる) では、1 の
   スレッドも動けない。そのときだけ、さらに STALL_MARGIN_SEC 待ってから従来の C のスレッドが書く。
   1 が動けたなら GIL は生きているので、1 がこのタイマーを解除する。
"""
import faulthandler
import os
import threading
import time
from typing import Optional

# 1 のスレッドが GIL を取って書き終えるまでの猶予。これを過ぎても解除されなければ、GIL が
# 止まっているとみなす。
STALL_MARGIN_SEC = 30.0


class FreezeDump:
    def __init__(self, file, *, stall_margin: float = STALL_MARGIN_SEC, clock=time.monotonic) -> None:
        self._file = file
        self._stall_margin = stall_margin
        self._clock = clock
        self._changed = threading.Condition()
        self._deadline: Optional[float] = None
        self._timeout = 0.0
        self._thread: Optional[threading.Thread] = None

    def arm(self, timeout: float) -> None:
        """いまから timeout 秒のうちに arm() も cancel() も呼ばれなければ、スタックを書く。"""
        deadline = self._clock() + timeout
        with self._changed:
            earlier = self._deadline is None or deadline < self._deadline
            self._deadline = deadline
            self._timeout = timeout
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name="FreezeDump", daemon=True)
                self._thread.start()
            elif earlier:
                # 期限が延びただけなら起こさない。前の期限で起きたときに、新しい期限まで待ち直す。
                self._changed.notify()
            # 2 段目。呼ぶたびに前のタイマーを置き換える (faulthandler の仕様)。ロックの中で呼ぶのは、
            # 期限切れを処理中のスレッドが、ここで掛けた新しいタイマーを解除しないようにするため。
            faulthandler.dump_traceback_later(timeout + self._stall_margin, repeat=False, file=self._file, exit=False)

    def cancel(self) -> None:
        with self._changed:
            self._deadline = None
            faulthandler.cancel_dump_traceback_later()

    def _run(self) -> None:
        while True:
            with self._changed:
                while True:
                    if self._deadline is None:
                        self._changed.wait()
                        continue
                    remaining = self._deadline - self._clock()
                    if remaining <= 0:
                        break
                    self._changed.wait(remaining)
                self._deadline = None
                timeout = self._timeout
                # ここまで来られたなら GIL は生きている。GIL を持たない 2 段目は要らない。
                faulthandler.cancel_dump_traceback_later()
            self._write(timeout)

    def _write(self, timeout: float) -> None:
        try:
            # faulthandler と同じく fd へ直接書く (file のバッファーと順序が入れ替わらないように)。
            self._file.flush()
            os.write(self._file.fileno(), f"Timeout ({timeout:.0f}s without a feed)!\n".encode("ascii"))
            faulthandler.dump_traceback(file=self._file, all_threads=True)
        except Exception:
            pass  # 閉じたファイルなど。診断のための処理でアプリを止めない
