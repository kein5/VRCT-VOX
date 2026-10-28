/* SPDX-License-Identifier: MIT
 * Watch an inherited creator-thread pidfd throughout the OS audio lifetime.
 * No PCM processing or elevated privileges; only spawn the fixed optional VC worker module.
 */
#include <errno.h>
#include <limits.h>
#include <poll.h>
#include <signal.h>
#include <stdbool.h>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/prctl.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <unistd.h>

static volatile sig_atomic_t stopping;
static void stop(int signal) { (void)signal; stopping = 1; }
static long number(const char *text) {
    char *end;
    errno = 0;
    long value = strtol(text, &end, 10);
    return !text[0] || errno || *end || value < 0 || value > INT_MAX ? -1 : value;
}
static bool owner_alive(int fd) {
    struct pollfd item = {.fd = fd, .events = POLLIN};
    return syscall(SYS_pidfd_send_signal, fd, 0, NULL, 0) == 0 && poll(&item, 1, 0) == 0;
}
int main(int argc, char **argv) {
    if (argc != 8 || argv[3][0] != '/' || argv[4][0] != '/' || argv[5][0] != '/' ||
        argv[6][0] != '/' || strlen(argv[7]) != 32 ||
        strspn(argv[7], "0123456789abcdef") != 32) return 2;
    long expected_parent = number(argv[1]), descriptor = number(argv[2]);
    if (expected_parent <= 1 || descriptor < 3) return 2;
    int owner_fd = (int)descriptor;
    /* getppid alone misses an already-dead creating thread in a live TGID.
     * The caller opens its own thread pidfd BEFORE spawning us. Poll it for
     * our entire lifetime; never reopen a numeric TID after thread death. */
    if (getppid() != (pid_t)expected_parent || prctl(PR_SET_PDEATHSIG, SIGKILL) < 0 ||
        getppid() != (pid_t)expected_parent || !owner_alive(owner_fd)) return 1;
    struct sigaction action = {.sa_handler = stop};
    sigemptyset(&action.sa_mask);
    if (sigaction(SIGTERM, &action, NULL) || sigaction(SIGINT, &action, NULL)) return 1;
    if (signal(SIGCHLD, SIG_DFL) == SIG_ERR) return 1;
    pid_t supervisor = getpid();
    pid_t child = fork();
    if (child < 0) return 1;
    if (child == 0) {
        close(owner_fd);
        /* Our supervisor has one thread: these PID checks also cover its
         * death before prctl. SIGKILL of supervisor cannot orphan audio. */
        if (getppid() != supervisor || prctl(PR_SET_PDEATHSIG, SIGKILL) < 0 ||
            getppid() != supervisor) _exit(1);
        signal(SIGTERM, SIG_DFL);
        signal(SIGINT, SIG_DFL);
        char *args[] = {argv[3], "-u", "-m", "integrations.seed_vc.live_worker",
            "--engine", argv[4], "--assets", argv[5], "--reference", argv[6],
            "--session", argv[7], NULL};
        execv(args[0], args);
        _exit(1);
    }
    /* Only the worker owns these protocol pipes; do not keep EOF alive. */
    close(STDIN_FILENO);
    close(STDOUT_FILENO);
    int status;
    while (!stopping) {
        pid_t done = waitpid(child, &status, WNOHANG);
        if (done == child) { close(owner_fd); return WIFEXITED(status) ? WEXITSTATUS(status) : 1; }
        if (done < 0 && errno != EINTR) { close(owner_fd); return 1; }
        struct pollfd item = {.fd = owner_fd, .events = POLLIN};
        int result = poll(&item, 1, 20);
        if (result > 0 || (result < 0 && errno != EINTR)) break;
    }
    kill(child, SIGKILL);
    while (waitpid(child, &status, 0) < 0 && errno == EINTR) {}
    close(owner_fd);
    return 1;
}
