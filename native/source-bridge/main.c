/* SPDX-License-Identifier: MIT
 * Keep the OS audio child bound to its creating control thread's lifetime.
 * No elevated privileges; only exec pw-loopback from the caller's PATH.
 */
#include <errno.h>
#include <limits.h>
#include <signal.h>
#include <stdlib.h>
#include <sys/prctl.h>
#include <unistd.h>

int main(int argc, char **argv) {
    if (argc < 2 || !argv[1][0] || argv[1][0] == '-') return 2;
    char *end;
    errno = 0;
    long expected_parent = strtol(argv[1], &end, 10);
    if (errno || *end || expected_parent <= 1 || expected_parent > INT_MAX) return 2;
    /* A parent that died before prctl produces no signal. Check both sides. */
    if (getppid() != (pid_t)expected_parent || prctl(PR_SET_PDEATHSIG, SIGKILL) < 0 ||
        getppid() != (pid_t)expected_parent) return 1;
    argv[1] = "pw-loopback";
    execvp(argv[1], &argv[1]);
    return 1;
}
