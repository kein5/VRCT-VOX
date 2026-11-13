"""The window-sharing helper (native/screen-capture) without a PipeWire daemon or a portal.

The frame-file writer is compiled with a small harness that hands it buffers the way PipeWire would,
and the file is then read by the backend's own reader, so both sides of the format are held together.
"""
import os
from pathlib import Path
import shlex
import socket
import subprocess
import sys

import numpy as np
import pytest

from models.ocr import ocr_capture_portal
from models.ocr.ocr_capture_portal import SharedWindowCapture, parseHeader

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "native/screen-capture/main.c"
pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux window-sharing helper")

WIDTH, HEIGHT, PAD = 5, 3, 12

HARNESS = r'''
#define main helper_main
#define pw_main_loop_quit fixture_quit
#include "%(source)s"
#undef main
static int quits;
int fixture_quit(struct pw_main_loop *loop) { (void)loop; quits++; return 0; }

#define W %(width)d
#define H %(height)d
#define STRIDE (W * 4 + %(pad)d)
int main(int argc, char **argv) {
    if (argc != 3) return 2;
    const char *scenario = argv[2];
    struct state s = {.path = argv[1], .interval = 250000000ULL, .file = -1};
    s.instance = ((uint64_t)getpid() << 32) | 1;
    s.file = open(s.path, O_RDWR | O_CREAT | O_TRUNC, 0600);
    s.format.format = SPA_VIDEO_FORMAT_BGRx; s.format.size = SPA_RECTANGLE(W, H);
    s.layout = LAYOUT_BGRX; s.format_ok = true;
    if (s.file < 0 || !write_header(&s, s.instance, 0, 0, 0, 0)) return 3;

    uint8_t pixels[STRIDE * H];
    memset(pixels, 0xEE, sizeof(pixels));               /* row padding never belongs to the picture */
    for (int y = 0; y < H; y++) for (int x = 0; x < W; x++) {
        uint8_t *p = pixels + y * STRIDE + x * 4;
        p[0] = 10 + x; p[1] = 100 + y; p[2] = 200 + x + y; p[3] = 0x7F;
    }
    struct spa_chunk chunk = {.offset = 0, .size = sizeof(pixels), .stride = STRIDE};
    struct spa_data data = {.type = SPA_DATA_MemFd, .data = pixels, .maxsize = sizeof(pixels), .chunk = &chunk};
    struct spa_meta_region crop = {.region = SPA_REGION(1, 1, 3, 2)};
    struct spa_meta_header header = {0};
    struct spa_meta metas[2] = {{.type = SPA_META_VideoCrop, .size = sizeof(crop), .data = &crop},
                                {.type = SPA_META_Header, .size = sizeof(header), .data = &header}};
    struct spa_buffer buffer = {.n_datas = 1, .datas = &data};

    if (!strcmp(scenario, "plain")) {
        publish(&s, &buffer);
    } else if (!strcmp(scenario, "rgba")) {
        s.layout = LAYOUT_RGBA;
        publish(&s, &buffer);
    } else if (!strcmp(scenario, "no_stride")) {      /* some producers leave the stride at 0: rows are then tightly packed */
        chunk.stride = 0; chunk.size = W * 4 * H;
        for (int y = 0; y < H; y++) for (int x = 0; x < W; x++) {
            uint8_t *p = pixels + y * W * 4 + x * 4;
            p[0] = 10 + x; p[1] = 100 + y; p[2] = 200 + x + y; p[3] = 0x7F;
        }
        publish(&s, &buffer);
    } else if (!strcmp(scenario, "crop")) {
        buffer.n_metas = 2; buffer.metas = metas;
        publish(&s, &buffer);
    } else if (!strcmp(scenario, "crop_outside")) {
        crop.region = SPA_REGION(3, 1, 3, 2);
        buffer.n_metas = 1; buffer.metas = metas;
        publish(&s, &buffer);
    } else if (!strcmp(scenario, "throttle")) {
        publish(&s, &buffer);
        pixels[0] = 77;
        publish(&s, &buffer);                           /* too soon: dropped */
        printf("soon=%%llu ", (unsigned long long)s.sequence);
        s.last_frame -= 200000000ULL;                   /* the rate that was asked for, give or take a timer */
        publish(&s, &buffer);
    } else if (!strcmp(scenario, "empty")) {
        chunk.size = 0;
        publish(&s, &buffer);
    } else if (!strcmp(scenario, "corrupted_chunk")) {
        chunk.flags = SPA_CHUNK_FLAG_CORRUPTED;
        publish(&s, &buffer);
    } else if (!strcmp(scenario, "corrupted_header")) {
        header.flags = SPA_META_HEADER_FLAG_CORRUPTED;
        buffer.n_metas = 1; buffer.metas = metas + 1;
        publish(&s, &buffer);
    } else if (!strcmp(scenario, "no_format")) {
        s.format_ok = false;
        publish(&s, &buffer);
    } else if (!strcmp(scenario, "dmabuf")) {
        data.type = SPA_DATA_DmaBuf; data.data = NULL;
        publish(&s, &buffer);
    } else if (!strcmp(scenario, "short")) {
        data.maxsize = (H - 1) * STRIDE + W * 4 - 1;   /* one byte less than the picture needs */
        publish(&s, &buffer);
    } else if (!strcmp(scenario, "narrow_stride")) {
        chunk.stride = W * 4 - 4;
        publish(&s, &buffer);
    } else if (!strcmp(scenario, "over")) {
        publish(&s, &buffer);
        close_frame(&s);
    } else if (!strcmp(scenario, "layouts")) {
        uint32_t layout;
        printf("%%d%%d%%d%%d%%d%%d ", layout_of(SPA_VIDEO_FORMAT_BGRx, &layout), layout_of(SPA_VIDEO_FORMAT_BGRA, &layout),
               layout_of(SPA_VIDEO_FORMAT_RGBx, &layout), layout_of(SPA_VIDEO_FORMAT_RGBA, &layout),
               layout_of(SPA_VIDEO_FORMAT_I420, &layout), layout_of(SPA_VIDEO_FORMAT_xRGB, &layout));
    } else {
        return 2;
    }
    printf("sequence=%%llu quits=%%d\n", (unsigned long long)s.sequence, quits);
    return 0;
}
'''


def flags():
    return shlex.split(subprocess.check_output(["pkg-config", "--cflags", "--libs", "libpipewire-0.3"], text=True))


def compile_c(source, binary):
    subprocess.run(["cc", "-std=gnu11", "-O2", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary), *flags()], check=True)
    return binary


@pytest.fixture(scope="module")
def helper(tmp_path_factory):
    assert SOURCE.is_file(), "the window-sharing helper is not implemented"
    return compile_c(SOURCE, tmp_path_factory.mktemp("screen-capture") / "vrct-screen-capture")


@pytest.fixture(scope="module")
def harness(tmp_path_factory):
    folder = tmp_path_factory.mktemp("screen-capture-harness")
    source = folder / "harness.c"
    source.write_text(HARNESS % {"source": SOURCE, "width": WIDTH, "height": HEIGHT, "pad": PAD})
    return compile_c(source, folder / "harness")


@pytest.fixture
def run(harness, tmp_path, monkeypatch):
    # The harness has exited by the time the file is read; its process id no longer says anything.
    monkeypatch.setattr(ocr_capture_portal, "_writerAlive", lambda instance: True)

    def start(scenario):
        frame = tmp_path / "screen-frame"
        done = subprocess.run([str(harness), str(frame), scenario], capture_output=True, text=True, timeout=10)
        assert done.returncode == 0, done.stderr
        return frame, done
    return start


def picture(x0=0, y0=0, width=WIDTH, height=HEIGHT):
    """What the harness draws, in the byte order it writes: (10 + x, 100 + y, 200 + x + y)."""
    return np.array([[[10 + x, 100 + y, 200 + x + y] for x in range(x0, x0 + width)] for y in range(y0, y0 + height)], np.uint8)


def header(frame):
    return parseHeader(frame.read_bytes()[:64])


def test_a_frame_written_by_the_helper_is_read_by_the_backend(run):
    frame, done = run("plain")
    assert done.stdout == "sequence=2 quits=0\n" and done.stderr == ""
    sequence, instance, width, height, stride, layout = header(frame)
    assert (sequence, width, height, stride, layout) == (2, WIDTH, HEIGHT, WIDTH * 4 + PAD, 0)
    assert instance != 0 and instance & 1
    # Rows keep the producer's spacing; the last one stops at the picture's edge.
    assert frame.stat().st_size == 64 + (HEIGHT - 1) * (WIDTH * 4 + PAD) + WIDTH * 4
    np.testing.assert_array_equal(SharedWindowCapture(frame).capture(), picture())
    assert SharedWindowCapture(frame).isActive()


def test_red_first_layouts_reach_the_backend_as_bgr(run):
    frame, _ = run("rgba")
    assert header(frame)[5] == 3
    np.testing.assert_array_equal(SharedWindowCapture(frame).capture(), picture()[:, :, ::-1])


def test_a_missing_stride_means_tightly_packed_rows(run):
    frame, done = run("no_stride")
    assert done.stdout == "sequence=2 quits=0\n"
    assert header(frame)[4] == WIDTH * 4
    np.testing.assert_array_equal(SharedWindowCapture(frame).capture(), picture())


def test_only_the_marked_part_of_a_larger_buffer_is_the_picture(run):
    frame, done = run("crop")
    assert done.stdout == "sequence=2 quits=0\n"
    assert header(frame)[2:4] == (3, 2)
    np.testing.assert_array_equal(SharedWindowCapture(frame).capture(), picture(1, 1, 3, 2))


def test_frames_that_come_too_soon_are_dropped_and_the_asked_rate_passes(run):
    frame, done = run("throttle")
    assert done.stdout == "soon=2 sequence=4 quits=0\n"
    assert int(SharedWindowCapture(frame).capture()[0, 0, 0]) == 77


@pytest.mark.parametrize("scenario", ["empty", "corrupted_chunk", "corrupted_header", "no_format"])
def test_buffers_without_a_picture_change_nothing(run, scenario):
    frame, done = run(scenario)
    assert done.stdout == "sequence=0 quits=0\n" and done.stderr == ""
    assert header(frame)[2:4] == (0, 0)
    assert SharedWindowCapture(frame).capture() is None


@pytest.mark.parametrize("scenario,reason", [("dmabuf", "buffer_unsupported"), ("short", "buffer_invalid"),
                                             ("narrow_stride", "buffer_invalid"), ("crop_outside", "buffer_invalid")])
def test_buffers_that_cannot_be_read_stop_the_helper_with_a_reason(run, scenario, reason):
    frame, done = run(scenario)
    assert done.stdout == "sequence=0 quits=1\n"
    assert done.stderr == f"screen_capture_{reason}\n"
    assert SharedWindowCapture(frame).capture() is None


def test_the_end_of_the_stream_is_written_before_the_file_goes(harness, tmp_path, monkeypatch):
    monkeypatch.setattr(ocr_capture_portal, "_writerAlive", lambda instance: True)
    frame, kept = tmp_path / "screen-frame", tmp_path / "kept"
    frame.write_bytes(b"")
    os.link(frame, kept)   # a second name, as a reader that still has the file open would see it
    done = subprocess.run([str(harness), str(frame), "over"], capture_output=True, text=True, timeout=10)
    assert done.returncode == 0 and done.stdout == "sequence=4 quits=0\n"
    assert not frame.exists()
    sequence, instance, width, height, _stride, _layout = parseHeader(kept.read_bytes()[:64])
    assert (sequence, instance, width, height) == (4, 0, 0, 0)
    assert not SharedWindowCapture(kept).isActive()


def test_only_the_four_byte_layouts_the_backend_knows_are_accepted(run):
    _, done = run("layouts")
    assert done.stdout.startswith("111100 ")


def test_bad_command_lines_and_descriptors_are_refused_before_anything_is_written(helper, tmp_path):
    frame = tmp_path / "screen-frame"
    parent = str(os.getpid())
    left, right = socket.socketpair()
    with left, right:
        def start(args, stdin=left, stdout=subprocess.PIPE):
            return subprocess.run([str(helper), *args], stdin=stdin, stdout=stdout, stderr=subprocess.PIPE, timeout=5).returncode
        good = [parent, "42", str(frame), "250"]
        for args in ([], good[:3], good + ["extra"], ["1", "42", str(frame), "250"], [parent, "x", str(frame), "250"],
                     [parent, "-1", str(frame), "250"], [parent, "4294967295", str(frame), "250"],
                     [parent, "42", "relative/frame", "250"], [parent, "42", str(frame), "10001"], [parent, "42", str(frame), "fast"]):
            assert start(args) == 2, args
        # The PipeWire connection must be a socket, and the owner's lifeline a pipe.
        assert start(good, stdin=subprocess.DEVNULL) == 2
        with (tmp_path / "out").open("wb") as out:
            assert start(good, stdout=out) == 2
        # Started by someone other than the process it names: it must not run on.
        assert start(["2", "42", str(frame), "250"]) == 1
    assert not frame.exists()


def test_without_pipewire_behind_the_descriptor_the_helper_stops_and_leaves_no_file(helper, tmp_path):
    frame = tmp_path / "screen-frame"
    left, right = socket.socketpair()
    with left:
        right.close()   # nobody answers on the "PipeWire connection"
        done = subprocess.run([str(helper), str(os.getpid()), "42", str(frame), "250"], stdin=left, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, timeout=10)
    assert done.returncode == 1
    assert not frame.exists()
