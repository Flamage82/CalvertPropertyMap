#!/usr/bin/env python3
"""
Download map tiles for 306-354 Sipples Road, Calvert QLD
and save them to a local tiles/ directory for offline use.

Usage:
    python download-tiles.py                  # Download all providers, zoom 14-20
    python download-tiles.py --zoom 14 16     # Only zoom levels 14-16
    python download-tiles.py --provider satellite  # Only satellite tiles
    python download-tiles.py --provider qldaerial  # Only QLD aerial tiles
    python download-tiles.py --dry-run        # Show what would be downloaded
"""

import os
import sys
import math
import time
import argparse
import urllib.request
import urllib.error

# Wide bounds with generous buffer for viewport coverage at lower zoom levels
# The lot itself is roughly -27.670 to -27.674, 152.492 to 152.498
# We add ~1km buffer in each direction so the map never shows blank edges
BOUNDS_WIDE = {
    "minLat": -27.685,
    "maxLat": -27.658,
    "minLng": 152.478,
    "maxLng": 152.510,
}

# Tight bounds: lot + 200m buffer for high-zoom tiles (z19-22)
# The lot corners are roughly: NW(-27.6698, 152.4926) SE(-27.6740, 152.4988)
# 200m ≈ 0.0018° lat, 0.0020° lng at this latitude
LOT_BOUNDS_200M = {
    "minLat": -27.6758,  # south edge of lot - 200m
    "maxLat": -27.6680,  # north edge of lot + 200m
    "minLng": 152.4906,  # west edge of lot - 200m
    "maxLng": 152.5008,  # east edge of lot + 200m
}

PROVIDERS = {
    "carto": {
        "url": "https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png",
        "subdomains": ["a", "b", "c", "d"],
        "ext": "png",
        "max_native_zoom": 18,
    },
    "satellite": {
        "url": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        "subdomains": None,
        "ext": "jpg",
        "max_native_zoom": 18,
    },
    "topo": {
        "url": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
        "subdomains": None,
        "ext": "jpg",
        "max_native_zoom": 17,
    },
    "qldaerial": {
        "url": "https://spatial-img.information.qld.gov.au/arcgis/rest/services/Basemaps/LatestStateProgram_AllUsers/ImageServer/tile/{z}/{y}/{x}",
        "subdomains": None,
        "ext": "jpg",
        "max_native_zoom": 20,
    },
}

# Zoom 14-18: wide bounds, all providers
# Zoom 19-20: lot+200m bounds, all providers (only native tiles)
DEFAULT_ZOOM_LEVELS = list(range(14, 21))  # 14 through 20

# High-zoom threshold: above this zoom, use tight lot bounds
HIGH_ZOOM_THRESHOLD = 19


def lat2tile(lat, zoom):
    return int(
        math.floor(
            (1 - math.log(math.tan(lat * math.pi / 180) + 1 / math.cos(lat * math.pi / 180)) / math.pi)
            / 2
            * (2 ** zoom)
        )
    )


def lng2tile(lng, zoom):
    return int(math.floor((lng + 180) / 360 * (2 ** zoom)))


def get_tile_list(zoom_levels, providers):
    tiles = []
    for zoom in zoom_levels:
        # Use tight bounds for high zoom levels, wide bounds for lower
        if zoom >= HIGH_ZOOM_THRESHOLD:
            bounds = LOT_BOUNDS_200M
        else:
            bounds = BOUNDS_WIDE

        x_min = lng2tile(bounds["minLng"], zoom)
        x_max = lng2tile(bounds["maxLng"], zoom)
        y_min = lat2tile(bounds["maxLat"], zoom)
        y_max = lat2tile(bounds["minLat"], zoom)

        for x in range(x_min, x_max + 1):
            for y in range(y_min, y_max + 1):
                for name, p in providers.items():
                    # Skip zoom levels above native max for this provider
                    # (Leaflet handles upscaling in-browser, no need to cache upscaled tiles)
                    if zoom > p["max_native_zoom"]:
                        continue

                    if p["subdomains"]:
                        s = p["subdomains"][(x + y) % len(p["subdomains"])]
                        url = p["url"].replace("{s}", s)
                    else:
                        url = p["url"]
                    url = url.replace("{z}", str(zoom)).replace("{x}", str(x)).replace("{y}", str(y))
                    local_path = os.path.join("tiles", name, str(zoom), str(x), f"{y}.{p['ext']}")
                    tiles.append({"url": url, "path": local_path, "provider": name, "z": zoom, "x": x, "y": y})
    return tiles


def download_tiles(tiles, dry_run=False):
    total = len(tiles)
    downloaded = 0
    skipped = 0
    failed = 0

    print(f"{'[DRY RUN] ' if dry_run else ''}Downloading {total} tiles...")
    print()

    for i, t in enumerate(tiles):
        if os.path.exists(t["path"]):
            skipped += 1
            continue

        if dry_run:
            print(f"  Would download: {t['path']}")
            downloaded += 1
            continue

        os.makedirs(os.path.dirname(t["path"]), exist_ok=True)

        try:
            req = urllib.request.Request(t["url"], headers={"User-Agent": "BlockMap-TileDownloader/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                with open(t["path"], "wb") as f:
                    f.write(resp.read())
            downloaded += 1
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
            failed += 1
            print(f"  FAIL: {t['path']} — {e}")

        # Progress
        if (i + 1) % 20 == 0 or i == total - 1:
            pct = (i + 1) / total * 100
            print(f"  [{pct:5.1f}%] {i+1}/{total} — {downloaded} new, {skipped} existing, {failed} failed")

        # Rate limit: small delay every 10 downloads
        if downloaded > 0 and downloaded % 10 == 0:
            time.sleep(0.2)

    print()
    print(f"Done! {downloaded} downloaded, {skipped} already existed, {failed} failed.")

    # Calculate size
    total_size = 0
    for root, dirs, files in os.walk("tiles"):
        for f in files:
            total_size += os.path.getsize(os.path.join(root, f))
    if total_size > 0:
        print(f"Total tiles/ folder size: {total_size / (1024*1024):.1f} MB")


def main():
    parser = argparse.ArgumentParser(description="Download map tiles for offline use")
    parser.add_argument("--zoom", nargs=2, type=int, metavar=("MIN", "MAX"), help="Zoom level range (default: 14 20)")
    parser.add_argument("--provider", choices=list(PROVIDERS.keys()), help="Only download from this provider")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be downloaded without downloading")
    args = parser.parse_args()

    zoom_levels = list(range(args.zoom[0], args.zoom[1] + 1)) if args.zoom else DEFAULT_ZOOM_LEVELS
    providers = {args.provider: PROVIDERS[args.provider]} if args.provider else PROVIDERS

    tiles = get_tile_list(zoom_levels, providers)

    # Summarize per-provider per-zoom counts
    from collections import Counter
    counts = Counter((t["provider"], t["z"]) for t in tiles)

    print(f"Block: 306-354 Sipples Road, Calvert QLD")
    print(f"Wide bounds (z14-18): {BOUNDS_WIDE['minLat']:.3f},{BOUNDS_WIDE['minLng']:.3f} to {BOUNDS_WIDE['maxLat']:.3f},{BOUNDS_WIDE['maxLng']:.3f}")
    print(f"Lot bounds+200m (z19+): {LOT_BOUNDS_200M['minLat']:.4f},{LOT_BOUNDS_200M['minLng']:.4f} to {LOT_BOUNDS_200M['maxLat']:.4f},{LOT_BOUNDS_200M['maxLng']:.4f}")
    print(f"Zoom levels: {zoom_levels}")
    print(f"Providers: {', '.join(providers.keys())}")
    print()

    # Per-provider breakdown
    for pname in sorted(providers.keys()):
        p = providers[pname]
        ptiles = [c for (pr, z), c in counts.items() if pr == pname]
        ptotal = sum(ptiles)
        native = p["max_native_zoom"]
        print(f"  {pname}: {ptotal} tiles (native up to z{native})")
        for z in zoom_levels:
            if z <= native:
                c = counts.get((pname, z), 0)
                if c > 0:
                    label = "lot+200m" if z >= HIGH_ZOOM_THRESHOLD else "wide"
                    print(f"    z{z}: {c} tiles ({label})")

    print(f"\nTotal tiles to check: {len(tiles)}")
    print()

    download_tiles(tiles, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
