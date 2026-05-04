"""Generate the app icon at multiple sizes (PNG) plus a Windows .ico.

Run once: `python3 packaging/make_icon.py`
Output goes into src/es_snap_mon/data/.
"""
from __future__ import annotations
from pathlib import Path
from PIL import Image, ImageDraw

OUT_DIR = Path(__file__).resolve().parents[1] / "src" / "es_snap_mon" / "data"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Color palette (matches the app's accents)
BG_TOP = (30, 41, 59)       # slate-800
BG_BOT = (15, 23, 42)       # slate-900
ACCENT = (52, 152, 219)     # blue
WARN = (243, 156, 18)       # orange
GOOD = (46, 204, 113)       # green
WHITE = (255, 255, 255)


def _gradient(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), BG_BOT + (255,))
    for y in range(size):
        t = y / max(size - 1, 1)
        r = int(BG_TOP[0] + (BG_BOT[0] - BG_TOP[0]) * t)
        g = int(BG_TOP[1] + (BG_BOT[1] - BG_TOP[1]) * t)
        b = int(BG_TOP[2] + (BG_BOT[2] - BG_TOP[2]) * t)
        for x in range(size):
            img.putpixel((x, y), (r, g, b, 255))
    return img


def _rounded_mask(size: int, radius_ratio: float = 0.22) -> Image.Image:
    radius = int(size * radius_ratio)
    mask = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(mask)
    d.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
    return mask


def make_icon(size: int) -> Image.Image:
    bg = _gradient(size)
    mask = _rounded_mask(size)

    # Apply rounded corners
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(bg, (0, 0), mask)

    d = ImageDraw.Draw(out)

    # Stack of 3 "snapshot disks" (horizontal pill bars)
    bar_h = max(int(size * 0.13), 4)
    bar_gap = max(int(size * 0.06), 2)
    bar_w = int(size * 0.62)
    x0 = (size - bar_w) // 2
    total_h = bar_h * 3 + bar_gap * 2
    y_top = (size - total_h) // 2

    colors = [GOOD, WARN, ACCENT]
    for i, col in enumerate(colors):
        y = y_top + i * (bar_h + bar_gap)
        d.rounded_rectangle(
            (x0, y, x0 + bar_w, y + bar_h),
            radius=bar_h // 2,
            fill=col + (255,),
        )
        # Subtle highlight on top
        d.line(
            (x0 + bar_h // 2, y + 1, x0 + bar_w - bar_h // 2, y + 1),
            fill=(255, 255, 255, 110),
            width=max(1, size // 128),
        )

    # Tiny "progress dot" on the active (middle) layer
    dot_r = max(int(size * 0.04), 2)
    cx = x0 + bar_w - bar_h
    cy = y_top + (bar_h + bar_gap) + bar_h // 2
    d.ellipse(
        (cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r),
        fill=WHITE + (255,),
    )

    return out


def main():
    sizes = [16, 24, 32, 48, 64, 128, 256, 512]
    images = {s: make_icon(s) for s in sizes}

    # Save individual PNGs (we ship 256 + 64 for runtime use)
    images[256].save(OUT_DIR / "icon.png", "PNG")
    images[64].save(OUT_DIR / "icon-64.png", "PNG")

    # Also ship 48 + 32 for Linux .desktop integration
    images[48].save(OUT_DIR / "icon-48.png", "PNG")
    images[32].save(OUT_DIR / "icon-32.png", "PNG")

    # Windows .ico (multi-size)
    images[256].save(
        OUT_DIR / "icon.ico",
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(f"Icons written to {OUT_DIR}")


if __name__ == "__main__":
    main()
