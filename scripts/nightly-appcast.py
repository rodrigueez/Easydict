#!/usr/bin/env python3
"""Update the Sparkle appcast for the Easydict nightly channel.

Signs the given zip with the Sparkle Ed25519 key and prepends a new
appcast <item> entry. Version metadata (build number, short version,
minimum macOS) is read from the zip's embedded Info.plist so it always
matches the artifact actually shipped.
"""

import argparse
import os
import plistlib
import re
import subprocess
import zipfile
from datetime import datetime, timedelta, timezone


RSS_HEADER = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<rss xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle" version="2.0">\n'
    "    <channel>\n"
    "        <title>Easydict Nightly</title>\n"
)
RSS_FOOTER = "    </channel>\n</rss>\n"

ITEM_RE = re.compile(r"<item>.*?</item>", re.DOTALL)
VERSION_RE = re.compile(r"<sparkle:version>(.*?)</sparkle:version>", re.DOTALL)


def rfc822_now():
    now = datetime.now(timezone(timedelta(hours=8)))
    return now.strftime("%a, %d %b %Y %H:%M:%S %z")


def read_app_info(zip_path):
    with zipfile.ZipFile(zip_path) as zf:
        # The zip may contain nested bundles (e.g. Firebase) that also have
        # Contents/Info.plist; the top-level app bundle is the shallowest.
        candidates = [n for n in zf.namelist() if n.endswith("Contents/Info.plist")]
        info_name = min(candidates, key=lambda n: n.count("/"))
        with zf.open(info_name) as fh:
            info = plistlib.load(fh)
    return (
        str(info["CFBundleVersion"]),
        str(info["CFBundleShortVersionString"]),
        str(info.get("LSMinimumSystemVersion", "13.0")),
    )


def sign_zip(sign_update, key_file, zip_path):
    proc = subprocess.run(
        [sign_update, "--ed-key-file", key_file, "-p", zip_path],
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def build_item(download_url, notes_url, build, short_version, min_os, signature, length):
    return (
        "        <item>\n"
        f"            <title>{short_version}</title>\n"
        f"            <pubDate>{rfc822_now()}</pubDate>\n"
        f"            <sparkle:version>{build}</sparkle:version>\n"
        f"            <sparkle:shortVersionString>{short_version}</sparkle:shortVersionString>\n"
        f"            <sparkle:releaseNotesLink>{notes_url}</sparkle:releaseNotesLink>\n"
        f"            <sparkle:minimumSystemVersion>{min_os}</sparkle:minimumSystemVersion>\n"
        f'            <enclosure url="{download_url}" length="{length}" '
        f'type="application/octet-stream" sparkle:edSignature="{signature}"/>\n'
        "        </item>\n"
    )


def extract_items(appcast_text):
    return ITEM_RE.findall(appcast_text or "")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--zip", required=True)
    ap.add_argument("--download-url", required=True)
    ap.add_argument("--notes-url", required=True)
    ap.add_argument("--sign-update", required=True)
    ap.add_argument("--key-file", required=True)
    ap.add_argument("--prev", help="previous appcast.xml, optional")
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-items", type=int, default=10)
    args = ap.parse_args()

    build, short_version, min_os = read_app_info(args.zip)
    signature = sign_zip(args.sign_update, args.key_file, args.zip)
    length = os.path.getsize(args.zip)

    new_item = build_item(
        args.download_url, args.notes_url, build, short_version, min_os,
        signature, length,
    )

    prev_text = None
    if args.prev and os.path.exists(args.prev):
        with open(args.prev, encoding="utf-8") as fh:
            prev_text = fh.read()

    items = [
        item for item in extract_items(prev_text)
        if build not in VERSION_RE.search(item).group(1)
    ]
    items.insert(0, new_item)
    items = items[: args.max_items]

    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(RSS_HEADER)
        fh.writelines(items)
        fh.write(RSS_FOOTER)

    print(f"appcast written: {args.out} ({len(items)} items, build {build})")


if __name__ == "__main__":
    main()
