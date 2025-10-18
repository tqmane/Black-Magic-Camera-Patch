#!/usr/bin/env python3
import argparse
import os
import sys
import zipfile


def pick_apk_from_zip(z: zipfile.ZipFile) -> str:
    # Prefer base.apk; else pick the largest *.apk
    names = z.namelist()
    base = None
    apks = []
    for name in names:
        low = name.lower()
        if not low.endswith('.apk'):
            continue
        if os.path.basename(low) == 'base.apk':
            base = name
        try:
            info = z.getinfo(name)
            apks.append((info.file_size, name))
        except KeyError:
            pass
    if base:
        return base
    if not apks:
        return ''
    apks.sort(key=lambda t: t[0], reverse=True)
    return apks[0][1]


def main() -> int:
    parser = argparse.ArgumentParser(description='Extract a usable APK from an APKM (APKMirror) archive.')
    parser.add_argument('--apkm', required=True, help='Path to the .apkm file')
    parser.add_argument('--out', required=True, help='Output APK path')
    parser.add_argument('--workdir', default='build/apkm_extract')
    args = parser.parse_args()

    apkm_path = os.path.abspath(args.apkm)
    out_apk = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out_apk), exist_ok=True)

    if not os.path.isfile(apkm_path):
        print(f'ERROR: .apkm not found: {apkm_path}')
        return 2

    with zipfile.ZipFile(apkm_path, 'r') as z:
        pick = pick_apk_from_zip(z)
        if not pick:
            print('ERROR: No APK entries found inside .apkm')
            return 3
        z.extract(pick, args.workdir)
        extracted_path = os.path.join(args.workdir, pick)
        os.makedirs(os.path.dirname(out_apk), exist_ok=True)
        # Move/overwrite
        if os.path.abspath(extracted_path) != out_apk:
            os.replace(extracted_path, out_apk)

    print(out_apk)
    return 0


if __name__ == '__main__':
    sys.exit(main())


