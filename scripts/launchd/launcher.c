// Runs a launchd job's script as a child process, so this app -- not
// /bin/bash -- is the process macOS names in its permission prompts.
// It must spawn and wait, never exec: exec would hand the identity back to bash.
#include <errno.h>
#include <signal.h>
#include <spawn.h>
#include <stdio.h>
#include <string.h>
#include <sys/wait.h>

extern char **environ;
static pid_t child;

static void forward(int sig) {
    if (child > 0) kill(child, sig);
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr, "usage: %s script [args...]\n", argv[0]);
        return 64;
    }
    signal(SIGTERM, forward);
    signal(SIGINT, forward);
    signal(SIGHUP, forward);
    int rc = posix_spawn(&child, argv[1], NULL, NULL, argv + 1, environ);
    if (rc != 0) {
        fprintf(stderr, "%s: cannot run %s: %s\n", argv[0], argv[1], strerror(rc));
        return 126;
    }
    int status;
    while (waitpid(child, &status, 0) < 0) {
        if (errno != EINTR) return 1;
    }
    if (WIFEXITED(status)) return WEXITSTATUS(status);
    return 128 + WTERMSIG(status);
}
