#!/bin/sh

while true; do
    python scrobbler.py || echo "scrobbler.py crashed, restarting..." >&2
    sleep 2
done &

while true; do
    python now_playing.py || echo "now_playing.py crashed, restarting..." >&2
    sleep 2
done

wait
