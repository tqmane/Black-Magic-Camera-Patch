#!/usr/bin/env python3
import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime


def run(cmd, cwd=None):
    print(f"$ {' '.join(cmd)}")
    subprocess.check_call(cmd, cwd=cwd)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build, align, and optionally sign the modded APK.")
    parser.add_argument("--decoded", required=True)
    parser.add_argument("--dist", default="dist")
    parser.add_argument("--zipalign", required=True)
    parser.add_argument("--apksigner", required=True)
    parser.add_argument("--keystore", default="build/blackmagic.keystore")
    parser.add_argument("--key-alias", default="")
    parser.add_argument("--keystore-pass", default="")
    parser.add_argument("--key-pass", default="")
    parser.add_argument("--version", default="")
    parser.add_argument("--maybe-unsigned", action="store_true", help="if set and keystore missing, skip signing")
    args = parser.parse_args()

    decoded_dir = os.path.abspath(args.decoded)
    dist_dir = os.path.abspath(args.dist)
    os.makedirs(dist_dir, exist_ok=True)

    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    version_tag = args.version or timestamp

    unsigned_apk = os.path.join(dist_dir, f"Blackmagic_Camera_mod_unsigned_{version_tag}.apk")
    aligned_apk = os.path.join(dist_dir, f"Blackmagic_Camera_mod_unsigned_aligned_{version_tag}.apk")
    signed_apk = os.path.join(dist_dir, f"Blackmagic_Camera_mod_signed_{version_tag}.apk")

    # Build with apktool
    # The repo expects apktool.jar at repo root; use it via java -jar
    apktool_jar = os.path.abspath("apktool.jar")
    run(["java", "-jar", apktool_jar, "b", decoded_dir, "-o", unsigned_apk])

    # zipalign
    run([args.zipalign, "-p", "-f", "4096", unsigned_apk, aligned_apk])

    # Sign if keystore present and configured
    keystore_exists = os.path.isfile(args.keystore)
    can_sign = keystore_exists and args.key_alias and args.keystore_pass and args.key_pass
    if can_sign:
        run([
            args.apksigner,
            "sign",
            "--ks", args.keystore,
            "--ks-key-alias", args.key_alias,
            "--ks-pass", f"pass:{args.keystore_pass}",
            "--key-pass", f"pass:{args.key_pass}",
            "--out", signed_apk,
            aligned_apk,
        ])
        print(f"Signed APK: {signed_apk}")
    else:
        if not args.maybe-unsigned:
            print("ERROR: Keystore not provided or incomplete. Set --maybe-unsigned to skip signing.")
            return 2
        print("Signing skipped. Output is unsigned aligned APK.")

    return 0


if __name__ == "__main__":
    sys.exit(main())


