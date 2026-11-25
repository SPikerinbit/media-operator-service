"""Convert Blender 4.5 PNG renders into production WebP props, Windows .ico, favicon, and Inno Setup wizard BMPs."""
from __future__ import annotations

import argparse
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter


def alpha_bounds(img: Image.Image) -> tuple[float, float, float, float]:
    bbox = img.getbbox()
    if not bbox:
        return (0.0, 0.0, 1.0, 1.0)
    w, h = img.size
    return (
        round(bbox[0] / w, 5),
        round(bbox[1] / h, 5),
        round(bbox[2] / w, 5),
        round(bbox[3] / h, 5),
    )


def save_webp(src: Path, dst: Path, quality: int = 92, max_size: tuple[int, int] | None = None):
    img = Image.open(src).convert("RGBA")
    if max_size and (img.width > max_size[0] or img.height > max_size[1]):
        img.thumbnail(max_size, Image.Resampling.LANCZOS)
    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst, "WEBP", quality=quality, method=6)
    print(f"  -> {dst.relative_to(dst.parents[3]) if len(dst.parents) > 3 else dst.name} ({img.size[0]}x{img.size[1]}, bounds={alpha_bounds(img)})")
    return img


def build_icon_assets(icon_png: Path, repo: Path):
    raw = Image.open(icon_png).convert("RGBA")
    # Crop tightly around the rendered icon with a tiny 5% breathing margin so Windows 16px/24px icons look bold & crisp
    bbox = raw.getbbox()
    if bbox:
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        side = max(w, h)
        pad = int(side * 0.05)
        canvas = Image.new("RGBA", (side + pad * 2, side + pad * 2), (0, 0, 0, 0))
        cropped = raw.crop(bbox)
        canvas.paste(cropped, (pad + (side - w) // 2, pad + (side - h) // 2), cropped)
    else:
        canvas = raw

    ico_path = repo / "packaging" / "icon.ico"
    ico_sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    canvas.resize((256, 256), Image.Resampling.LANCZOS).save(ico_path, format="ICO", sizes=ico_sizes)
    print(f"  -> packaging/icon.ico ({len(ico_sizes)} sizes)")

    fav_path = repo / "frontend" / "public" / "favicon.png"
    canvas.resize((256, 256), Image.Resampling.LANCZOS).save(fav_path, format="PNG")
    print("  -> frontend/public/favicon.png (256x256)")

    # Inno Setup modern wizard sidebar (164 x 314, 24-bit RGB BMP)
    sidebar = Image.new("RGB", (164, 314), (231, 238, 242))
    draw = ImageDraw.Draw(sidebar)
    # Soft vertical gradient from #eef3f6 to #d5e0e7
    for y in range(314):
        t = y / 313
        r = int(238 + (212 - 238) * t)
        g = int(243 + (223 - 243) * t)
        b = int(246 + (231 - 246) * t)
        draw.line([(0, y), (164, y)], fill=(r, g, b))
    # Subtle brass rule line near bottom
    draw.rectangle([28, 258, 136, 260], fill=(198, 161, 90))
    icon_med = canvas.resize((120, 120), Image.Resampling.LANCZOS)
    # Soft drop shadow under icon
    shadow = Image.new("RGBA", (140, 140), (0, 0, 0, 0))
    alpha = icon_med.getchannel("A")
    shadow_layer = Image.new("RGBA", (120, 120), (36, 52, 68, 56))
    shadow.paste(shadow_layer, (10, 14), alpha)
    shadow = shadow.filter(ImageFilter.GaussianBlur(7))
    sidebar_rgba = sidebar.convert("RGBA")
    sidebar_rgba.alpha_composite(shadow, (12, 76))
    sidebar_rgba.alpha_composite(icon_med, (22, 82))
    sidebar_rgba.convert("RGB").save(repo / "packaging" / "wizard-sidebar.bmp", format="BMP")
    print("  -> packaging/wizard-sidebar.bmp (164x314)")

    # Inno Setup modern wizard small top-right image (55 x 58, 24-bit RGB BMP)
    small = Image.new("RGBA", (55, 58), (246, 248, 250, 255))
    icon_sm = canvas.resize((46, 46), Image.Resampling.LANCZOS)
    small.alpha_composite(icon_sm, (4, 6))
    small.convert("RGB").save(repo / "packaging" / "wizard-small.bmp", format="BMP")
    print("  -> packaging/wizard-small.bmp (55x58)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", required=True)
    parser.add_argument("--repo", default=".")
    args = parser.parse_args()
    src = Path(args.src).resolve()
    repo = Path(args.repo).resolve()
    wb = repo / "frontend" / "public" / "workbench"

    if (src / "app-icon.png").is_file():
        build_icon_assets(src / "app-icon.png", repo)

    direct_props = [
        "mailbox-light-beauty",
        "mailbox-light-body",
        "mailbox-light-front",
        "mailbox-light-flap",
        "mailbox-light-slot-back",
        "mailbox-light-slot-front",
        "wax-light-beauty",
        "wax-light-body",
        "wax-blue-light-beauty",
        "wax-blue-light-body",
        "wood-0-light-beauty",
        "wood-0-light-body",
        "wood-1-light-beauty",
        "wood-1-light-body",
        "wood-2-light-beauty",
        "wood-2-light-body",
        "wood-3-light-beauty",
        "wood-3-light-body",
        "trash-light-beauty",
        "trash-light-body",
        "trash-light-front",
        "desk-tv-frame",
        "shred-switch-plate",
        "badge-douyin",
        "badge-xiaohongshu",
        "badge-bilibili",
        "badge-weread",
    ]
    for stem in direct_props:
        png = src / f"{stem}.png"
        if png.is_file():
            save_webp(png, wb / f"{stem}.webp")


if __name__ == "__main__":
    main()
