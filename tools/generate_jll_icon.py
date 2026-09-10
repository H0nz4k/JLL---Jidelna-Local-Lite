"""Generate packaging/windows/jll.ico (multi-size) for EXE / Inno / ARP."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "packaging" / "windows" / "jll.ico"
PREVIEW = ROOT / "packaging" / "windows" / "jll_icon_preview.png"
ACCENT = (30, 90, 132, 255)  # theme accent #1E5A84
WHITE = (255, 255, 255, 255)
SIZES = (16, 24, 32, 48, 64, 128, 256)


def _font(size: int) -> ImageFont.ImageFont:
    for candidate in (
        Path(r"C:\Windows\Fonts\segoeuib.ttf"),
        Path(r"C:\Windows\Fonts\arialbd.ttf"),
        Path(r"C:\Windows\Fonts\arial.ttf"),
    ):
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), max(8, int(size * 0.38)))
    return ImageFont.load_default()


def make(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    margin = max(1, size // 16)
    radius = max(2, size // 5)
    draw.rounded_rectangle(
        (margin, margin, size - margin - 1, size - margin - 1),
        radius=radius,
        fill=ACCENT,
    )
    if size >= 32:
        r = max(2, size // 10)
        cx = size - margin - r - size // 12
        cy = margin + r + size // 14
        draw.ellipse(
            (cx - r, cy - r, cx + r, cy + r),
            outline=WHITE,
            width=max(1, size // 48),
        )
        draw.ellipse(
            (cx - r // 2, cy - r // 2, cx + r // 2, cy + r // 2),
            fill=WHITE,
        )
    text = "JLL"
    font = _font(size)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (size - tw) / 2 - bbox[0]
    y = (size - th) / 2 - bbox[1] + size * 0.02
    draw.text((x, y), text, font=font, fill=WHITE)
    return img


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    largest = make(256)
    largest.save(OUT, format="ICO", sizes=[(s, s) for s in SIZES])
    largest.save(PREVIEW, format="PNG")
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")
    print(f"wrote {PREVIEW}")


if __name__ == "__main__":
    main()
