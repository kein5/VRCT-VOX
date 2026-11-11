"""Linux の VR画面の受け渡し: Tauri が書く画像ファイルを読み、ポインタの操作をソケットへ送る。

Tauri 側 (src-tauri/src/vr_panel_surface.rs) の代わりに、同じ形式のファイルとソケットを試験が用意する。
"""
import socket
import struct
import sys

import numpy as np
import pytest

from models.overlay import window_capture_linux as capture

pytestmark = pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="Unix sockets")

HEADER = struct.Struct("<8sQQIII")


def write_frame(folder, *, sequence=2, instance=7, width=4, height=2, stride=None, pixels=None, magic=b"VRCTVRP1"):
    stride = width * 4 if stride is None else stride
    if pixels is None:
        pixels = bytes(range(256))[: stride * height]
    head = HEADER.pack(magic, sequence, instance, width, height, stride).ljust(64, b"\0")
    (folder / "frame").write_bytes(head + pixels)
    return pixels


@pytest.fixture
def panel(tmp_path, monkeypatch):
    monkeypatch.setenv(capture.DIRECTORY_ENV, str(tmp_path))
    monkeypatch.setattr(capture, "_cache", None)
    monkeypatch.setattr(capture, "_expected", {})
    monkeypatch.setattr(capture, "_sender", None)
    return tmp_path


@pytest.fixture
def commands(panel):
    """The socket the Tauri side listens on; returns what was sent so far."""
    receiver = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    receiver.bind(str(panel / "input.sock"))
    receiver.setblocking(False)

    def received():
        rows = []
        while True:
            try:
                rows.append(receiver.recv(128).decode("ascii"))
            except BlockingIOError:
                return rows

    yield received
    receiver.close()


def test_without_a_place_from_tauri_the_vr_page_is_unavailable(tmp_path, monkeypatch):
    monkeypatch.delenv(capture.DIRECTORY_ENV, raising=False)
    assert capture.available() is False
    assert capture.findWindow() is None
    assert capture.captureWindowRaw(7) is None
    capture.mouseMove(7, 1, 2)  # 送り先が無くても落ちない
    monkeypatch.setenv(capture.DIRECTORY_ENV, str(tmp_path / "missing"))
    assert capture.available() is False
    monkeypatch.setenv(capture.DIRECTORY_ENV, str(tmp_path))
    assert capture.available() is True
    assert capture.findWindow() is None  # 場所はあるが、VR画面はまだ無い


def test_the_page_is_known_by_its_instance(panel):
    write_frame(panel, instance=7, width=0, height=0, pixels=b"")
    assert capture.findWindow() == 7
    assert capture.isWindow(7) and not capture.isWindow(8)
    assert capture.captureWindowRaw(7) is None  # まだ1枚も描いていない
    write_frame(panel, instance=0, width=0, height=0, pixels=b"")  # 消えた
    assert capture.findWindow() is None and not capture.isWindow(7)


def test_a_frame_comes_back_as_bgra_with_its_full_box(panel):
    pixels = write_frame(panel)
    raw, size, box = capture.captureWindowRaw(7)
    assert (raw, size, box) == (pixels, (4, 2), (0, 0, 4, 2))
    image = capture.bgraFromCapture((raw, size, box))
    assert image.shape == (2, 4, 4) and image.flags.writeable
    assert bytes(image[1, 0]) == pixels[16:20]
    assert capture.captureWindowRaw(8) is None  # 別の VR画面の番号では返さない


def test_row_padding_is_dropped(panel):
    rows = [bytes([10 + y]) * 16 + b"\xff" * 4 for y in range(2)]  # 幅4 (16バイト) + 余り4バイト
    write_frame(panel, stride=20, pixels=b"".join(rows))
    raw, size, _ = capture.captureWindowRaw(7)
    assert size == (4, 2) and raw == bytes([10]) * 16 + bytes([11]) * 16


@pytest.mark.parametrize("change", [dict(magic=b"SOMETHIN"), dict(width=9000), dict(width=4, stride=8)])
def test_a_file_in_another_format_is_not_a_page(panel, change):
    write_frame(panel, **change)
    assert capture.findWindow() is None
    assert capture.captureWindowRaw(7) is None


def test_a_frame_being_replaced_is_not_returned_half_written(panel):
    first = write_frame(panel, sequence=2)
    assert capture.captureWindowRaw(7)[0] == first
    write_frame(panel, sequence=3, pixels=b"\xee" * 32)  # 奇数: 書き換えの途中
    assert capture.captureWindowRaw(7)[0] == first  # 前の1枚を返す
    done = write_frame(panel, sequence=4, pixels=b"\xaa" * 32)
    assert capture.captureWindowRaw(7)[0] == done


def test_a_first_frame_still_being_written_is_not_returned(panel):
    write_frame(panel, sequence=1)
    assert capture.captureWindowRaw(7) is None


def test_an_unchanged_frame_is_not_read_again(panel, monkeypatch):
    write_frame(panel)
    first = capture.captureWindowRaw(7)[0]
    reads = []
    real = capture.os.pread
    monkeypatch.setattr(capture.os, "pread", lambda fd, length, offset: reads.append(length) or real(fd, length, offset))
    assert capture.captureWindowRaw(7)[0] is first
    assert reads == [64]  # 先頭だけ読んで、通し番号が同じなら画素は読まない


def test_the_stream_waits_for_the_size_it_asked_for(panel, commands):
    write_frame(panel, width=4, height=2)
    stream = capture.WindowStream(7)
    assert stream.take()[1] == (4, 2) and not stream.stale  # 大きさを頼む前は、届いたものを返す
    assert capture.resizeClient(7, 8, 2) == (8, 2)
    assert commands() == ["resize 8 2"]
    assert stream.take() is None and stream.stale  # まだ前の大きさ
    write_frame(panel, sequence=4, width=8, height=2, pixels=b"\x01" * 64)
    assert stream.take()[1] == (8, 2) and not stream.stale
    assert not stream.closed
    write_frame(panel, instance=9)  # VR画面が作り直された
    assert stream.closed and stream.take() is None
    stream.close()


def test_pointer_commands_are_sent_one_line_each(panel, commands):
    capture.mouseMove(7, 10, 20)
    capture.mouseMove(7, 11.6, 21, pressed=True)
    capture.mouseDown(7, 30, 40)
    capture.mouseUp(7, 30, 41)
    capture.mouseWheel(7, 50, 60, 120)   # Windows の1目盛り上向き
    capture.mouseWheel(7, 50, 60, -60)
    assert commands() == ["move 10 20 0", "move 11 21 1", "down 30 40", "up 30 41",
                          "wheel 50 60 -2.0000", "wheel 50 60 1.0000"]


def test_the_overlay_uses_this_backend_on_linux():
    from models.overlay import overlay

    if sys.platform == "linux":
        assert overlay.window_capture is capture
    else:
        assert overlay.window_capture is not capture


def test_the_vr_ui_is_supported_only_where_the_page_can_be_captured(monkeypatch):
    from models.overlay import overlay

    monkeypatch.setattr(overlay.window_capture, "available", lambda: True)
    assert overlay.vrPanelSupported() is True
    monkeypatch.setattr(overlay.window_capture, "available", lambda: False)
    assert overlay.vrPanelSupported() is False


def test_frames_are_numpy_friendly(panel):
    pixels = np.arange(32, dtype=np.uint8).tobytes()
    write_frame(panel, pixels=pixels)
    image = capture.bgraFromCapture(capture.captureWindowRaw(7))
    image[..., 3] = 255  # 呼び出し側がアルファを決める
    assert image[0, 0].tolist() == [0, 1, 2, 255]
