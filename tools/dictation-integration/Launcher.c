#include <mach-o/dyld.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

// Set Foundation's sandbox home before loading the Swift/AppKit process.
// The Swift entry point independently verifies its resulting cache directory.
int main(int argc, char **argv) {
    char executable[PATH_MAX], resolved[PATH_MAX];
    uint32_t size = sizeof(executable);
    if (_NSGetExecutablePath(executable, &size) != 0 || !realpath(executable, resolved)) return 78;
    char *slash = strrchr(resolved, '/');
    if (!slash) return 78;
    *(slash + 1) = '\0';
    if (strlen(resolved) + strlen("DictationIntegrationBin") >= sizeof(resolved)) return 78;
    strcat(resolved, "DictationIntegrationBin");
    if (setenv("CFFIXED_USER_HOME", INTEGRATION_HOME, 1) != 0 ||
        setenv("REVIEW_TODAY_M1_UI_FIXTURE", "1", 1) != 0) return 78;
    argv[0] = resolved;
    execv(resolved, argv);
    perror("Unable to launch isolated dictation integration");
    return 78;
}
