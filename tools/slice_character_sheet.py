"""Slice the official Mors artwork into named, transparent sprites.

Inputs
    assets/character/character_sheet.jpeg : official Ai.Mors expression sheet
    assets/character/face_grid.jpeg       : official abstract face/eye sheet

Outputs
    frontend/public/mors/<state>.png      : expression sprites + hero + poses
    frontend/public/mors/face/<n>.png     : abstract mini-faces
    assets/character/sprite_map.json      : manifest consumed by the UI

Method
    1. connected components on "not background"
    2. big blobs  -> sprites, small blobs -> decorations or caption text
    3. caption rows are detected as horizontal runs of small text-like blobs
       so the sprite crop can grow *upward* (to keep "?", "zZz", motion marks)
       without ever swallowing the printed label underneath
    4. background removal = flood fill from the image border only, so the
       near-white helmet panels (almost the same colour as the sheet
       background) stay opaque
"""

from __future__ import annotations

import json
import sys
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SHEET = ROOT / "assets" / "character" / "character_sheet.jpeg"
FACE_GRID = ROOT / "assets" / "character" / "face_grid.jpeg"
OUT_DIR = ROOT / "frontend" / "public" / "mors"
FACE_OUT = OUT_DIR / "face"

BG_TOL = 16
SPRITE_MIN_AREA = 1500
DECOR_MIN_AREA = 25
MAX_SPRITE_EDGE = 700

ROW1 = ["neutral", "happy", "excited", "sad", "angry"]
ROW2 = ["confused", "wink", "surprised", "love", "tired"]
ROW3 = ["smug", "crying", "shocked", "thinking", "cool"]
ROW4 = ["mischievous", "peaceful", "overwhelmed", "hype"]
POSES = ["front", "side", "back", "fly"]


# --------------------------------------------------------------------------- #
# detection
# --------------------------------------------------------------------------- #
def background_color(arr: np.ndarray) -> np.ndarray:
    flat = arr.reshape(-1, 3)
    colors, counts = np.unique(flat, axis=0, return_counts=True)
    return colors[counts.argmax()]


def components(mask: np.ndarray) -> list[dict]:
    h, w = mask.shape
    seen = np.zeros((h, w), dtype=bool)
    out: list[dict] = []
    for y in range(h):
        for x in range(w):
            if not mask[y, x] or seen[y, x]:
                continue
            q = deque([(y, x)])
            seen[y, x] = True
            min_y = max_y = y
            min_x = max_x = x
            area = 0
            while q:
                cy, cx = q.popleft()
                area += 1
                min_y = min(min_y, cy)
                max_y = max(max_y, cy)
                min_x = min(min_x, cx)
                max_x = max(max_x, cx)
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        ny, nx = cy + dy, cx + dx
                        if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                            seen[ny, nx] = True
                            q.append((ny, nx))
            out.append(
                {
                    "x": min_x,
                    "y": min_y,
                    "w": max_x - min_x + 1,
                    "h": max_y - min_y + 1,
                    "area": area,
                }
            )
    return out


def caption_bands(parts: list[dict]) -> list[tuple[int, int]]:
    """Horizontal bands occupied by the printed labels under each sprite."""
    text = [
        p
        for p in parts
        if DECOR_MIN_AREA <= p["area"] <= SPRITE_MIN_AREA and 7 <= p["h"] <= 26 and p["w"] <= 70
    ]
    if not text:
        return []
    text.sort(key=lambda p: p["y"] + p["h"] / 2)
    bands: list[list[dict]] = [[text[0]]]
    for p in text[1:]:
        centre = p["y"] + p["h"] / 2
        prev = bands[-1]
        pc = sum(q["y"] + q["h"] / 2 for q in prev) / len(prev)
        if abs(centre - pc) <= 9:
            prev.append(p)
        else:
            bands.append([p])
    out: list[dict] = []
    for group in bands:
        letters = [p for p in group if p["w"] <= 70]
        if len(letters) < 4:
            continue
        out.append(
            {
                "y0": min(p["y"] for p in letters),
                "y1": max(p["y"] + p["h"] for p in letters),
                "x0": min(p["x"] for p in letters),
                "x1": max(p["x"] + p["w"] for p in letters),
            }
        )
    out.sort(key=lambda b: b["y0"])
    return out


def safe_top(box: dict, bands: list[dict], headroom: int) -> int:
    """Highest we may crop to, stopping at the caption line printed above."""
    top = box["y"] - headroom
    for b in bands:
        if b["y1"] > box["y"]:
            continue
        if box["y"] - b["y1"] > headroom + 24:
            continue
        if b["x1"] + 24 < box["x"] or b["x0"] - 24 > box["x"] + box["w"]:
            continue
        top = max(top, b["y1"] + 3)
    return max(0, top)


def merge_decorations(box: dict, parts: list[dict], bands: list[dict], headroom: int = 46, decor: bool = True) -> dict:
    """Grow a sprite box to include its own floating decorations."""
    limit = safe_top(box, bands, headroom)
    x0, y0 = box["x"], box["y"]
    x1, y1 = box["x"] + box["w"], box["y"] + box["h"]
    for p in parts if decor else ():
        if p["area"] >= SPRITE_MIN_AREA:
            continue
        if p["y"] > box["y"] + box["h"]:
            continue
        if p["y"] + p["h"] < limit:
            continue
        if p["x"] + p["w"] < box["x"] - 30 or p["x"] > box["x"] + box["w"] + 30:
            continue
        if any(b["y0"] - 3 <= p["y"] <= b["y1"] + 3 for b in bands):
            continue
        x0 = min(x0, p["x"] - 6)
        y0 = min(y0, p["y"] - 6)
        x1 = max(x1, p["x"] + p["w"] + 6)
        y1 = max(y1, p["y"] + p["h"] + 6)
    y0 = min(max(y0, limit), box["y"])
    return {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}


def clip_against_neighbours(box: dict, sprites: list[dict]) -> dict:
    x0, y0 = box["x"], box["y"]
    x1, y1 = box["x"] + box["w"], box["y"] + box["h"]
    for o in sprites:
        ox0, oy0 = o["x"] - 4, o["y"] - 4
        ox1, oy1 = o["x"] + o["w"] + 4, o["y"] + o["h"] + 4
        if not (y0 < oy1 and y1 > oy0 and x0 < ox1 and x1 > ox0):
            continue
        if oy0 >= box["y"] + box["h"]:
            y1 = min(y1, oy0)
        elif oy1 <= box["y"]:
            y0 = max(y0, oy1)
        elif ox0 >= box["x"] + box["w"]:
            x1 = min(x1, ox0)
        elif ox1 <= box["x"]:
            x0 = max(x0, ox1)
    return {"x": max(0, x0), "y": max(0, y0), "w": max(1, x1 - max(0, x0)), "h": max(1, y1 - max(0, y0))}


# --------------------------------------------------------------------------- #
# background removal + crop
# --------------------------------------------------------------------------- #
def remove_border_background(img: Image.Image, bg: np.ndarray) -> Image.Image:
    rgb = np.asarray(img.convert("RGB")).astype(np.int16)
    h, w, _ = rgb.shape
    close = np.abs(rgb - bg.astype(np.int16)).max(axis=2) <= BG_TOL
    cut = np.zeros((h, w), dtype=bool)
    q: deque[tuple[int, int]] = deque()
    for x in range(w):
        for y in (0, h - 1):
            if close[y, x]:
                cut[y, x] = True
                q.append((y, x))
    for y in range(h):
        for x in (0, w - 1):
            if close[y, x] and not cut[y, x]:
                cut[y, x] = True
                q.append((y, x))
    while q:
        cy, cx = q.popleft()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = cy + dy, cx + dx
            if 0 <= ny < h and 0 <= nx < w and close[ny, nx] and not cut[ny, nx]:
                cut[ny, nx] = True
                q.append((ny, nx))
    rgba = np.dstack([np.asarray(img.convert("RGB")), np.where(cut, 0, 255).astype(np.uint8)])
    return Image.fromarray(rgba, "RGBA")


def emit(name: str, sheet: Image.Image, bg: np.ndarray, box: dict, manifest: dict) -> None:
    x0, y0 = max(0, box["x"]), max(0, box["y"])
    x1 = min(sheet.width, box["x"] + box["w"])
    y1 = min(sheet.height, box["y"] + box["h"])
    sprite = remove_border_background(sheet.crop((x0, y0, x1, y1)), bg)
    if max(sprite.size) > 420:
        ratio = 420 / max(sprite.size)
        sprite = sprite.resize(
            (max(1, round(sprite.width * ratio)), max(1, round(sprite.height * ratio))),
            Image.LANCZOS,
        )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sprite.save(OUT_DIR / f"{name}.png", optimize=True)
    manifest[name] = {"file": f"/mors/{name}.png", "w": sprite.width, "h": sprite.height}
    print(f"  {name:14s} {sprite.size}")


# --------------------------------------------------------------------------- #
def slice_sheet() -> dict:
    sheet = Image.open(SHEET).convert("RGB")
    arr = np.asarray(sheet)
    bg = background_color(arr)
    mask = np.abs(arr.astype(np.int16) - bg.astype(np.int16)).max(axis=2) > BG_TOL
    parts = components(mask)
    bands = caption_bands(parts)
    print(f"sheet={sheet.size} parts={len(parts)} caption_bands={bands}")

    sprites = [
        p
        for p in parts
        if p["area"] > SPRITE_MIN_AREA
        and p["w"] > 60
        and p["h"] > 60
        and p["w"] < MAX_SPRITE_EDGE
    ]
    sprites.sort(key=lambda r: (round(r["y"] / 60), r["x"]))

    hero = max((s for s in sprites if s["y"] < 400 and s["x"] < 340), key=lambda s: s["area"])
    bands_grid: dict[str, list[dict]] = {}
    for name, band in (
        ("row1", (170, 350)),
        ("row2", (380, 570)),
        ("row3", (575, 765)),
        ("row4", (770, 955)),
        ("turn", (955, 1190)),
    ):
        lo, hi = band
        rows = [s for s in sprites if lo <= s["y"] < hi and s is not hero]
        if name == "turn":
            rows = [s for s in rows if s["h"] > 120 and s["w"] < 300]
        bands_grid[name] = sorted(rows, key=lambda s: s["x"])

    groups = [
        ("row1", ROW1),
        ("row2", ROW2),
        ("row3", ROW3),
        ("row4", ROW4),
        ("turn", POSES),
    ]
    planned: dict[str, dict] = {"hero": merge_decorations(hero, parts, bands)}
    for key, names in groups:
        rows = bands_grid[key]
        if len(rows) != len(names):
            raise SystemExit(f"{key}: expected {len(names)} sprites, detected {len(rows)}")
        tight = key == "turn"
        for name, box in zip(names, rows):
            planned[name] = merge_decorations(
                box, parts, bands, headroom=8 if tight else 46, decor=not tight
            )

    all_sprites = list(planned.values())
    manifest: dict[str, dict] = {}
    for name, box in planned.items():
        emit(name, sheet, bg, clip_against_neighbours(box, all_sprites), manifest)
    return manifest


def slice_faces() -> dict[str, dict]:
    img = Image.open(FACE_GRID).convert("RGB")
    arr = np.asarray(img)
    bg = background_color(arr)
    FACE_OUT.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, dict] = {}
    cols, rows = 3, 4
    cw, ch = img.width // cols, img.height // rows
    idx = 0
    for r in range(rows):
        for c in range(cols):
            idx += 1
            face = remove_border_background(img.crop((c * cw, r * ch, c * cw + cw, r * ch + ch)), bg)
            name = f"face-{idx:02d}"
            face.save(FACE_OUT / f"{name}.png", optimize=True)
            manifest[name] = {"file": f"/mors/face/{name}.png", "w": face.width, "h": face.height}
    print(f"  faces: {idx}")
    return manifest


def main() -> int:
    for path in (SHEET, FACE_GRID):
        if not path.exists():
            print(f"missing asset: {path}", file=sys.stderr)
            return 1
    print("slicing character sheet ...")
    manifest = slice_sheet()
    print("slicing face grid ...")
    manifest["faces"] = slice_faces()
    (ROOT / "assets" / "character" / "sprite_map.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"manifest -> {len(manifest)} entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

