#!/usr/bin/env sh
# Thin interpreter finder. It never changes PATH or installs global tooling.
set -u

write_launcher_error() {
    printf '{"schema_version":1,"status":"%s","ready":false,"reason_code":"%s","message":"%s"}\n' "$1" "$1" "$2"
}

script_path=${1:-}
if [ -z "$script_path" ]; then
    write_launcher_error "script_missing" "the requested setup script was not provided"
    exit 2
fi
shift
case "$script_path" in
    /*|[A-Za-z]:[\\/]*) ;;
    *) script_path="$(pwd)/$script_path" ;;
esac
if [ ! -f "$script_path" ]; then
    write_launcher_error "script_missing" "the requested setup script does not exist"
    exit 2
fi

resolve_candidate() {
    candidate=$1
    if [ -z "$candidate" ]; then
        return 1
    fi
    if [ -f "$candidate" ] && [ -x "$candidate" ]; then
        printf '%s\n' "$candidate"
        return 0
    fi
    command -v "$candidate" 2>/dev/null || return 1
}

test_candidate() {
    candidate=$1
    [ -n "$candidate" ] || return 1
    "$candidate" -I -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1
}

selected=
for candidate in \
    "${GENERAL_SCREENWRITER_HOST_PYTHON:-}" \
    "${CODEX_PYTHON:-}" \
    "${PYTHON:-}" \
    "${GENERAL_SCREENWRITER_SYSTEM_PYTHON:-}" \
    "python3" \
    "python" \
    "${GENERAL_SCREENWRITER_USER_PYTHON:-}" \
    "${HOME:-}/.local/bin/python3" \
    "${HOME:-}/.local/bin/python" \
    "${GENERAL_SCREENWRITER_USER_DATA:-}/general-screenwriter/runtimes/python/bin/python3"
do
    resolved=$(resolve_candidate "$candidate" 2>/dev/null) || continue
    if test_candidate "$resolved"; then
        selected=$resolved
        break
    fi
done

if [ -z "$selected" ]; then
    write_launcher_error "runtime_missing" "no compatible host, system, or user Python interpreter was found"
    exit 2
fi

exec "$selected" -I "$script_path" "$@"
