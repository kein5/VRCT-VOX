/* SPDX-License-Identifier: MIT
 * Identity-bound PipeWire capture. Mainloop callbacks only; no inference,
 * recording files, default-device selection, or real-time callback file I/O.
 */
#include <endian.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <math.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/syscall.h>
#include <unistd.h>
#include <time.h>
#include <pipewire/pipewire.h>
#include <spa/param/audio/format-utils.h>
#include <spa/param/latency-utils.h>
#include <spa/node/io.h>

#define RATE 48000
#define NS 1000000000ULL
struct state {
    struct pw_main_loop *loop;
    struct pw_context *context;
    struct pw_core *core;
    struct pw_registry *registry;
    struct pw_stream *stream;
    struct spa_hook core_hook, registry_hook, stream_hook;
    const struct spa_io_position *position;
    struct spa_latency_info latency;
    struct spa_io_clock epoch;
    uint64_t cookie, serial, last_packet, last_cycle;
    const char *name, *kind;
    char stream_name[80];
    uint32_t target, own, links[8], n_links, sequence;
    int sync, result, names;
    bool cookie_ok, target_ok, format_ok, latency_ok, started, stopping;
};
static uint64_t now_ns(void) {
    struct timespec now; clock_gettime(CLOCK_MONOTONIC, &now);
    return (uint64_t)now.tv_sec * NS + now.tv_nsec;
}
static bool number(const char *text, uint64_t *value) {
    char *end;
    if (!text[0] || text[0] == '-') return false;
    errno = 0; *value = strtoull(text, &end, 10);
    return !errno && !*end;
}
static void finish(struct state *s, int code) {
    if (s->stopping) return;
    s->stopping = true; s->result = code;
    pw_main_loop_quit(s->loop);
}
static void failed(struct state *s, const char *code) {
    if (!s->stopping) fprintf(stderr, "asr_capture_%s\n", code);
    finish(s, 1);
}
static void parent_gone(void *data, int fd, uint32_t mask) {
    (void)fd; (void)mask; failed(data, "owner_gone");
}
static void signal_stop(void *data, int sig) { (void)sig; finish(data, 0); }
static void watchdog(void *data, uint64_t expirations) {
    struct state *s = data; (void)expirations;
    uint64_t now = now_ns();
    if (now - s->last_packet > (s->started ? 500000000ULL : 3000000000ULL)) failed(s, "stalled");
}
static void core_info(void *data, const struct pw_core_info *info) {
    struct state *s = data;
    s->cookie_ok = info->cookie == s->cookie;
    if (!s->cookie_ok) failed(s, "core_changed");
}
static void core_error(void *data, uint32_t id, int seq, int res, const char *msg) {
    (void)id; (void)seq; (void)res; (void)msg; failed(data, "core_error");
}
static void stream_state(void *data, enum pw_stream_state old, enum pw_stream_state state, const char *error) {
    struct state *s = data; (void)old; (void)error;
    if (state == PW_STREAM_STATE_ERROR || (s->started && state != PW_STREAM_STATE_STREAMING)) failed(s, "stream_disconnected");
}
static void stream_io(void *data, uint32_t id, void *area, uint32_t size) {
    struct state *s = data;
    if (id != SPA_IO_Position) return;
    if (s->started && s->position != area) { failed(s, "clock_changed"); return; }
    s->position = size >= sizeof(struct spa_io_position) ? area : NULL;
}
static bool same_latency(const struct spa_latency_info *a, const struct spa_latency_info *b) {
    return a->direction == b->direction && a->min_quantum == b->min_quantum && a->max_quantum == b->max_quantum &&
        a->min_rate == b->min_rate && a->max_rate == b->max_rate && a->min_ns == b->min_ns && a->max_ns == b->max_ns;
}
static void stream_param(void *data, uint32_t id, const struct spa_pod *param) {
    struct state *s = data;
    if (!param) {
        if (id == SPA_PARAM_Latency) {
            s->latency_ok = false;
            if (s->started) failed(s, "latency_removed");
        }
        if (s->started && id == SPA_PARAM_Format) failed(s, "format_removed");
        return;
    }
    if (id == SPA_PARAM_Format) {
        struct spa_audio_info_raw audio = {0};
        if (spa_format_audio_raw_parse(param, &audio) < 0 || audio.format != SPA_AUDIO_FORMAT_S16_LE || audio.rate != RATE || audio.channels != 1) {
            failed(s, "format_invalid"); return;
        }
        s->format_ok = true;
    } else if (id == SPA_PARAM_Latency) {
        struct spa_latency_info latency = {0};
        if (spa_latency_parse(param, &latency) < 0) { failed(s, "latency_invalid"); return; }
        if (latency.direction != SPA_DIRECTION_OUTPUT) return;
        if (!isfinite(latency.max_quantum) || latency.max_quantum > 100 || latency.max_ns > (int64_t)NS || latency.max_rate > RATE) {
            failed(s, "latency_invalid"); return;
        }
        if (s->started && !same_latency(&s->latency, &latency)) { failed(s, "latency_changed"); return; }
        s->latency = latency; s->latency_ok = true;
    }
}
static bool same_clock(const struct spa_io_clock *a, const struct spa_io_clock *b, bool cycle) {
    return a->id == b->id && a->rate.num == b->rate.num && a->rate.denom == b->rate.denom &&
        a->duration == b->duration && (!cycle || (a->cycle == b->cycle && a->nsec == b->nsec && a->flags == b->flags));
}
static bool snapshot(struct state *s, struct pw_time *time, struct spa_io_clock *clock) {
    if (!s->position) return false;
    for (int i = 0; i < 3; i++) {
        struct spa_io_clock a, b;
        memcpy(&a, &s->position->clock, sizeof(a));
        if (pw_stream_get_time_n(s->stream, time, sizeof(*time)) < 0) return false;
        memcpy(&b, &s->position->clock, sizeof(b));
        if (same_clock(&a, &b, true) && a.nsec == (uint64_t)time->now &&
            a.rate.num == time->rate.num && a.rate.denom == time->rate.denom) {
            *clock = a; return true;
        }
    }
    return false;
}
static void u32(uint8_t *p, uint32_t value) { value = htole32(value); memcpy(p, &value, 4); }
static void u64(uint8_t *p, uint64_t value) { value = htole64(value); memcpy(p, &value, 8); }
static bool send_buffer(struct state *s, struct pw_buffer *buffer) {
    struct spa_buffer *b = buffer->buffer;
    struct pw_time timing = {0}; struct spa_io_clock clock;
    if (!s->target_ok || !s->n_links || !s->format_ok || !s->latency_ok) return true; /* wait for negotiation */
    if (s->own != pw_stream_get_node_id(s->stream)) { failed(s, "stream_identity_invalid"); return false; }
    if (!snapshot(s, &timing, &clock)) { failed(s, s->position ? "clock_snapshot_inconsistent" : "clock_position_missing"); return false; }
    if (!clock.rate.num || !clock.rate.denom || !clock.duration || !buffer->time ||
        (s->started && !same_clock(&s->epoch, &clock, false)) ||
        (clock.flags & (SPA_IO_CLOCK_FLAG_FREEWHEEL | SPA_IO_CLOCK_FLAG_NO_RATE | SPA_IO_CLOCK_FLAG_DISCONT | SPA_IO_CLOCK_FLAG_XRUN_RECOVER))) {
        failed(s, "clock_invalid"); return false;
    }
    struct spa_meta_header *header = spa_buffer_find_meta_data(b, SPA_META_Header, sizeof(*header));
    if (header && (header->flags & SPA_META_HEADER_FLAG_CORRUPTED)) { failed(s, "buffer_corrupted"); return false; }
    if (s->started && header && (header->flags & SPA_META_HEADER_FLAG_DISCONT)) { failed(s, "discontinuity"); return false; }
    if (b->n_datas != 1 || !b->datas[0].data || !b->datas[0].chunk) { failed(s, "buffer_invalid"); return false; }
    struct spa_data *d = &b->datas[0];
    if (d->chunk->flags & SPA_CHUNK_FLAG_CORRUPTED) { failed(s, "buffer_corrupted"); return false; }
    uint32_t bytes = d->chunk->size, offset = d->chunk->offset;
    if (!bytes) return true;
    if (bytes % 2 || bytes > RATE / 10 * 2 || offset > d->maxsize || bytes > d->maxsize - offset ||
        (d->chunk->stride != 0 && d->chunk->stride != 2)) { failed(s, "buffer_invalid"); return false; }
    uint32_t frames = bytes / 2;
    /* Maximum reported path latency, plus one buffer-duration safety margin.
     * This is a conservative PipeWire-reported bound, not a physical ADC clock. */
    long double ns = (fmaxl(s->latency.max_quantum, 0) * clock.duration + fmaxl(s->latency.max_rate, 0)) *
        clock.rate.num * NS / clock.rate.denom + fmaxl(s->latency.max_ns, 0) +
        ((long double)timing.buffered + frames) * NS / RATE;
    uint64_t now = now_ns();
    if (!isfinite(ns) || ns < 0 || ns > 250000000 || buffer->time < (uint64_t)ceill(ns) ||
        buffer->time > now || (s->started && buffer->time <= s->last_cycle)) { failed(s, "timestamp_invalid"); return false; }
    uint64_t first = buffer->time - (uint64_t)ceill(ns);
    if (now - first > 250000000) { failed(s, "stale_buffer"); return false; }
    for (uint32_t i = 0; i < frames; i += 960) {
        uint32_t count = SPA_MIN(960U, frames - i);
        uint8_t packet[32 + 1920];
        memcpy(packet, "VCA1", 4); u32(packet + 4, s->sequence++);
        u64(packet + 8, buffer->time); u64(packet + 16, first + (uint64_t)i * NS / RATE);
        u32(packet + 24, RATE); u32(packet + 28, count);
        memcpy(packet + 32, (uint8_t *)d->data + offset + i * 2, count * 2);
        ssize_t written = write(STDOUT_FILENO, packet, 32 + count * 2);
        if (written != (ssize_t)(32 + count * 2)) { failed(s, "pipe_blocked"); return false; }
    }
    s->epoch = clock; s->started = true; s->last_packet = now; s->last_cycle = buffer->time;
    return true;
}
static void stream_process(void *data) {
    struct state *s = data; struct pw_buffer *buffer;
    while (!s->stopping && (buffer = pw_stream_dequeue_buffer(s->stream))) {
        send_buffer(s, buffer);
        pw_stream_queue_buffer(s->stream, buffer);
    }
}
static const struct pw_stream_events stream_events = {
    PW_VERSION_STREAM_EVENTS, .state_changed = stream_state, .io_changed = stream_io,
    .param_changed = stream_param, .process = stream_process
};
static void global(void *data, uint32_t id, uint32_t permissions, const char *type, uint32_t version, const struct spa_dict *props) {
    struct state *s = data; (void)permissions; (void)version;
    if (!props) return;
    if (!strcmp(type, PW_TYPE_INTERFACE_Node)) {
        const char *name = spa_dict_lookup(props, PW_KEY_NODE_NAME);
        if (!name) return;
        if (!strcmp(name, s->stream_name)) { s->own = id; return; }
        if (strcmp(name, s->name)) return;
        s->names++;
        const char *serial = spa_dict_lookup(props, PW_KEY_OBJECT_SERIAL), *media = spa_dict_lookup(props, PW_KEY_MEDIA_CLASS);
        uint64_t value;
        if (!serial || !number(serial, &value) || value != s->serial || !media ||
            strcmp(media, !strcmp(s->kind, "mic") ? "Audio/Source" : "Audio/Sink") || s->names != 1) {
            failed(s, "endpoint_changed"); return;
        }
        s->target = id; s->target_ok = true;
    } else if (!strcmp(type, PW_TYPE_INTERFACE_Link)) {
        const char *out = spa_dict_lookup(props, PW_KEY_LINK_OUTPUT_NODE), *in = spa_dict_lookup(props, PW_KEY_LINK_INPUT_NODE);
        uint64_t output, input;
        if (!out || !in || !number(out, &output) || !number(in, &input) || s->own == SPA_ID_INVALID) return;
        if (input != s->own && output != s->own) return;
        if (input != s->own || output != s->target || s->n_links >= 8) { failed(s, "unexpected_link"); return; }
        s->links[s->n_links++] = id;
    }
}
static void removed(void *data, uint32_t id) {
    struct state *s = data;
    if (id == s->target || id == s->own) { failed(s, "endpoint_removed"); return; }
    for (uint32_t i = 0; i < s->n_links; i++) if (s->links[i] == id) { failed(s, "link_removed"); return; }
}
static void core_done(void *data, uint32_t id, int seq) {
    struct state *s = data; (void)id;
    if (seq != s->sync || s->stream || s->stopping) return;
    if (!s->cookie_ok || !s->target_ok || s->names != 1) { failed(s, "endpoint_missing"); return; }
    char serial[32]; snprintf(serial, sizeof(serial), "%llu", (unsigned long long)s->serial);
    struct pw_properties *props = pw_properties_new(PW_KEY_MEDIA_TYPE, "Audio", PW_KEY_MEDIA_CATEGORY, "Capture",
        PW_KEY_MEDIA_ROLE, "Communication", PW_KEY_NODE_NAME, s->stream_name, PW_KEY_TARGET_OBJECT, serial,
        PW_KEY_NODE_DONT_RECONNECT, "true", "node.dont-fallback", "true", "node.dont-move", "true",
        "node.linger", "false", PW_KEY_NODE_LATENCY, "480/48000", "vrct.asr.capture", "v1", NULL);
    if (!strcmp(s->kind, "speaker")) pw_properties_set(props, PW_KEY_STREAM_CAPTURE_SINK, "true");
    s->stream = pw_stream_new(s->core, s->stream_name, props);
    if (!s->stream) { failed(s, "stream_create_failed"); return; }
    pw_stream_add_listener(s->stream, &s->stream_hook, &stream_events, s);
    uint8_t space[1024]; struct spa_pod_builder builder = SPA_POD_BUILDER_INIT(space, sizeof(space));
    struct spa_audio_info_raw info = SPA_AUDIO_INFO_RAW_INIT(.format = SPA_AUDIO_FORMAT_S16_LE, .rate = RATE, .channels = 1, .position = { SPA_AUDIO_CHANNEL_MONO });
    const struct spa_pod *params[] = {spa_format_audio_raw_build(&builder, SPA_PARAM_EnumFormat, &info)};
    if (pw_stream_connect(s->stream, PW_DIRECTION_INPUT, PW_ID_ANY, PW_STREAM_FLAG_AUTOCONNECT | PW_STREAM_FLAG_MAP_BUFFERS, params, 1) < 0) failed(s, "stream_connect_failed");
}
static const struct pw_core_events core_events = {PW_VERSION_CORE_EVENTS, .info = core_info, .done = core_done, .error = core_error};
static const struct pw_registry_events registry_events = {PW_VERSION_REGISTRY_EVENTS, .global = global, .global_remove = removed};
int main(int argc, char **argv) {
    uint64_t parent, owner, cookie, serial;
    if (argc != 8 || !number(argv[1], &parent) || parent <= 1 || parent > INT_MAX ||
        !number(argv[2], &owner) || owner < 3 || owner > INT_MAX || !number(argv[3], &cookie) || cookie > UINT32_MAX ||
        !number(argv[4], &serial) || !argv[5][0] || strlen(argv[5]) > 512 ||
        (strcmp(argv[6], "mic") && strcmp(argv[6], "speaker")) || strlen(argv[7]) != 32 ||
        strspn(argv[7], "0123456789abcdef") != 32 || !strncmp(argv[5], "vrct.managed.", 13) ||
        !strncmp(argv[5], "vrct.asr.capture.", 17) || !strncmp(argv[5], "vrct.source-bridge.", 19)) return 2;
    struct pollfd watch = {.fd = (int)owner, .events = POLLIN};
    if (getppid() != (pid_t)parent || prctl(PR_SET_PDEATHSIG, SIGKILL) < 0 || getppid() != (pid_t)parent ||
        syscall(SYS_pidfd_send_signal, (int)owner, 0, NULL, 0) != 0 || poll(&watch, 1, 0) != 0) return 1;
    if (fpathconf(STDOUT_FILENO, _PC_PIPE_BUF) < 1952 || fcntl(STDOUT_FILENO, F_SETFL, fcntl(STDOUT_FILENO, F_GETFL) | O_NONBLOCK) < 0) return 1;
    signal(SIGPIPE, SIG_IGN);
    pw_init(&argc, &argv);
    struct state s = {.cookie = cookie, .serial = serial, .name = argv[5], .kind = argv[6], .target = SPA_ID_INVALID, .own = SPA_ID_INVALID};
    snprintf(s.stream_name, sizeof(s.stream_name), "vrct.asr.capture.%s", argv[7]);
    s.loop = pw_main_loop_new(NULL);
    s.context = pw_context_new(pw_main_loop_get_loop(s.loop), NULL, 0);
    s.core = pw_context_connect(s.context, NULL, 0);
    if (!s.core) { pw_context_destroy(s.context); pw_main_loop_destroy(s.loop); return 1; }
    pw_core_add_listener(s.core, &s.core_hook, &core_events, &s);
    s.registry = pw_core_get_registry(s.core, PW_VERSION_REGISTRY, 0);
    pw_registry_add_listener(s.registry, &s.registry_hook, &registry_events, &s);
    struct pw_loop *loop = pw_main_loop_get_loop(s.loop);
    pw_loop_add_io(loop, (int)owner, SPA_IO_IN | SPA_IO_ERR | SPA_IO_HUP, false, parent_gone, &s);
    pw_loop_add_signal(loop, SIGTERM, signal_stop, &s); pw_loop_add_signal(loop, SIGINT, signal_stop, &s);
    struct spa_source *timer = pw_loop_add_timer(loop, watchdog, &s);
    struct timespec interval = {.tv_nsec = 100000000};
    pw_loop_update_timer(loop, timer, &interval, &interval, false);
    s.last_packet = now_ns();
    s.sync = pw_core_sync(s.core, PW_ID_CORE, 0);
    pw_main_loop_run(s.loop);
    if (s.stream) pw_stream_destroy(s.stream);
    pw_proxy_destroy((struct pw_proxy *)s.registry); pw_core_disconnect(s.core);
    pw_context_destroy(s.context); pw_main_loop_destroy(s.loop); pw_deinit();
    return s.result;
}
