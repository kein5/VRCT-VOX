/* SPDX-License-Identifier: MIT
 * One identity-bound mute mutation. No audio processing or endpoint ownership.
 */
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <pipewire/pipewire.h>
#include <spa/param/props.h>
#include <spa/pod/builder.h>
#include <spa/pod/iter.h>

#define TARGET "vrct.managed.source"
struct state {
    struct pw_main_loop *loop;
    struct pw_core *core;
    struct pw_registry *registry;
    struct pw_node *node;
    struct spa_hook core_listener, registry_listener, node_listener;
    uint32_t cookie, expected_cookie, target_id;
    uint64_t expected_serial;
    const char *target, *marker, *media_class;
    int seq, phase, names, result;
    bool mute, valid_node;
    struct pw_node *direct;
    struct spa_hook direct_listener;
    uint32_t direct_id;
    uint64_t direct_serial;
    int direct_names;
    bool guard_direct, direct_valid, direct_seen, direct_mute, expected_direct_mute;
};
static int set_mute(struct state *s, bool mute) {
    uint8_t buffer[256];
    struct spa_pod_builder builder = SPA_POD_BUILDER_INIT(buffer, sizeof(buffer));
    struct spa_pod *param = spa_pod_builder_add_object(&builder,
        SPA_TYPE_OBJECT_Props, SPA_PARAM_Props, SPA_PROP_mute, SPA_POD_Bool(mute));
    return pw_node_set_param(s->node, SPA_PARAM_Props, 0, param);
}
static void fail(struct state *s) {
    s->result = 1;
    if (s->guard_direct && s->phase >= 1 && s->phase < 3 && s->node && s->valid_node
            && s->cookie == s->expected_cookie && s->names == 1) {
        s->phase = 3;
        if (set_mute(s, true) >= 0) {
            s->seq = pw_core_sync(s->core, PW_ID_CORE, 0);
            return;
        }
    }
    pw_main_loop_quit(s->loop);
}
static void core_info(void *data, const struct pw_core_info *info) {
    ((struct state *)data)->cookie = info->cookie;
}
static void core_error(void *data, uint32_t id, int seq, int res, const char *message) {
    (void)id; (void)seq; (void)res; (void)message;
    fail(data);
}
static void node_info(void *data, const struct pw_node_info *info) {
    struct state *s = data;
    /* Params-only notifications carry an empty props dictionary. */
    if (!(info->change_mask & PW_NODE_CHANGE_MASK_PROPS)) return;
    if (!info->props) { s->valid_node = false; if (s->phase) fail(s); return; }
    const char *tag = spa_dict_lookup(info->props, s->marker);
    const char *media = spa_dict_lookup(info->props, PW_KEY_MEDIA_CLASS);
    s->valid_node = tag && !strcmp(tag, "v1") && media && !strcmp(media, s->media_class);
    if (s->phase && !s->valid_node) fail(s);
}
static const struct pw_node_events node_events = {PW_VERSION_NODE_EVENTS, .info = node_info};
static void direct_info(void *data, const struct pw_node_info *info) {
    struct state *s = data;
    if (!(info->change_mask & PW_NODE_CHANGE_MASK_PROPS)) return;
    if (!info->props) { s->direct_valid = false; if (s->phase) fail(s); return; }
    const char *tag = spa_dict_lookup(info->props, "vrct.managed.route");
    const char *media = spa_dict_lookup(info->props, PW_KEY_MEDIA_CLASS);
    s->direct_valid = tag && !strcmp(tag, "v1") && media && !strcmp(media, "Audio/Sink");
    if (s->phase && !s->direct_valid) fail(s);
}
static void direct_param(void *data, int seq, uint32_t id, uint32_t index,
                         uint32_t next, const struct spa_pod *param) {
    (void)seq; (void)index; (void)next;
    struct state *s = data;
    if (id != SPA_PARAM_Props || !param) return;
    const struct spa_pod_prop *mute = spa_pod_find_prop(param, NULL, SPA_PROP_mute);
    if (!mute) return;
    s->direct_seen = spa_pod_get_bool(&mute->value, &s->direct_mute) == 0;
    if (s->phase && (!s->direct_seen || s->direct_mute != s->expected_direct_mute)) fail(s);
}
static const struct pw_node_events direct_events = {
    PW_VERSION_NODE_EVENTS, .info = direct_info, .param = direct_param
};
static void global(void *data, uint32_t id, uint32_t permissions, const char *type,
                   uint32_t version, const struct spa_dict *props) {
    struct state *s = data;
    (void)permissions; (void)version;
    if (strcmp(type, PW_TYPE_INTERFACE_Node) || !props) return;
    const char *name = spa_dict_lookup(props, PW_KEY_NODE_NAME);
    if (s->guard_direct && name && !strcmp(name, "vrct.managed.vc")) {
        s->direct_names++;
        const char *serial = spa_dict_lookup(props, PW_KEY_OBJECT_SERIAL);
        if (!serial || strtoull(serial, NULL, 10) != s->direct_serial) return;
        s->direct_id = id;
        s->direct = pw_registry_bind(s->registry, id, PW_TYPE_INTERFACE_Node, PW_VERSION_NODE, 0);
        if (s->direct) {
            pw_node_add_listener(s->direct, &s->direct_listener, &direct_events, s);
            uint32_t params[] = {SPA_PARAM_Props};
            if (pw_node_subscribe_params(s->direct, params, 1) < 0) fail(s);
        }
        return;
    }
    if (!name || strcmp(name, s->target)) return;
    s->names++;
    const char *serial = spa_dict_lookup(props, PW_KEY_OBJECT_SERIAL);
    if (!serial || strtoull(serial, NULL, 10) != s->expected_serial) return;
    s->target_id = id;
    s->node = pw_registry_bind(s->registry, id, PW_TYPE_INTERFACE_Node, PW_VERSION_NODE, 0);
    if (s->node) pw_node_add_listener(s->node, &s->node_listener, &node_events, s);
}
static void removed(void *data, uint32_t id) {
    struct state *s = data;
    if (s->node && s->target_id == id) fail(s);
    if (s->direct && s->direct_id == id) fail(s);
}
static void done(void *data, uint32_t id, int seq) {
    struct state *s = data;
    (void)id;
    if (seq != s->seq) return;
    if (s->phase == 3) {
        pw_main_loop_quit(s->loop);
        return;
    }
    if (s->result) return;
    if (s->cookie != s->expected_cookie || s->names != 1 || !s->node) {
        fail(s);
        return;
    }
    if (s->phase == 0) {
        s->phase = 1;
        s->seq = pw_core_sync(s->core, PW_ID_CORE, 0);
        return;
    }
    if (!s->valid_node) { fail(s); return; }
    if (s->guard_direct && (s->direct_names != 1 || !s->direct || !s->direct_valid
            || !s->direct_seen || s->direct_mute != s->expected_direct_mute)) { fail(s); return; }
    if (s->phase == 2) {
        pw_main_loop_quit(s->loop);
        return;
    }
    /* This proxy is bound to the old object, not looked up again by reused id/name. */
    if (set_mute(s, s->mute) < 0) {
        fail(s);
        return;
    }
    s->phase = 2;
    s->seq = pw_core_sync(s->core, PW_ID_CORE, 0);
}
static void timeout(void *data, uint64_t expirations) {
    (void)expirations;
    fail(data);
}
static const struct pw_core_events core_events = {
    PW_VERSION_CORE_EVENTS, .info = core_info, .done = done, .error = core_error
};
static const struct pw_registry_events registry_events = {
    PW_VERSION_REGISTRY_EVENTS, .global = global, .global_remove = removed
};
static bool number(const char *text, uint64_t *value) {
    char *end;
    if (!text[0] || text[0] == '-') return false;
    errno = 0;
    *value = strtoull(text, &end, 10);
    return !errno && !*end;
}
int main(int argc, char **argv) {
    uint64_t cookie, serial;
    if ((argc != 4 && argc != 5 && argc != 7) || !number(argv[1], &cookie) || cookie > UINT32_MAX ||
        !number(argv[2], &serial) || (strcmp(argv[3], "0") && strcmp(argv[3], "1"))) return 2;
    char target[80];
    struct state s = {.expected_cookie = (uint32_t)cookie, .expected_serial = serial,
                      .mute = !strcmp(argv[3], "1"), .target = TARGET,
                      .marker = "vrct.managed.route", .media_class = "Audio/Source"};
    if (argc == 7) {
        if (strcmp(argv[3], "0") || strcmp(argv[4], "guard-direct") ||
                !number(argv[5], &s.direct_serial) || (strcmp(argv[6], "0") && strcmp(argv[6], "1"))) return 2;
        s.guard_direct = true;
        s.expected_direct_mute = !strcmp(argv[6], "1");
    } else if (argc == 5 && !strcmp(argv[4], "vc")) {
        s.target = "vrct.managed.vc";
        s.media_class = "Audio/Sink";
    } else if (argc == 5) {
        if (strlen(argv[4]) != 32 || strspn(argv[4], "0123456789abcdef") != 32) return 2;
        snprintf(target, sizeof(target), "vrct.source-bridge.%s.playback", argv[4]);
        s.target = target;
        s.marker = "vrct.source.bridge";
        s.media_class = "Stream/Output/Audio";
    }
    pw_init(NULL, NULL);
    s.loop = pw_main_loop_new(NULL);
    if (!s.loop) return 1;
    struct pw_context *context = pw_context_new(pw_main_loop_get_loop(s.loop), NULL, 0);
    if (!context) { pw_main_loop_destroy(s.loop); return 1; }
    s.core = pw_context_connect(context, NULL, 0);
    if (!s.core) { pw_context_destroy(context); pw_main_loop_destroy(s.loop); return 1; }
    pw_core_add_listener(s.core, &s.core_listener, &core_events, &s);
    s.registry = pw_core_get_registry(s.core, PW_VERSION_REGISTRY, 0);
    pw_registry_add_listener(s.registry, &s.registry_listener, &registry_events, &s);
    struct spa_source *timer = pw_loop_add_timer(pw_main_loop_get_loop(s.loop), timeout, &s);
    struct timespec delay = {.tv_sec = 2};
    pw_loop_update_timer(pw_main_loop_get_loop(s.loop), timer, &delay, NULL, false);
    s.seq = pw_core_sync(s.core, PW_ID_CORE, 0);
    pw_main_loop_run(s.loop);
    if (s.node) pw_proxy_destroy((struct pw_proxy *)s.node);
    if (s.direct) pw_proxy_destroy((struct pw_proxy *)s.direct);
    pw_proxy_destroy((struct pw_proxy *)s.registry);
    pw_core_disconnect(s.core);
    pw_context_destroy(context);
    pw_main_loop_destroy(s.loop);
    pw_deinit();
    return s.result;
}
