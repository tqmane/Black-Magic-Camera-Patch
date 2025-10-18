#!/usr/bin/env bash
set -euo pipefail

DECODED=""
DIST="dist"
ZIPALIGN="${ANDROID_SDK_ROOT:-/usr/local/lib/android/sdk}/build-tools/34.0.0/zipalign"
APKSIGNER="${ANDROID_SDK_ROOT:-/usr/local/lib/android/sdk}/build-tools/34.0.0/apksigner"
KEYSTORE="build/blackmagic.keystore"
KEY_ALIAS=""
KS_PASS=""
KEY_PASS=""
VERSION=""
UNSIGNED_ONLY="false"

while [ $# -gt 0 ]; do
  case "$1" in
    --decoded) DECODED="$2"; shift 2;;
    --dist) DIST="$2"; shift 2;;
    --zipalign) ZIPALIGN="$2"; shift 2;;
    --apksigner) APKSIGNER="$2"; shift 2;;
    --keystore) KEYSTORE="$2"; shift 2;;
    --key-alias) KEY_ALIAS="$2"; shift 2;;
    --keystore-pass) KS_PASS="$2"; shift 2;;
    --key-pass) KEY_PASS="$2"; shift 2;;
    --version) VERSION="$2"; shift 2;;
    --unsigned-only) UNSIGNED_ONLY="true"; shift;;
    *) echo "Unknown arg: $1" >&2; exit 2;;
  esac
done

if [ -z "$DECODED" ]; then
  echo "Usage: $0 --decoded build/work/decoded_apk [--dist dist]" >&2
  exit 2
fi

mkdir -p "$DIST"
ts="$(date -u +%Y%m%d%H%M%S)"
[ -n "$VERSION" ] || VERSION="$ts"

UNSIGNED_APK="$DIST/Blackmagic_Camera_mod_unsigned_${VERSION}.apk"
ALIGNED_APK="$DIST/Blackmagic_Camera_mod_unsigned_aligned_${VERSION}.apk"
SIGNED_APK="$DIST/Blackmagic_Camera_mod_signed_${VERSION}.apk"

APKTOOL_JAR="apktool.jar"
echo "$ java -jar $APKTOOL_JAR b $DECODED -o $UNSIGNED_APK"
java -jar "$APKTOOL_JAR" b "$DECODED" -o "$UNSIGNED_APK"

"$ZIPALIGN" -p -f 4096 "$UNSIGNED_APK" "$ALIGNED_APK"

if [ "$UNSIGNED_ONLY" = "true" ]; then
  echo "Signing skipped. Output: $ALIGNED_APK"
  exit 0
fi

if [ -f "$KEYSTORE" ] && [ -n "$KEY_ALIAS" ] && [ -n "$KS_PASS" ] && [ -n "$KEY_PASS" ]; then
  "$APKSIGNER" sign \
    --ks "$KEYSTORE" \
    --ks-key-alias "$KEY_ALIAS" \
    --ks-pass "pass:$KS_PASS" \
    --key-pass "pass:$KEY_PASS" \
    --out "$SIGNED_APK" \
    "$ALIGNED_APK"
  echo "Signed APK: $SIGNED_APK"
else
  echo "WARN: Keystore info incomplete. Leaving unsigned aligned APK."
fi


