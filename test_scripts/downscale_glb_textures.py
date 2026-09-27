"""
Downscale the textures embedded in a .glb, in place of a Blender re-export.

Why
---
FreyaV2.glb ships two 4096x4096 JPEGs (baseColor 12.20 MB, normal 12.79 MB) plus
two 2048x2048 ones. At native resolution those four maps cost roughly 213 MB of
GPU memory once uploaded with mipmaps — for a portrait card that renders at about
280 CSS pixels tall. Under that pressure `createImageBitmap` intermittently fails
on one of the big blobs, which surfaces as:

    THREE.GLTFLoader: Couldn't load texture "blob:http://localhost:3000/..."

three.js swallows that rejection and assigns `null`, so the model still renders
with a map missing rather than failing outright — which is what made it look like
a random glitch instead of a resource problem.

What this does
--------------
Rewrites only the image bufferViews: every embedded texture is resized so its
longest edge is at most `--max-size`, re-encoded as JPEG, and the binary chunk is
rebuilt with corrected offsets. Geometry, animations, skins, materials and the
node graph are copied through untouched — accessors address their data as an
offset *within* a bufferView, and each view stays contiguous, so they stay valid.

Normal maps are re-encoded without chroma subsampling; subsampling averages the
colour channels, and in a normal map those channels are the X/Y of a vector, so
the usual JPEG shortcut shows up as visible shading artifacts.

Usage
-----
    python test_scripts/downscale_glb_textures.py freya-ui/public/models/FreyaV2.glb
    python test_scripts/downscale_glb_textures.py <glb> --max-size 2048 --quality 92
    python test_scripts/downscale_glb_textures.py <glb> --dry-run

The original is copied to <name>.orig.glb before anything is written, unless
--no-backup is passed.
"""

import argparse
import io
import json
import os
import shutil
import struct
import sys

from PIL import Image

JSON_CHUNK = 0x4E4F534A
BIN_CHUNK = 0x004E4942


def read_glb(path):
    """Split a .glb into its JSON chunk and its binary chunk."""
    with open(path, "rb") as f:
        magic, version, _total = struct.unpack("<III", f.read(12))
        if magic != 0x46546C67:
            raise SystemExit(f"{path} is not a .glb (bad magic)")
        if version != 2:
            raise SystemExit(f"{path} is glTF {version}; only version 2 is supported")
        gltf, binary = None, None
        while True:
            header = f.read(8)
            if len(header) < 8:
                break
            length, kind = struct.unpack("<II", header)
            data = f.read(length)
            if kind == JSON_CHUNK:
                gltf = json.loads(data.decode("utf-8"))
            elif kind == BIN_CHUNK:
                binary = data
    if gltf is None or binary is None:
        raise SystemExit(f"{path} is missing its JSON or BIN chunk")
    return gltf, binary


def pad4(n):
    return (4 - (n % 4)) % 4


def texture_roles(gltf):
    """Map image index -> the material slots that sample it, for reporting and
    so normal maps can be encoded differently from colour maps."""
    roles = {}
    textures = gltf.get("textures", [])
    for material in gltf.get("materials", []):
        slots = dict(material)
        slots.update(material.get("pbrMetallicRoughness", {}))
        for slot, value in slots.items():
            if isinstance(value, dict) and "index" in value:
                source = textures[value["index"]].get("source")
                if source is not None:
                    roles.setdefault(source, set()).add(slot)
    return roles


def resize_jpeg(data, max_size, quality, is_normal_map):
    """Return (new_bytes, before_wh, after_wh). Unchanged data if already small."""
    image = Image.open(io.BytesIO(data))
    before = image.size
    longest = max(image.size)
    if longest <= max_size:
        return None, before, before
    scale = max_size / longest
    target = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    image = image.convert("RGB").resize(target, Image.LANCZOS)
    out = io.BytesIO()
    image.save(
        out,
        format="JPEG",
        quality=quality,
        optimize=True,
        # A normal map's channels are vector components, not colour — averaging
        # them the way 4:2:0 does produces visible shading artifacts.
        subsampling=0 if is_normal_map else 2,
    )
    return out.getvalue(), before, target


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("glb", help="path to the .glb to rewrite")
    ap.add_argument("--max-size", type=int, default=1024,
                    help="longest edge any texture may keep (default: 1024)")
    ap.add_argument("--quality", type=int, default=90,
                    help="JPEG quality for re-encoded textures (default: 90)")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would change and write nothing")
    ap.add_argument("--no-backup", action="store_true",
                    help="skip writing <name>.orig.glb")
    args = ap.parse_args()

    gltf, binary = read_glb(args.glb)
    views = gltf.get("bufferViews", [])
    images = gltf.get("images", [])
    if len(gltf.get("buffers", [])) != 1:
        raise SystemExit("Expected a single embedded buffer; this .glb has "
                         f"{len(gltf.get('buffers', []))}")
    roles = texture_roles(gltf)

    replacements = {}   # bufferView index -> new bytes
    print(f"{os.path.basename(args.glb)}: {len(images)} embedded image(s), "
          f"capping at {args.max_size}px\n")
    for i, image in enumerate(images):
        view_index = image.get("bufferView")
        if view_index is None:
            print(f"  [{i}] {image.get('name')!r}: external URI, skipped")
            continue
        view = views[view_index]
        start = view.get("byteOffset", 0)
        data = binary[start:start + view["byteLength"]]
        slots = roles.get(i, set())
        is_normal = any("normal" in s.lower() for s in slots)
        new, before, after = resize_jpeg(data, args.max_size, args.quality, is_normal)
        label = ",".join(sorted(slots)) or "unused"
        if new is None:
            print(f"  [{i}] {image.get('name'):<9} {before[0]}x{before[1]} "
                  f"{len(data)/1048576:6.2f} MB  {label}  — already within cap")
            continue
        replacements[view_index] = new
        image["mimeType"] = "image/jpeg"
        print(f"  [{i}] {image.get('name'):<9} {before[0]}x{before[1]} -> "
              f"{after[0]}x{after[1]}   {len(data)/1048576:6.2f} MB -> "
              f"{len(new)/1048576:5.2f} MB  {label}"
              + ("  (no chroma subsampling)" if is_normal else ""))

    if not replacements:
        print("\nNothing to do — every texture is already within the cap.")
        return 0

    # Rebuild the binary chunk. Every view is laid out in index order, 4-byte
    # aligned, and its byteOffset rewritten; accessors address data relative to
    # their view, so keeping each view contiguous keeps them correct.
    out = bytearray()
    for index, view in enumerate(views):
        data = replacements.get(index)
        if data is None:
            start = view.get("byteOffset", 0)
            data = binary[start:start + view["byteLength"]]
        view["byteOffset"] = len(out)
        view["byteLength"] = len(data)
        out += data
        out += b"\x00" * pad4(len(out))
    gltf["buffers"][0]["byteLength"] = len(out)

    json_bytes = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    json_bytes += b" " * pad4(len(json_bytes))
    total = 12 + 8 + len(json_bytes) + 8 + len(out)

    before_size = os.path.getsize(args.glb)
    print(f"\n  file: {before_size/1048576:.1f} MB -> {total/1048576:.1f} MB "
          f"({100 * (1 - total / before_size):.0f}% smaller)")

    if args.dry_run:
        print("  --dry-run: nothing written.")
        return 0

    if not args.no_backup:
        backup = os.path.splitext(args.glb)[0] + ".orig.glb"
        if os.path.exists(backup):
            print(f"  backup already exists, left alone: {backup}")
        else:
            shutil.copy2(args.glb, backup)
            print(f"  backup: {backup}")

    tmp = args.glb + ".tmp"
    with open(tmp, "wb") as f:
        f.write(struct.pack("<III", 0x46546C67, 2, total))
        f.write(struct.pack("<II", len(json_bytes), JSON_CHUNK))
        f.write(json_bytes)
        f.write(struct.pack("<II", len(out), BIN_CHUNK))
        f.write(out)
    os.replace(tmp, args.glb)
    print(f"  wrote: {args.glb}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
