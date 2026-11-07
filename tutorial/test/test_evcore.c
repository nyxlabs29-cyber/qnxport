/* Host unit test for the shared core (compiles as plain C on any host). */
#include <assert.h>
#include <stdio.h>
#include <string.h>

#include "../common/evcore.h"

static void read_all(FILE *f, char *dst, size_t cap)
{
    size_t n;
    rewind(f);
    n = fread(dst, 1, cap - 1, f);
    dst[n] = '\0';
}

int main(void)
{
    char got[512];
    evcore_t c;
    FILE *out = tmpfile();
    assert(out);

    evcore_init(&c, out);
    evcore_on_tick(&c);
    evcore_on_tick(&c);
    evcore_on_job(&c, 7);
    evcore_feed(&c, "hel", 3);            /* partial line is buffered */
    evcore_feed(&c, "lo\nwor", 6);
    evcore_feed(&c, "ld\nquit\nignored\n", 16);
    assert(c.quit == 1);
    assert(c.ticks == 2 && c.jobs == 1 && c.lines == 2);

    read_all(out, got, sizeof got);
    assert(strcmp(got, "tick 1\ntick 2\njob 7 done\nline: HELLO\nline: WORLD\n") == 0);

    evcore_init(&c, out);                 /* EOF flushes a partial line and quits */
    evcore_feed(&c, "tail", 4);
    evcore_eof(&c);
    assert(c.quit == 1 && c.lines == 1);

    fclose(out);
    puts("test_evcore: ok");
    return 0;
}
