#!/usr/bin/env bash
set -euo pipefail

APK=""
APKTOOL="./apktool.jar"
WORKDIR="build/work"
PATCH_FILE="blackmagic_mod.patch"

while [ $# -gt 0 ]; do
  case "$1" in
    --apk) APK="$2"; shift 2;;
    --apktool) APKTOOL="$2"; shift 2;;
    --workdir) WORKDIR="$2"; shift 2;;
    --patch-file) PATCH_FILE="$2"; shift 2;;
    *) echo "Unknown arg: $1" >&2; exit 2;;
  esac
done

if [ -z "$APK" ]; then
  echo "Usage: $0 --apk input.apk [--apktool ./apktool.jar] [--workdir build/work]" >&2
  exit 2
fi

mkdir -p "$WORKDIR"
DECODED="$WORKDIR/decoded_apk"
rm -rf "$DECODED"

# If input is .apkm, extract an APK first
lower="$(printf '%s' "$APK" | tr '[:upper:]' '[:lower:]')"
if [[ "$lower" == *.apkm ]]; then
  echo "Extracting from .apkm ..."
  bash scripts/extract_from_apkm.sh --apkm "$APK" --out "$WORKDIR/from_apkm.apk"
  APK="$WORKDIR/from_apkm.apk"
fi

if [ ! -f "$APKTOOL" ]; then
  echo "Downloading apktool.jar ..."
  curl -L -o "$APKTOOL" https://github.com/iBotPeaches/Apktool/releases/download/v2.9.3/apktool_2.9.3.jar
fi

echo "$ java -jar $APKTOOL d -f $APK -o $DECODED"
java -jar "$APKTOOL" d -f "$APK" -o "$DECODED"

# Apply patch
cp "$PATCH_FILE" "$WORKDIR/applied_patch.diff" 2>/dev/null || true
if git apply --unsafe-paths "$PATCH_FILE" -p1 -C1 --directory="$WORKDIR" 2>/dev/null; then
  :
else
  (cd "$WORKDIR" && patch -p1 -i "$(pwd)/../$(basename "$PATCH_FILE")")
fi

echo "Decoded at: $DECODED"


