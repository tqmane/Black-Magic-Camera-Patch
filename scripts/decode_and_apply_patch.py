#!/usr/bin/env python3
import argparse
import os
import shutil
import subprocess
import sys


def run(cmd, cwd=None):
    print(f"$ {' '.join(cmd)}")
    subprocess.check_call(cmd, cwd=cwd)


def main() -> int:
    parser = argparse.ArgumentParser(description="Decode APK with apktool and apply repo patch.")
    parser.add_argument("--apk", required=True)
    parser.add_argument("--apktool", default="./apktool.jar")
    parser.add_argument("--workdir", default="build/work")
    parser.add_argument("--patch-file", default="blackmagic_mod.patch")
    args = parser.parse_args()

    workdir = os.path.abspath(args.workdir)
    decoded_dir = os.path.join(workdir, "decoded_apk")
    os.makedirs(workdir, exist_ok=True)

    # Validate inputs
    apk_path = os.path.abspath(args.apk)
    if not os.path.isfile(apk_path):
        print(f"ERROR: APK not found: {apk_path}")
        return 2

    apktool_path = os.path.abspath(args.apktool)
    if not os.path.isfile(apktool_path):
        # Try to download apktool.jar locally
        try:
            import urllib.request
            url = "https://github.com/iBotPeaches/Apktool/releases/download/v2.9.3/apktool_2.9.3.jar"
            print(f"apktool.jar not found. Downloading {url} ...")
            urllib.request.urlretrieve(url, apktool_path)
        except Exception as e:
            print(f"ERROR: apktool.jar not found and auto-download failed: {e}")
            return 2

    # Clean previous
    if os.path.exists(decoded_dir):
        shutil.rmtree(decoded_dir)

    # Decode
    run(["java", "-jar", apktool_path, "d", "-f", apk_path, "-o", decoded_dir])

    # Apply patch (targets decoded_apk paths)
    patch_path = os.path.abspath(args.patch_file)
    # Record a copy of baseline manifest for debugging
    try:
        shutil.copyfile(patch_path, os.path.join(workdir, "applied_patch.diff"))
    except Exception:
        pass

    # Use 'git apply' if available, else fallback to 'patch'
    try:
        run(["git", "apply", "--unsafe-paths", patch_path], cwd=workdir)
    except Exception:
        # Fallback: patch -p1 in workdir
        run(["patch", "-p1", "-i", patch_path], cwd=workdir)

    # Quick existence check of a few known-edited files
    touched = [
        os.path.join(decoded_dir, "AndroidManifest.xml"),
        os.path.join(decoded_dir, "smali", "com", "blackmagicdesign", "android", "camera", "domain", "k.smali"),
    ]
    for path in touched:
        if not os.path.exists(path):
            print(f"WARN: Expected modified file missing: {path}")

    print(f"Decoded into: {decoded_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())


