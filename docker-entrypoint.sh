#!/bin/sh
set -eu

db_path=${SLEEP_DB_PATH:-/data/sleep.db}
db_dir=$(dirname -- "$db_path")

mkdir -p -- "$db_dir"
chown app:app -- "$db_dir"
if [ -L "$db_path" ]; then
    echo "Refusing symbolic-link database path: $db_path" >&2
    exit 1
fi
if [ -e "$db_path" ]; then
    chown -h app:app -- "$db_path"
fi

exec gosu app "$@"
