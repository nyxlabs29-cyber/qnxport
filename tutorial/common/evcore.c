#include "evcore.h"

#include <ctype.h>
#include <string.h>

void evcore_init(evcore_t *c, FILE *out)
{
    memset(c, 0, sizeof *c);
    c->out = out ? out : stdout;
}

void evcore_on_tick(evcore_t *c)
{
    c->ticks++;
    fprintf(c->out, "tick %u\n", c->ticks);
    fflush(c->out);
}

void evcore_on_job(evcore_t *c, int job_id)
{
    c->jobs++;
    fprintf(c->out, "job %d done\n", job_id);
    fflush(c->out);
}

static void handle_line(evcore_t *c)
{
    size_t i;
    c->buf[c->used] = '\0';
    if (strcmp(c->buf, "quit") == 0) {
        c->quit = 1;
    } else {
        for (i = 0; i < c->used; i++)
            c->buf[i] = (char)toupper((unsigned char)c->buf[i]);
        c->lines++;
        fprintf(c->out, "line: %s\n", c->buf);
        fflush(c->out);
    }
    c->used = 0;
}

void evcore_feed(evcore_t *c, const char *data, size_t n)
{
    size_t i;
    for (i = 0; i < n && !c->quit; i++) {
        if (data[i] == '\n') {
            handle_line(c);
        } else if (c->used < sizeof c->buf - 1) {
            c->buf[c->used++] = data[i];
        }
    }
}

void evcore_eof(evcore_t *c)
{
    if (c->used && !c->quit)
        handle_line(c);
    c->quit = 1;
}

void evcore_summary(const evcore_t *c)
{
    fprintf(c->out, "summary jobs=%u lines=%u ticks_ge_2=%d\n", c->jobs, c->lines, c->ticks >= 2);
    fflush(c->out);
}
