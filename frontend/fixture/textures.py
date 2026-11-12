"""Tileable study-room textures. Warm light is painted in CSS, not in the grain."""
from pathlib import Path
import math
import random
from PIL import Image

OUT = Path(__file__).resolve().parents[1] / "public" / "workbench" / "materials"
OUT.mkdir(parents=True, exist_ok=True)


def clamp(v):
    return 0 if v < 0 else 255 if v > 255 else int(v)


def value_noise(w, h, scale, seed):
    rng = random.Random(seed)
    gw = max(2, w // scale + 2)
    gh = max(2, h // scale + 2)
    grid = [[rng.random() for _ in range(gw)] for _ in range(gh)]
    out = [[0.0] * w for _ in range(h)]
    for y in range(h):
        gy = y / scale
        y0 = int(gy)
        ty = gy - y0
        sy = ty * ty * (3 - 2 * ty)
        for x in range(w):
            gx = x / scale
            x0 = int(gx)
            tx = gx - x0
            sx = tx * tx * (3 - 2 * tx)
            a = grid[y0 % gh][x0 % gw]
            b = grid[y0 % gh][(x0 + 1) % gw]
            c = grid[(y0 + 1) % gh][x0 % gw]
            d = grid[(y0 + 1) % gh][(x0 + 1) % gw]
            out[y][x] = (a + (b - a) * sx) + ((c + (d - c) * sx) - (a + (b - a) * sx)) * sy
    return out


def save(name, img, quality=74):
    path = OUT / name
    img.save(path, "WEBP", quality=quality, method=6)
    print(f"{path.name} {path.stat().st_size} bytes")


def walnut():
    w = h = 720
    fine = value_noise(w, h, 4, 2)
    figure = value_noise(w, h, 110, 8)
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            yy = y + math.sin(x * 0.013) * 3.2 + math.sin(x * 0.004 + 1.2) * 5 + (fine[y][x] - 0.5) * 2.2
            band = (yy * 0.16) % 1
            tone = 74 + band * 48 + figure[y][x] * 22
            if band > 0.58:
                tone = 42 + (1 - band) * 36
            if 0.35 < figure[y][x] < 0.62 and band < 0.45:
                tone += 14
            tone += (fine[y][x] - 0.5) * 16
            r = tone + 36
            g = tone * 0.46 + 12
            b = tone * 0.2 + 4
            px[x, y] = (clamp(r), clamp(g), clamp(b))
    save("walnut.webp", img)


def leather():
    w = h = 512
    blot = value_noise(w, h, 28, 4)
    grain = value_noise(w, h, 3, 19)
    img = Image.new("RGB", (w, h))
    px = img.load()
    rng = random.Random(21)
    pores = {(rng.randrange(w), rng.randrange(h)) for _ in range(2200)}
    for y in range(h):
        for x in range(w):
            r = 48 + blot[y][x] * 40 + grain[y][x] * 22
            g = 26 + blot[y][x] * 18 + grain[y][x] * 8
            b = 16 + blot[y][x] * 8
            if (x, y) in pores or grain[y][x] > 0.84:
                r -= 26
                g -= 14
                b -= 8
            px[x, y] = (clamp(r), clamp(g), clamp(b))
    save("leather.webp", img)


def linen():
    w = h = 256
    img = Image.new("RGB", (w, h))
    px = img.load()
    rng = random.Random(7)
    for y in range(h):
        for x in range(w):
            cell = 4
            over = ((x // cell) + (y // cell)) % 2 == 0
            along = (x % cell) / cell if over else (y % cell) / cell
            shade = 10 if 0.15 < along < 0.7 else -8
            if over:
                shade += 4
            n = (rng.random() - 0.5) * 8
            r = 206 + shade + n
            g = 196 + shade * 0.85 + n
            b = 174 + shade * 0.6 + n
            px[x, y] = (clamp(r), clamp(g), clamp(b))
    save("linen.webp", img, 72)


def paper():
    w = h = 384
    n1 = value_noise(w, h, 40, 5)
    img = Image.new("RGB", (w, h))
    px = img.load()
    rng = random.Random(2)
    fibers = []
    for _ in range(1600):
        fibers.append((rng.randrange(w), rng.randrange(h), rng.random() * math.tau, rng.uniform(2, 9)))
    for y in range(h):
        for x in range(w):
            cloud = n1[y][x]
            r = 242 + cloud * 10
            g = 236 + cloud * 8
            b = 222 + cloud * 6
            px[x, y] = (clamp(r), clamp(g), clamp(b))
    for x, y, ang, length in fibers:
        tone = rng.choice([(214, 202, 182), (206, 192, 170), (226, 216, 198)])
        for i in range(int(length)):
            xx = int(x + math.cos(ang) * i) % w
            yy = int(y + math.sin(ang) * i) % h
            px[xx, yy] = tone
    save("paper.webp", img, 72)


def brass():
    w, h = 128, 64
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            band = math.sin(y * 0.45) * 10 + math.sin(x * 0.2 + y) * 4
            r = 196 + band
            g = 156 + band * 0.7
            b = 72 + band * 0.3
            px[x, y] = (clamp(r), clamp(g), clamp(b))
    save("brass.webp", img, 76)


def torn_mask():
    w, h = 480, 96
    img = Image.new("L", (w, h), 0)
    px = img.load()
    rng = random.Random(8)
    top = [6 + int(math.sin(x * 0.17) * 3 + math.sin(x * 0.05) * 2 + (rng.random() * 4 if rng.random() > 0.82 else 0)) for x in range(w)]
    bot = [h - 6 - int(math.sin(x * 0.13 + 1) * 3 + (rng.random() * 5 if rng.random() > 0.8 else 0)) for x in range(w)]
    for y in range(h):
        for x in range(w):
            if top[x] < y < bot[x]:
                px[x, y] = 255
            elif abs(y - top[x]) < 3 or abs(y - bot[x]) < 3:
                px[x, y] = 180 if rng.random() > 0.4 else 0
    # feather a few fibers sticking out
    for _ in range(180):
        x = rng.randrange(w)
        y = top[x] - rng.randint(0, 4)
        if 0 <= y < h:
            px[x, y] = 220
        y2 = bot[x] + rng.randint(0, 4)
        if 0 <= y2 < h:
            px[x, y2] = 220
    save("torn-mask.webp", img, 80)


if __name__ == "__main__":
    walnut()
    leather()
    linen()
    paper()
    brass()
    torn_mask()
