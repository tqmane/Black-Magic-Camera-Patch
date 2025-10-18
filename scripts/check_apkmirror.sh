#!/usr/bin/env bash
set -euo pipefail

DEFAULT_APP_URL="https://www.apkmirror.com/apk/blackmagic-design/blackmagic-camera/"
PREFERRED_ARCH_REGEX="${APKMIRROR_PREFERRED_ARCH:-arm64|universal|all|noarch}"

APP_URL="${APKMIRROR_APP_URL:-$DEFAULT_APP_URL}"
OUT="build/latest.json"
FALLBACK_APK=""
FORCE="false"
SKIP_RELEASE_CHECK="false"

while [ $# -gt 0 ]; do
  case "$1" in
    --app-url) APP_URL="$2"; shift 2;;
    --out) OUT="$2"; shift 2;;
    --fallback-apk) FALLBACK_APK="$2"; shift 2;;
    --force) FORCE="true"; shift;;
    --skip-release-check) SKIP_RELEASE_CHECK="true"; shift;;
    *) echo "Unknown arg: $1" >&2; exit 2;;
  esac
done

mkdir -p "$(dirname "$OUT")"

ua="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118 Safari/537.36"
fetch() {
  curl -sL --fail --retry 3 --retry-delay 2 \
    -H "User-Agent: $ua" \
    -H "Accept-Language: en-US,en;q=0.8" \
    -H "Referer: $APP_URL" \
    "$1"
}
resolve_final() {
  # prints final effective URL after redirects
  curl -sL --fail --retry 3 --retry-delay 2 \
    -H "User-Agent: $ua" \
    -H "Accept-Language: en-US,en;q=0.8" \
    -H "Referer: $APP_URL" \
    -o /dev/null -w '%{url_effective}' "$1"
}

# 1) Find latest release URL
app_html="$(fetch "$APP_URL" || true)"
if [ -z "$app_html" ]; then
  jq -n --arg err "Failed to fetch app page" '{has_update:false, error:$err}' > "$OUT"
  exit 0
fi

# Prefer all-versions page and direct /download/ links like ReVanced approach
all_rel="$(printf '%s' "$app_html" | grep -oP 'href="\K(/apk/[^"#]*/all-versions/[^"#]*)' | head -n1 || true)"
if [ -n "$all_rel" ]; then
  all_url="https://www.apkmirror.com$all_rel"
else
  # construct heuristic all-versions URL
  base_slug="$(printf '%s' "$APP_URL" | sed 's#/*$##')/all-versions/"
  all_url="$base_slug"
fi
all_html="$(fetch "$all_url" || true)"

# Try to pick a suitable variant download link from all-versions
# Prefer arm64-v8a or universal; fall back to first /download/
variant_dl_rel="$(printf '%s' "$all_html" | grep -oP 'href="\K(/apk/[^"#]*/download/[^"#]*)' | grep -Ei "(${PREFERRED_ARCH_REGEX})" | head -n1 || true)"
if [ -z "$variant_dl_rel" ]; then
  variant_dl_rel="$(printf '%s' "$all_html" | grep -oP 'href="\K(/apk/[^"#]*/download/[^"#]*)' | head -n1 || true)"
fi

download_page_url=""
version="unknown"
if [ -n "$variant_dl_rel" ]; then
  download_page_url="https://www.apkmirror.com$variant_dl_rel"
  version="$(printf '%s' "$variant_dl_rel" | sed -n 's#.*blackmagic-camera-\([A-Za-z0-9._-]\+\)-.*#\1#p' | head -n1)"
fi

# If still missing, fall back to release->variants flow
if [ -z "$download_page_url" ]; then
  release_rel="$(printf '%s' "$app_html" | grep -oP 'href="\K(/apk/[^"#]*/release/[^"#]*)' | head -n1 || true)"
  if [ -z "$release_rel" ]; then
    jq -n --arg err "Could not locate latest release link on APKMirror app page." '{has_update:false, error:$err}' > "$OUT"
    exit 0
  fi
  release_url="https://www.apkmirror.com$release_rel"
  [ "$version" != "unknown" ] || version="$(printf '%s' "$release_rel" | sed -n 's#.*blackmagic-camera-\([A-Za-z0-9._-]\+\)-release.*#\1#p' | head -n1)"

  release_html="$(fetch "$release_url" || true)"
  variants_rel="$(printf '%s' "$release_html" | grep -oP 'href="\K(/apk/[^"#]*/variants/[^"#]*)' | head -n1 || true)"
  variants_url="$release_url"
  if [ -n "$variants_rel" ]; then variants_url="https://www.apkmirror.com$variants_rel"; fi

  variants_html="$(fetch "$variants_url" || true)"
  variant_rel="$(printf '%s' "$variants_html" | grep -oP 'href="\K(/apk/[^"#]*/download/[^"#]*)' | grep -Ei "(${PREFERRED_ARCH_REGEX})" | head -n1 || true)"
  if [ -z "$variant_rel" ]; then
    variant_rel="$(printf '%s' "$variants_html" | grep -oP 'href="\K(/apk/[^"#]*/download/[^"#]*)' | head -n1 || true)"
  fi
  if [ -n "$variant_rel" ]; then download_page_url="https://www.apkmirror.com$variant_rel"; fi
fi

if [ -n "$download_page_url" ]; then
  dl_html="$(fetch "$download_page_url" || true)"
  # primary nofollow link or dl.apkmirror link
  final_rel="$(printf '%s' "$dl_html" | grep -oP 'rel="nofollow" href="\K([^"]+)' | head -n1 || true)"
  if [ -z "$final_rel" ]; then
    final_rel="$(printf '%s' "$dl_html" | grep -oP 'href="\K(https?://[^" ]*dl\.apkmirror\.com[^" ]*)' | head -n1 || true)"
  fi
  if [ -z "$final_rel" ]; then
    final_rel="$(printf '%s' "$dl_html" | grep -oP 'href="\K(/wp-content/[^"#]*download[^"#]*)' | head -n1 || true)"
  fi
  if [ -n "$final_rel" ] && printf '%s' "$final_rel" | grep -q '^/'; then
    final_url="https://www.apkmirror.com$final_rel"
  else
    final_url="$final_rel"
  fi
  # Follow redirects to get CDN URL if still on apkmirror.com
  if [ -n "$final_url" ] && printf '%s' "$final_url" | grep -q 'apkmirror\.com'; then
    resolved="$(resolve_final "$final_url" || true)"
    if [ -n "$resolved" ]; then final_url="$resolved"; fi
  fi
else
  final_url=""
fi

package_type="unknown"
if [ -n "$final_url" ]; then
  low="$(printf '%s' "$final_url" | sed 's/[?].*$//; s/.*/\L&/')"
  case "$low" in
    *.apk) package_type="apk";;
    *.apkm) package_type="apkm";;
    *.xapk) package_type="xapk";;
  esac
fi

has_update=true
if [ "$SKIP_RELEASE_CHECK" != "true" ]; then
  # We skip remote release existence check for simplicity; rely on workflow 'force'
  :
fi

apk_path=""
note=""

# Fallback to provided local APK if any
if [ -z "$apk_path" ] && [ -n "$FALLBACK_APK" ] && [ -f "$FALLBACK_APK" ]; then
  apk_path="$(cd "$(dirname "$FALLBACK_APK")" && pwd)/$(basename "$FALLBACK_APK")"
fi

# Try to download from resolved URL if available
if [ -z "$apk_path" ] && [ -n "$final_url" ] && [ "$package_type" != "unknown" ]; then
  mkdir -p build
  EXT="apk"
  case "$package_type" in
    apkm) EXT="apkm" ;;
    xapk) EXT="xapk" ;;
  esac
  out_file="build/from_checker.$EXT"
  echo "Attempting to download from resolved URL: $final_url" >&2
  if curl -L --fail --retry 3 --retry-delay 2 -o "$out_file" "$final_url"; then
    if [ -f "$out_file" ]; then
      if [ "$EXT" = "apkm" ]; then
        echo "Extracting base APK from .apkm ..." >&2
        bash scripts/extract_from_apkm.sh --apkm "$out_file" --out build/from_checker.apk || true
        if [ -f build/from_checker.apk ]; then
          apk_path="$(pwd)/build/from_checker.apk"
          note="downloaded_from_checker:apkm_extracted"
        fi
      elif [ "$EXT" = "apk" ]; then
        apk_path="$(pwd)/$out_file"
        note="downloaded_from_checker:apk"
      else
        # xapk unsupported unless forced elsewhere
        :
      fi
    fi
  fi
fi

# If only .xapk is available and no fallback, disable update unless forced
if [ "$package_type" = "xapk" ] && [ -z "$apk_path" ] && [ "$FORCE" != "true" ]; then
  has_update=false
  note="unsupported_package_type:xapk"
fi

jq -n \
  --argjson has_update "${has_update}" \
  --arg version "$version" \
  --arg release_url "${release_url:-}" \
  --arg variant_url "${variants_url:-}" \
  --arg download_page "${download_page_url}" \
  --arg download_url "${final_url}" \
  --arg package_type "${package_type}" \
  --arg note "${note}" \
  --arg apk_path "${apk_path}" \
  '{has_update:$has_update, version:$version, release_url:$release_url, variant_url:$variant_url, download_page:$download_page, download_url:$download_url, package_type:$package_type, note:$note, apk_path:$apk_path}' \
  > "$OUT"

echo "wrote $OUT"


