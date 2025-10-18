#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from typing import Optional, Tuple

import requests
from bs4 import BeautifulSoup


DEFAULT_APP_URL = (
    # App landing page (adjustable via --app-url)
    "https://www.apkmirror.com/apk/blackmagic-design/blackmagic-camera/"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36"
    )
}

# Reuse a session with retries to make APKMirror flow more robust
_SESSION: Optional[requests.Session] = None


def _get_session() -> requests.Session:
    global _SESSION
    if _SESSION is not None:
        return _SESSION
    s = requests.Session()
    s.headers.update(HEADERS)
    try:
        # Configure retries for transient network issues
        from urllib3.util.retry import Retry
        from requests.adapters import HTTPAdapter

        retry = Retry(
            total=5,
            connect=3,
            read=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET"],
        )
        adapter = HTTPAdapter(max_retries=retry)
        s.mount("http://", adapter)
        s.mount("https://", adapter)
    except Exception:
        # Best-effort; if unavailable, proceed without custom retries
        pass
    _SESSION = s
    return s


@dataclass
class LatestInfo:
    version: str
    release_url: str
    variant_url: Optional[str]
    download_url: Optional[str]


def _soup_get(url: str, referer: Optional[str] = None) -> BeautifulSoup:
    s = _get_session()
    headers = {}
    if referer:
        headers["Referer"] = referer
    resp = s.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "lxml")


def _find_latest_release_url(app_url: str) -> Tuple[str, str]:
    soup = _soup_get(app_url)
    # 1) Try new app page cards
    selectors = [
        'div.listWidget a.fontBlack[href*="/release/"]',
        'a.fontBlack[href*="/release/"]',
        'a[href*="/download/"], a[href*="/variant/"]',
    ]
    link = None
    for sel in selectors:
        link = soup.select_one(sel)
        if link and link.get("href"):
            break
    if not link or not link.get("href"):
        # 2) Fallback to all versions page
        all_versions = soup.find("a", href=True, string=lambda t: t and "All versions" in t)
        if all_versions:
            href = all_versions.get("href")
            versions_url = href if href.startswith("http") else ("https://www.apkmirror.com" + href)
            soup2 = _soup_get(versions_url)
            link = soup2.select_one('a.fontBlack[href*="/release/"]') or soup2.select_one('a[href*="/release/"]')
    if not link or not link.get("href"):
        raise RuntimeError("Could not locate latest release link on APKMirror app page.")
    href = link["href"]
    release_url = href if href.startswith("http") else ("https://www.apkmirror.com" + href)
    # Extract a readable version string from link text or URL
    version_text = link.get_text(strip=True) or ""
    version = version_text
    if not version:
        m = re.search(r"blackmagic-camera-([\w\.-]+)-release", release_url)
        version = m.group(1) if m else "unknown"
    return version, release_url


def _find_variants_page(release_url: str) -> Optional[str]:
    soup = _soup_get(release_url)
    # Look for "See available APKs"
    anchor = soup.find("a", string=lambda t: t and "available APKs" in t)
    if not anchor:
        # Sometimes directly lists variants on same page
        return release_url
    href = anchor.get("href")
    return href if href.startswith("http") else ("https://www.apkmirror.com" + href)


def _choose_preferred_variant(variants_url: str) -> Optional[str]:
    soup = _soup_get(variants_url)
    # Prefer APK (not bundle), arm64-v8a or universal, nodpi
    rows = soup.select(".table-row, tr")
    candidates = []
    for row in rows:
        text = row.get_text(" ", strip=True).lower()
        a = row.find("a", href=True)
        if not a:
            continue
        href = a["href"]
        if "variant" not in href and "apk/blackmagic-design/" not in href:
            continue
        # Filtering heuristics (allow bundle too so we can reach download page for .apkm)
        is_apk = "apk" in text
        arch_ok = ("arm64-v8a" in text) or ("universal" in text) or ("all" in text)
        dpi_ok = ("nodpi" in text) or ("all dpi" in text) or ("dpi" not in text)
        if is_apk and arch_ok:
            score = 0
            if "universal" in text:
                score += 3
            if "arm64-v8a" in text:
                score += 2
            if "nodpi" in text:
                score += 1
            candidates.append((score, href))
    if not candidates:
        # fallback: first link on the page
        a = soup.select_one("a[href*='/apk/blackmagic-design/blackmagic-camera/']")
        if not a:
            return None
        href = a["href"]
        return href if href.startswith("http") else ("https://www.apkmirror.com" + href)
    # pick best score
    candidates.sort(key=lambda x: x[0], reverse=True)
    href = candidates[0][1]
    return href if href.startswith("http") else ("https://www.apkmirror.com" + href)


def _find_download_page(variant_url: str) -> Optional[str]:
    soup = _soup_get(variant_url)
    # Look for Download APK or Download APK Bundle button
    a = soup.find("a", string=lambda t: t and ("download apk" in t.lower() or "download apk bundle" in t.lower()))
    if not a:
        # Sometimes the button has an id or class
        a = soup.select_one("a.downloadButton, a.btn.btn-flat.downloadButton")
    if not a:
        # fallback: any link containing /download/
        a = soup.find("a", href=lambda h: h and "/download/" in h)
    if not a:
        return None
    href = a.get("href")
    if not href:
        return None
    return href if href.startswith("http") else ("https://www.apkmirror.com" + href)


def _resolve_final_download(download_page_url: str) -> Optional[str]:
    """Try to resolve the final direct download URL for APK/APKM/XAPK.

    APKMirror often uses a two-step flow: variant page -> download page ->
    a button pointing to dl.apkmirror.com or download.php which then redirects
    to the actual CDN URL. We keep cookies and set Referer headers properly.
    """
    s = _get_session()
    soup = _soup_get(download_page_url)

    # Prefer explicit nofollow button first
    link = soup.find("a", {"rel": "nofollow"}, href=True)
    if not link:
        # heuristic: any link with download.php or dl.apkmirror.com
        link = soup.find("a", href=lambda h: h and ("download.php" in h or "dl.apkmirror.com" in h))
    if not link:
        # fallback: any button-like link
        link = soup.select_one("a.btn, a.button, a.downloadButton")
    if not link or not link.get("href"):
        return None

    first_url = link["href"]
    if not first_url.startswith("http"):
        first_url = "https://www.apkmirror.com" + first_url

    # Try a short chain of requests capturing redirects, with Referer set
    current = first_url
    referer = download_page_url
    for _ in range(5):
        try:
            r = s.get(current, headers={"Referer": referer}, allow_redirects=False, timeout=30)
        except Exception:
            break
        # If we already got a binary response, stop and use r.url
        ct = (r.headers.get("Content-Type") or "").lower()
        cd = (r.headers.get("Content-Disposition") or "").lower()
        if ("application/vnd.android.package-archive" in ct) or ("application/octet-stream" in ct) or (".apk" in cd) or (".apkm" in cd) or (".xapk" in cd):
            return r.url
        # Follow Location header manually
        loc = r.headers.get("Location")
        if not loc:
            # As a fallback, allow redirects once to resolve r.url
            try:
                r2 = s.get(current, headers={"Referer": referer}, allow_redirects=True, stream=True, timeout=30)
                ct2 = (r2.headers.get("Content-Type") or "").lower()
                cd2 = (r2.headers.get("Content-Disposition") or "").lower()
                if ("application/vnd.android.package-archive" in ct2) or ("application/octet-stream" in ct2) or (".apk" in cd2) or (".apkm" in cd2) or (".xapk" in cd2):
                    return r2.url
                # If it looks like a final HTML without binary, break
                break
            except Exception:
                break
        # Absolute URL for next hop
        if not loc.startswith("http"):
            # Some redirects are relative to dl.apkmirror.com
            from urllib.parse import urljoin
            loc = urljoin(current, loc)
        referer = current
        current = loc

    return current


def _download_file(url: str, out_path: str, referer: Optional[str] = None) -> None:
    s = _get_session()
    headers = {}
    if referer:
        headers["Referer"] = referer
    with s.get(url, headers=headers, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 512):
                if chunk:
                    f.write(chunk)


def _github_release_exists(tag: str) -> bool:
    repo = os.environ.get("GITHUB_REPOSITORY")
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not repo or not token:
        # If we cannot check, assume not existing, so we proceed
        return False
    api = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
    resp = requests.get(api, headers={"Authorization": f"Bearer {token}", **HEADERS}, timeout=30)
    if resp.status_code == 200:
        return True
    if resp.status_code == 404:
        return False
    # On other errors, be conservative
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Check APKMirror for Blackmagic Camera updates and download latest APK.")
    parser.add_argument("--app-url", default=os.environ.get("APKMIRROR_APP_URL", DEFAULT_APP_URL))
    parser.add_argument("--out", default="build/latest.json")
    parser.add_argument("--download-out", default="build/latest.apk")
    parser.add_argument("--fallback-apk", default="")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--skip-release-check", action="store_true")
    args = parser.parse_args()

    os.makedirs(os.path.dirname(args.out), exist_ok=True)

    try:
        version, release_url = _find_latest_release_url(args.app_url)
        variants_url = _find_variants_page(release_url) or release_url
        variant_url = _choose_preferred_variant(variants_url)
        download_page = _find_download_page(variant_url) if variant_url else None
        final_url = _resolve_final_download(download_page) if download_page else None
    except Exception as e:
        data = {"has_update": False, "error": str(e)}
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        print(f"ERROR: {e}")
        return 0

    tag = f"blackmagic-{version}"
    exists = False if args.skip_release_check else _github_release_exists(tag)
    has_update = not exists

    apk_path = ""
    package_type = "unknown"
    if final_url:
        url_lower = final_url.split("?")[0].lower()
        if url_lower.endswith(".apk"):
            package_type = "apk"
        elif url_lower.endswith(".apkm"):
            package_type = "apkm"
        elif url_lower.endswith(".xapk"):
            package_type = "xapk"

    # Attempt to download both APK and APKM (we can extract APKM later)
    if has_update and final_url and package_type in ("apk", "apkm"):
        try:
            out_path = args.download_out
            if package_type == "apkm":
                base, _ = os.path.splitext(args.download_out)
                out_path = base + ".apkm"
            _download_file(final_url, out_path)
            # crude validation
            if os.path.getsize(out_path) < 1024 * 1024:
                raise RuntimeError("Downloaded file too small, likely not an APK.")
            apk_path = out_path
        except Exception as e:
            print(f"WARN: Failed to download APK: {e}")
            apk_path = ""

    # Fallbacks
    if (not apk_path) and args.fallback_apk and os.path.isfile(args.fallback_apk):
        apk_path = os.path.abspath(args.fallback_apk)
        # If user provided a fallback and wants to force, allow proceeding even if release existed
        has_update = True if args.force else has_update

    note = ""
    # If we couldn't obtain an APK and we're not forcing, avoid marking as update to prevent CI failure
    if not apk_path and not args.force:
        if package_type in ("xapk",):
            has_update = False
            note = f"unsupported_package_type:{package_type}"
        elif package_type in ("apkm", "apk"):
            # Could not download or resolve
            has_update = False
            note = f"download_unresolved:{package_type}"

    payload = {
        "has_update": bool(has_update),
        "version": version,
        "release_url": release_url,
        "variant_url": variant_url,
        "download_page": download_page,
        "download_url": final_url,
        "package_type": package_type,
        "note": note,
        "apk_path": apk_path,
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    print(json.dumps(payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())


