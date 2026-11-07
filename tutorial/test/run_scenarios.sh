#!/bin/sh
# Run the same input through every loop implementation and compare the normalised output.
# Input: "hello", then (after 600 ms) "world" and "quit". 3 jobs finish at ~150/300/450 ms; tick every 100 ms.
# Normalisation: tick lines are dropped (their count depends on timing); the summary reports ticks_ge_2.
set -eu
B=${1:-build/host}
EXPECT='line: HELLO
job 1 done
job 2 done
job 3 done
line: WORLD
summary jobs=3 lines=2 ticks_ge_2=1'
fail=0
for bin in evdemo-epoll evdemo-poll evdemo-qnx-shim; do
    out=$( { printf 'hello\n'; sleep 0.6; printf 'world\nquit\n'; } | "$B/$bin" 100 3 150 )
    ticks=$(printf '%s\n' "$out" | grep -c '^tick ' || true)
    norm=$(printf '%s\n' "$out" | grep -v '^tick ')
    if [ "$norm" = "$EXPECT" ] && [ "$ticks" -ge 2 ]; then
        echo "PASS $bin (ticks seen: $ticks)"
    else
        echo "FAIL $bin"; printf '%s\n' "$out"; fail=1
    fi
done
# EOF on stdin must also end the loop
out=$( : | "$B/evdemo-qnx-shim" 100 0 )
printf '%s\n' "$out" | grep -q '^summary jobs=0 lines=0' && echo "PASS evdemo-qnx-shim (stdin EOF ends loop)" || { echo "FAIL eof"; fail=1; }
exit $fail
