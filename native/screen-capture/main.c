/* SPDX-License-Identifier: MIT
 * Copies the newest frame of one shared window into a frame file.
 *
 * The desktop's ScreenCast portal lets the user pick a window; the app that
 * asked (the Tauri process) starts this helper with the portal's PipeWire
 * connection as stdin and the stream's node id. Chat reading only needs a few
 * frames a second, so the stream is asked for that rate (1000 / INTERVAL_MS)
 * and frames that still arrive clearly sooner are dropped here.
 *
 *   vrct-screen-capture PARENT_PID NODE_ID FRAME_PATH INTERVAL_MS
 *   stdin   the PipeWire remote from OpenPipeWireRemote (a socket)
 *   stdout  a pipe the owner only holds. Nothing is written to it: when the
 *           owner closes its end (or dies), the helper stops.
 *   stderr  "streaming" once frames can flow, and one "screen_capture_<reason>"
 *           line when it stops on a failure
 *
 * Frame file: a 64-byte little-endian header, then the pixels.
 *   0  "VRCTSCR1"
 *   8  sequence (u64): odd while the pixels are being replaced
 *   16 instance (u64): 0 once the stream is gone; the upper half is this pid
 *   24 width, 28 height, 32 bytes per row, 36 pixel layout (u32 each)
 *   40 time of the frame, CLOCK_MONOTONIC nanoseconds (u64)
 * Rows are `bytes per row` apart; the last one holds only width * 4 bytes.
 *
 * Only memory buffers are accepted (no DMA-BUF), so no GPU access is needed.
 */
#include <endian.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>
#include <pipewire/pipewire.h>
#include <spa/buffer/meta.h>
#include <spa/param/video/format-utils.h>

#define HEADER_SIZE 64
#define MAX_SIDE 16384
#define NS 1000000000ULL
enum layout { LAYOUT_BGRX, LAYOUT_BGRA, LAYOUT_RGBX, LAYOUT_RGBA };

struct state {
    struct pw_main_loop *loop;
    struct pw_context *context;
    struct pw_core *core;
    struct pw_registry *registry;
    struct pw_stream *stream;
    struct spa_hook core_hook, registry_hook, stream_hook;
    struct spa_video_info_raw format;
    const char *path;
    uint64_t sequence, instance, interval, last_frame;
    uint32_t node, layout;
    int file, result;
    bool format_ok, connected, announced, stopping;
};

static uint64_t now_ns(void) {
    struct timespec now; clock_gettime(CLOCK_MONOTONIC, &now);
    return (uint64_t)now.tv_sec * NS + now.tv_nsec;
}
static bool number(const char *text, uint64_t *value) {
    char *end;
    if (!text[0] || text[0] == '-' || text[0] == '+') return false;
    errno = 0; *value = strtoull(text, &end, 10);
    return !errno && !*end;
}
static void finish(struct state *s, int code) {
    if (s->stopping) return;
    s->stopping = true; s->result = code;
    pw_main_loop_quit(s->loop);
}
static void failed(struct state *s, const char *reason) {
    if (!s->stopping) fprintf(stderr, "screen_capture_%s\n", reason);
    finish(s, 1);
}
static void owner_gone(void *data, int fd, uint32_t mask) { (void)fd; (void)mask; finish(data, 1); }
static void signal_stop(void *data, int sig) { (void)sig; finish(data, 0); }

static bool write_at(int fd, const void *data, size_t size, off_t offset) {
    const uint8_t *bytes = data;
    while (size) {
        ssize_t written = pwrite(fd, bytes, size, offset);
        if (written < 0 && errno == EINTR) continue;
        if (written <= 0) return false;
        bytes += written; size -= (size_t)written; offset += written;
    }
    return true;
}
static void u32(uint8_t *p, uint32_t value) { value = htole32(value); memcpy(p, &value, 4); }
static void u64(uint8_t *p, uint64_t value) { value = htole64(value); memcpy(p, &value, 8); }
static bool write_header(struct state *s, uint64_t instance, uint32_t width, uint32_t height, uint32_t stride, uint64_t time) {
    uint8_t header[HEADER_SIZE] = {0};
    memcpy(header, "VRCTSCR1", 8);
    u64(header + 8, s->sequence); u64(header + 16, instance);
    u32(header + 24, width); u32(header + 28, height); u32(header + 32, stride); u32(header + 36, s->layout);
    u64(header + 40, time);
    return write_at(s->file, header, sizeof(header), 0);
}

/* Tells readers the stream is gone (instance 0) before the file disappears. */
static void close_frame(struct state *s) {
    s->sequence += 2;
    write_header(s, 0, 0, 0, 0, 0);
    unlink(s->path);
    close(s->file);
    s->file = -1;
}

/* Which part of the buffer is the picture. Some compositors hand out a larger buffer and mark the window in it. */
static bool picture(const struct state *s, struct spa_buffer *b, uint32_t *x, uint32_t *y, uint32_t *width, uint32_t *height) {
    *x = *y = 0; *width = s->format.size.width; *height = s->format.size.height;
    struct spa_meta_region *crop = spa_buffer_find_meta_data(b, SPA_META_VideoCrop, sizeof(*crop));
    if (!crop || !spa_meta_region_is_valid(crop)) return true;
    if (crop->region.position.x < 0 || crop->region.position.y < 0 ||
        (uint64_t)crop->region.position.x + crop->region.size.width > *width ||
        (uint64_t)crop->region.position.y + crop->region.size.height > *height) return false;
    *x = (uint32_t)crop->region.position.x; *y = (uint32_t)crop->region.position.y;
    *width = crop->region.size.width; *height = crop->region.size.height;
    return true;
}
static void publish(struct state *s, struct spa_buffer *b) {
    if (!s->format_ok || b->n_datas < 1) return;
    uint64_t now = now_ns();
    /* The compositor already keeps to the rate it was asked for, give or take its timer. Only drop
     * what comes clearly sooner (a source that ignores the cap), or every second frame would go. */
    if (s->last_frame && now - s->last_frame < s->interval / 4 * 3) return;
    struct spa_data *d = &b->datas[0];
    struct spa_meta_header *meta = spa_buffer_find_meta_data(b, SPA_META_Header, sizeof(*meta));
    if (!d->chunk || !d->chunk->size || (d->chunk->flags & SPA_CHUNK_FLAG_CORRUPTED) ||
        (meta && (meta->flags & SPA_META_HEADER_FLAG_CORRUPTED))) return; /* no picture in this one */
    if (!d->data || (d->type != SPA_DATA_MemFd && d->type != SPA_DATA_MemPtr)) { failed(s, "buffer_unsupported"); return; }
    uint32_t x, y, width, height;
    if (!picture(s, b, &x, &y, &width, &height)) { failed(s, "buffer_invalid"); return; }
    uint64_t stride = d->chunk->stride > 0 ? (uint64_t)d->chunk->stride : (uint64_t)s->format.size.width * 4;
    uint64_t offset = d->chunk->offset, rows = (uint64_t)(y + height - 1) * stride + ((uint64_t)x + width) * 4;
    if (stride < (uint64_t)s->format.size.width * 4 || stride > (uint64_t)MAX_SIDE * 8 ||
        offset > d->maxsize || rows > d->maxsize - offset) { failed(s, "buffer_invalid"); return; }
    const uint8_t *pixels = (const uint8_t *)d->data + offset + y * stride + (uint64_t)x * 4;
    /* Odd while the pixels change: a reader that sees the same even number before and after its copy has a whole frame. */
    uint8_t writing[8]; u64(writing, s->sequence + 1);
    if (!write_at(s->file, writing, sizeof(writing), 8) ||
        !write_at(s->file, pixels, (size_t)((height - 1) * stride + (uint64_t)width * 4), HEADER_SIZE)) {
        failed(s, "frame_write_failed"); return;
    }
    s->sequence += 2;
    if (!write_header(s, s->instance, width, height, (uint32_t)stride, now)) { failed(s, "frame_write_failed"); return; }
    s->last_frame = now;
}
static void stream_process(void *data) {
    struct state *s = data; struct pw_buffer *newest = NULL, *buffer;
    /* Only the newest picture matters; older ones go straight back. */
    while ((buffer = pw_stream_dequeue_buffer(s->stream))) {
        if (newest) pw_stream_queue_buffer(s->stream, newest);
        newest = buffer;
    }
    if (!newest) return;
    if (!s->stopping) publish(s, newest->buffer);
    pw_stream_queue_buffer(s->stream, newest);
}
static void stream_state(void *data, enum pw_stream_state old, enum pw_stream_state state, const char *error) {
    struct state *s = data; (void)old; (void)error;
    if (state == PW_STREAM_STATE_ERROR) { failed(s, "stream_error"); return; }
    if (state == PW_STREAM_STATE_UNCONNECTED && s->connected) { failed(s, "stream_ended"); return; }
    if (state != PW_STREAM_STATE_UNCONNECTED) s->connected = true;
    if (state == PW_STREAM_STATE_STREAMING && !s->announced) {
        s->announced = true;
        fputs("streaming\n", stderr);
    }
}
static bool layout_of(uint32_t format, uint32_t *layout) {
    switch (format) {
    case SPA_VIDEO_FORMAT_BGRx: *layout = LAYOUT_BGRX; return true;
    case SPA_VIDEO_FORMAT_BGRA: *layout = LAYOUT_BGRA; return true;
    case SPA_VIDEO_FORMAT_RGBx: *layout = LAYOUT_RGBX; return true;
    case SPA_VIDEO_FORMAT_RGBA: *layout = LAYOUT_RGBA; return true;
    default: return false;
    }
}
static void stream_param(void *data, uint32_t id, const struct spa_pod *param) {
    struct state *s = data;
    if (id != SPA_PARAM_Format) return;
    s->format_ok = false;
    if (!param) return;
    uint32_t type, subtype;
    if (spa_format_parse(param, &type, &subtype) < 0 || type != SPA_MEDIA_TYPE_video || subtype != SPA_MEDIA_SUBTYPE_raw ||
        spa_format_video_raw_parse(param, &s->format) < 0 || !layout_of(s->format.format, &s->layout) ||
        !s->format.size.width || !s->format.size.height ||
        s->format.size.width > MAX_SIDE || s->format.size.height > MAX_SIDE) {
        failed(s, "format_unsupported"); return;
    }
    s->format_ok = true;
    uint8_t space[1024]; struct spa_pod_builder builder = SPA_POD_BUILDER_INIT(space, sizeof(space));
    const struct spa_pod *params[3];
    /* Memory only: a DMA-BUF would need the GPU to read it back. */
    params[0] = spa_pod_builder_add_object(&builder, SPA_TYPE_OBJECT_ParamBuffers, SPA_PARAM_Buffers,
        SPA_PARAM_BUFFERS_buffers, SPA_POD_CHOICE_RANGE_Int(4, 2, 16),
        SPA_PARAM_BUFFERS_dataType, SPA_POD_CHOICE_FLAGS_Int((1 << SPA_DATA_MemFd) | (1 << SPA_DATA_MemPtr)));
    params[1] = spa_pod_builder_add_object(&builder, SPA_TYPE_OBJECT_ParamMeta, SPA_PARAM_Meta,
        SPA_PARAM_META_type, SPA_POD_Id(SPA_META_Header), SPA_PARAM_META_size, SPA_POD_Int(sizeof(struct spa_meta_header)));
    params[2] = spa_pod_builder_add_object(&builder, SPA_TYPE_OBJECT_ParamMeta, SPA_PARAM_Meta,
        SPA_PARAM_META_type, SPA_POD_Id(SPA_META_VideoCrop), SPA_PARAM_META_size, SPA_POD_Int(sizeof(struct spa_meta_region)));
    if (pw_stream_update_params(s->stream, params, 3) < 0) failed(s, "stream_error");
}
static const struct pw_stream_events stream_events = {
    PW_VERSION_STREAM_EVENTS, .state_changed = stream_state, .param_changed = stream_param, .process = stream_process
};
static void core_error(void *data, uint32_t id, int seq, int res, const char *message) {
    (void)seq; (void)message;
    /* Errors on other objects reach the stream as a state change. */
    if (id == PW_ID_CORE && res == -EPIPE) failed(data, "pipewire_disconnected");
}
static const struct pw_core_events core_events = {PW_VERSION_CORE_EVENTS, .error = core_error};
static void removed(void *data, uint32_t id) {
    struct state *s = data;
    /* The shared window was closed, or sharing was stopped from the desktop. */
    if (id == s->node) failed(s, "stream_ended");
}
static const struct pw_registry_events registry_events = {PW_VERSION_REGISTRY_EVENTS, .global_remove = removed};

static bool connect_stream(struct state *s, uint32_t fps) {
    struct pw_properties *props = pw_properties_new(PW_KEY_MEDIA_TYPE, "Video", PW_KEY_MEDIA_CATEGORY, "Capture",
        PW_KEY_MEDIA_ROLE, "Screen", PW_KEY_NODE_NAME, "vrct.screen-capture", PW_KEY_NODE_DONT_RECONNECT, "true", NULL);
    s->stream = pw_stream_new(s->core, "vrct.screen-capture", props);
    if (!s->stream) return false;
    pw_stream_add_listener(s->stream, &s->stream_hook, &stream_events, s);
    uint8_t space[1024]; struct spa_pod_builder builder = SPA_POD_BUILDER_INIT(space, sizeof(space));
    /* No modifier property: that is how a consumer says it takes memory buffers only.
     * The frame rate itself is left open (0/1); the cap makes the compositor skip the frames nobody reads. */
    const struct spa_pod *params[] = {spa_pod_builder_add_object(&builder, SPA_TYPE_OBJECT_Format, SPA_PARAM_EnumFormat,
        SPA_FORMAT_mediaType, SPA_POD_Id(SPA_MEDIA_TYPE_video),
        SPA_FORMAT_mediaSubtype, SPA_POD_Id(SPA_MEDIA_SUBTYPE_raw),
        SPA_FORMAT_VIDEO_format, SPA_POD_CHOICE_ENUM_Id(5, SPA_VIDEO_FORMAT_BGRx, SPA_VIDEO_FORMAT_BGRx,
            SPA_VIDEO_FORMAT_BGRA, SPA_VIDEO_FORMAT_RGBx, SPA_VIDEO_FORMAT_RGBA),
        SPA_FORMAT_VIDEO_size, SPA_POD_CHOICE_RANGE_Rectangle(&SPA_RECTANGLE(1920, 1080), &SPA_RECTANGLE(1, 1),
            &SPA_RECTANGLE(MAX_SIDE, MAX_SIDE)),
        SPA_FORMAT_VIDEO_framerate, SPA_POD_CHOICE_RANGE_Fraction(&SPA_FRACTION(0, 1), &SPA_FRACTION(0, 1),
            &SPA_FRACTION(1000, 1)),
        SPA_FORMAT_VIDEO_maxFramerate, SPA_POD_CHOICE_RANGE_Fraction(&SPA_FRACTION(fps, 1), &SPA_FRACTION(1, 1),
            &SPA_FRACTION(fps, 1)))};
    return pw_stream_connect(s->stream, PW_DIRECTION_INPUT, s->node,
        PW_STREAM_FLAG_AUTOCONNECT | PW_STREAM_FLAG_MAP_BUFFERS, params, 1) >= 0;
}

int main(int argc, char **argv) {
    uint64_t parent, node, interval;
    struct stat input, output;
    if (argc != 5 || !number(argv[1], &parent) || parent <= 1 || parent > INT_MAX ||
        !number(argv[2], &node) || node >= UINT32_MAX || argv[3][0] != '/' || strlen(argv[3]) >= PATH_MAX ||
        !number(argv[4], &interval) || interval > 10000 ||
        fstat(STDIN_FILENO, &input) || !S_ISSOCK(input.st_mode) ||
        fstat(STDOUT_FILENO, &output) || !S_ISFIFO(output.st_mode)) return 2;
    /* The parent may already be gone; never run on as someone else's child. */
    if (getppid() != (pid_t)parent || prctl(PR_SET_PDEATHSIG, SIGKILL) < 0 || getppid() != (pid_t)parent) return 1;
    signal(SIGPIPE, SIG_IGN);
    setvbuf(stderr, NULL, _IOLBF, 0);
    /* PipeWire closes the descriptor it is given; keep 0 itself out of its hands. */
    int remote = fcntl(STDIN_FILENO, F_DUPFD_CLOEXEC, 3), null = open("/dev/null", O_RDONLY | O_CLOEXEC);
    if (remote < 0 || null < 0 || dup2(null, STDIN_FILENO) < 0) return 1;
    close(null);
    struct state s = {.path = argv[3], .node = (uint32_t)node, .interval = interval * 1000000ULL, .file = -1, .result = 1};
    s.instance = ((uint64_t)getpid() << 32) | (now_ns() & 0xFFFFFFFFULL) | 1;
    /* The directory is private to the app; a file left by a helper that was killed is replaced. */
    unlink(s.path);
    s.file = open(s.path, O_RDWR | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
    if (s.file < 0 || !write_header(&s, s.instance, 0, 0, 0, 0)) {
        fprintf(stderr, "screen_capture_frame_write_failed\n");
        return 1;
    }
    pw_init(&argc, &argv);
    s.loop = pw_main_loop_new(NULL);
    struct pw_loop *loop = s.loop ? pw_main_loop_get_loop(s.loop) : NULL;
    s.context = loop ? pw_context_new(loop, NULL, 0) : NULL;
    s.core = s.context ? pw_context_connect_fd(s.context, remote, NULL, 0) : NULL;
    uint32_t fps = interval ? (uint32_t)SPA_CLAMP(1000 / interval, 1U, 60U) : 60;
    if (!s.core) {
        fprintf(stderr, "screen_capture_pipewire_unavailable\n");
    } else {
        pw_core_add_listener(s.core, &s.core_hook, &core_events, &s);
        s.registry = pw_core_get_registry(s.core, PW_VERSION_REGISTRY, 0);
        if (s.registry) pw_registry_add_listener(s.registry, &s.registry_hook, &registry_events, &s);
        pw_loop_add_signal(loop, SIGTERM, signal_stop, &s); pw_loop_add_signal(loop, SIGINT, signal_stop, &s);
        if (!s.registry || !pw_loop_add_io(loop, STDOUT_FILENO, SPA_IO_ERR | SPA_IO_HUP, false, owner_gone, &s) ||
            !connect_stream(&s, fps)) {
            fprintf(stderr, "screen_capture_stream_error\n");
        } else {
            pw_main_loop_run(s.loop);
        }
    }
    close_frame(&s);
    if (s.stream) pw_stream_destroy(s.stream);
    if (s.registry) pw_proxy_destroy((struct pw_proxy *)s.registry);
    if (s.core) pw_core_disconnect(s.core);
    if (s.context) pw_context_destroy(s.context);
    if (s.loop) pw_main_loop_destroy(s.loop);
    pw_deinit();
    return s.result;
}
