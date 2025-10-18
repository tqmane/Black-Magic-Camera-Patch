#!/usr/bin/env bash
set -euo pipefail

APKM=""
OUT=""
WORKDIR="build/apkm_extract"

while [ $# -gt 0 ]; do
  case "$1" in
    --apkm) APKM="$2"; shift 2;;
    --out) OUT="$2"; shift 2;;
    --workdir) WORKDIR="$2"; shift 2;;
    *) echo "Unknown arg: $1" >&2; exit 2;;
  esac
done

if [ -z "$APKM" ] || [ -z "$OUT" ]; then
  echo "Usage: $0 --apkm path.apkm --out output.apk" >&2
  exit 2
fi

if [ ! -f "$APKM" ]; then
  echo "ERROR: .apkm not found: $APKM" >&2
  exit 2
fi

mkdir -p "$WORKDIR"
mkdir -p "$(dirname "$OUT")"

# List entries
mapfile -t entries < <(zipinfo -1 "$APKM" | grep -iE '\.apk$' || true)
if [ ${#entries[@]} -eq 0 ]; then
  echo "ERROR: No APK entries in .apkm" >&2
  exit 3
fi

pick=""
for e in "${entries[@]}"; do
  base="$(basename "$e" | tr '[:upper:]' '[:lower:]')"
  if [ "$base" = "base.apk" ]; then pick="$e"; break; fi
done
if [ -z "$pick" ]; then
  # pick largest
  pick="$(zipinfo -l "$APKM" | awk '/\.apk$/ {print $1, $NF}' | sort -nr | awk 'NR==1{print $2}')"
fi

unzip -p "$APKM" "$pick" > "$OUT"
echo "$OUT"


