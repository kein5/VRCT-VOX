import asyncio
import hmac
import threading
from dataclasses import dataclass, field
from time import monotonic
from http import HTTPStatus
from urllib.parse import urlparse, parse_qs
import websockets
from websockets.asyncio.server import ServerConnection, broadcast
from typing import Callable, Set, Optional
from utils import errorLogging

_STOP_JOIN_TIMEOUT = 2.0
# The server only pushes messages; what clients send is ignored. Accept small
# frames only (OWASP suggests 64 KB or less) instead of the 1 MiB default.
_MAX_INCOMING_MESSAGE_SIZE = 64 * 1024


@dataclass
class _ServerRun:
    """Resources belong to one start attempt, including after a bounded join expires."""
    deadline: float
    ready: threading.Event = field(default_factory=threading.Event)
    cancelled: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)
    thread: Optional[threading.Thread] = None
    loop: Optional[asyncio.AbstractEventLoop] = None
    task: Optional[asyncio.Task] = None
    server: Optional[object] = None
    send_queue: Optional[asyncio.Queue] = None
    running: bool = False
    error: Optional[BaseException] = None


class WebSocketServer:
    """
    WebSocketサーバーを管理するクラス。
    主な機能:
    - サーバーの起動・停止
    - クライアント接続管理 (接続/切断の追跡)
    - メッセージ受信のコールバック処理
    - メッセージのブロードキャスト機能
    - GUIスレッド等からメッセージ送信するためのキュー

    セキュリティ: WebSocket は同一オリジンポリシーの対象外であるため、
    127.0.0.1 バインドだけでは「同じ PC 上で開いた任意の Web ページの JS が
    ws://127.0.0.1:PORT に直接接続してマイク/スピーカーの文字起こしを
    盗聴できる」という問題を防げない。token を要求することで、この
    トークンを渡されていないクライアント (= VRCT 自身が生成した
    OBS Browser Source ページ以外) を拒否する。
    """
    def __init__(self, host: str='127.0.0.1', port: int=8765, token: Optional[str] = None):
        """
        サーバーのホスト名とポートを指定して初期化します。

        token を指定すると、接続 URL のクエリパラメータ (?token=...) が
        一致しないクライアントの WebSocket ハンドシェイクを拒否する。
        None (デフォルト) の場合は検証を行わない (テスト・後方互換用)。
        """
        self.host = host
        self.port = port
        self.token = token
        self.clients: Set[ServerConnection] = set()  # 接続クライアント集合
        self._message_handler: Optional[Callable[['WebSocketServer', ServerConnection, str], None]] = None
        self._lifecycle_lock = threading.Lock()
        self._run: Optional[_ServerRun] = None

    @property
    def is_running(self) -> bool:
        run = self._run
        return run is not None and run.running and not run.cancelled.is_set()

    @property
    def is_stopped(self) -> bool:
        run = self._run
        return run is None or run.thread is None or not run.thread.is_alive()

    async def _process_request(self, connection: ServerConnection, request):
        """websockets の asyncio serve() が接続確立前に呼ぶフック。

        token が設定されている場合、クエリパラメータ ?token=... が一致
        しなければ WebSocket ハンドシェイクへ進める前に 403 で拒否する。
        None を返すと通常どおりハンドシェイクを継続する。

        新しい asyncio 実装の process_request は (connection, request) を
        受け取り、拒否する場合は connection.respond() で生成した Response を
        返す必要がある (legacy の (status, headers, body) タプルは不可)。
        """
        if self.token is None:
            return None
        try:
            query = parse_qs(urlparse(request.path).query)
        except Exception:
            query = {}
        supplied = query.get("token", [None])[0]
        if not isinstance(supplied, str) or not hmac.compare_digest(supplied.encode(), self.token.encode()):
            return connection.respond(
                HTTPStatus.FORBIDDEN, "Forbidden: invalid or missing token\n"
            )
        return None

    def set_message_handler(self, handler: Callable[['WebSocketServer', ServerConnection, str], None]):
        """
        クライアントからメッセージ受信時に呼び出すコールバックを設定します。
        コールバックのシグネチャ: (server, websocket, message) -> None
        """
        self._message_handler = handler

    async def _handler(self, websocket):
        """
        単一クライアントとのセッションを処理するハンドラです。
        新規接続時にクライアントを集合に追加し、メッセージを受信してコールバックを呼び出します。
        切断時には集合からクライアントを削除します。
        """
        # 接続クライアントを集合に追加
        self.clients.add(websocket)
        try:
            async for message in websocket:
                # メッセージ受信時にコールバック呼び出し
                if self._message_handler:
                    await asyncio.to_thread(
                        self._dispatch_message, self._message_handler, websocket, message
                    )
        except websockets.exceptions.ConnectionClosed:
            # クライアントが切断した場合
            pass
        finally:
            # 切断時に集合から削除(既に削除済みでも例外にならないようdiscardを使用)
            self.clients.discard(websocket)

    def _dispatch_message(self, handler, websocket, message):
        # Callbacks can enter Model locks or perform I/O. Keep exception logging
        # on the same worker too, so errorLogging retains the actual traceback.
        try:
            handler(self, websocket, message)
        except Exception:
            errorLogging()

    async def _broadcast_async(self, message: str):
        """
        すべての接続クライアントにメッセージを送信する非同期メソッド。
        """
        # 全員に届くまで待つと、いちばん遅いクライアントが時間切れになるまで
        # 後続のメッセージも全員分止まる。websockets の broadcast() は待たずに
        # 各接続の書き込みバッファへ積み、遅い接続は keepalive の時間切れで切れる
        clients = tuple(self.clients)
        for offset in range(0, len(clients), 32):
            # Fanout is synchronous too. Bound each turn while preserving the
            # library's nonblocking writes and slow-client keepalive policy.
            broadcast(clients[offset:offset + 32], message)
            await asyncio.sleep(0)

    async def _send_loop(self, run):
        while True:
            message = await run.send_queue.get()
            await self._broadcast_async(message)
            # Queue.get() and broadcast() need not suspend while producers keep
            # the queue full. Let keepalive, receive and stop callbacks run.
            await asyncio.sleep(0)

    def send(self, message: str):
        run = self._run
        if run is not None and self.is_running:
            try:
                run.loop.call_soon_threadsafe(run.send_queue.put_nowait, message)
            except RuntimeError:
                # A concurrent stop may already have closed this attempt's loop.
                pass

    def broadcast(self, message: str):
        run = self._run
        if run is not None and self.is_running:
            coroutine = self._broadcast_async(message)
            try:
                asyncio.run_coroutine_threadsafe(coroutine, run.loop)
            except RuntimeError:
                coroutine.close()

    def begin_start(self, timeout: float = 5.0):
        """Publish and launch an attempt without waiting (so stop can cancel it)."""
        with self._lifecycle_lock:
            if not self.is_stopped:
                if self._run.cancelled.is_set():
                    raise RuntimeError("WebSocket server is still stopping")
                return self._run
            run = _ServerRun(deadline=monotonic() + timeout)
            self._run = run
            run.thread = threading.Thread(
                target=self._run_loop, args=(run,), daemon=True,
                name="websocket_server",
            )
            run.thread.start()
            return run

    def wait_started(self, run):
        """Wait for this exact attempt, never a subsequent start's result."""
        if not run.ready.wait(max(0.0, run.deadline - monotonic())):
            self._stop_run(run)
            raise TimeoutError("WebSocket server startup timed out")
        if run.error is not None:
            self._stop_run(run)
            raise run.error
        if run.cancelled.is_set() or not run.running:
            self._stop_run(run)
            raise RuntimeError("WebSocket server startup was cancelled")

    def start(self, timeout: float = 5.0):
        self.wait_started(self.begin_start(timeout))

    async def _serve(self, run):
        # Bind without listening. Even an uncooperative/late serve result must
        # pass the cancellation and deadline checks before accepting clients.
        run.server = await websockets.serve(
            self._handler, self.host, self.port,
            process_request=self._process_request, start_serving=False,
            max_size=_MAX_INCOMING_MESSAGE_SIZE,
        )
        if run.cancelled.is_set() or monotonic() >= run.deadline:
            raise TimeoutError("WebSocket server startup timed out")
        await run.server.start_serving()
        with run.lock:
            if run.cancelled.is_set() or monotonic() >= run.deadline:
                raise TimeoutError("WebSocket server startup timed out")
            run.send_queue = asyncio.Queue()
            run.running = True
            run.ready.set()
        await self._send_loop(run)

    def _run_loop(self, run):
        # Only this thread creates, drains and closes the loop and its resources.
        # stop() cancels the task; loop.stop() during run_until_complete would
        # abandon a pending bind and leak its eventual result.
        try:
            loop = asyncio.new_event_loop()
            with run.lock:
                run.loop = loop
                asyncio.set_event_loop(loop)
                if run.cancelled.is_set():
                    return
                run.task = loop.create_task(self._serve(run))
            loop.run_until_complete(run.task)
        except asyncio.CancelledError:
            pass
        except BaseException as exc:
            run.error = exc
        finally:
            run.running = False
            loop = run.loop
            try:
                if loop is not None:
                    try:
                        if run.server is not None:
                            run.server.close()
                            loop.run_until_complete(run.server.wait_closed())
                    finally:
                        pending = asyncio.all_tasks(loop)
                        for task in pending:
                            task.cancel()
                        if pending:
                            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                        try:
                            loop.run_until_complete(loop.shutdown_asyncgens())
                        finally:
                            loop.close()
            except Exception:
                errorLogging()
            finally:
                run.ready.set()

    @staticmethod
    def _stop_run(run):
        with run.lock:
            first_cancel = not run.cancelled.is_set()
            run.cancelled.set()
            run.running = False
            run.ready.set()
            if first_cancel and run.loop is not None and not run.loop.is_closed():
                def cancel():
                    if run.task is not None and not run.task.done():
                        run.task.cancel()
                try:
                    run.loop.call_soon_threadsafe(cancel)
                except RuntimeError:
                    pass  # The owner finished closing the loop concurrently.
        if (run.thread is not None and run.thread.ident is not None
                and run.thread is not threading.current_thread()):
            run.thread.join(timeout=_STOP_JOIN_TIMEOUT)

    def stop(self):
        with self._lifecycle_lock:
            run = self._run
            if run is not None:
                self._stop_run(run)

if __name__ == "__main__":
    # テスト用の簡単なメッセージハンドラ
    def message_handler(server: WebSocketServer, websocket: ServerConnection, message: str):
        print(f"Received message from {websocket.remote_address}: {message}")
        server.send(f"Echo: {message}")

    def send_message(server: WebSocketServer, message: str):
        server.send(message)

    # メイン処理を非同期関数に変更
    async def main():
        # サーバーを起動してメッセージハンドラを設定
        ws_server = WebSocketServer()
        ws_server.set_message_handler(message_handler)
        await asyncio.to_thread(ws_server.start)
        await asyncio.to_thread(print, "WebSocket server started.")
        # 定期的にサーバーからメッセージを送信する例
        import threading
        import time
        def periodic_send():
            print("Starting periodic message sender...")
            while ws_server.is_running:
                time.sleep(5)
                print("Sending periodic message...")
                send_message(ws_server, "Periodic message")
            print("Periodic message sender stopped.")
        # 別スレッドで定期的にメッセージを送信
        await asyncio.sleep(5)
        send_thread = threading.Thread(target=periodic_send, daemon=True)
        send_thread.start()
        # メインスレッドでサーバーを動かし続ける
        try:
            while True:
                # 非同期スリープで待機
                await asyncio.sleep(1)

        except KeyboardInterrupt:
            # Ctrl+Cでサーバーを停止
            await asyncio.to_thread(print, "Stopping WebSocket server...")
            await asyncio.to_thread(ws_server.stop)

    # 非同期メイン関数を実行
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Stopping WebSocket server...")