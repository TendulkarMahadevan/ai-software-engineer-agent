#!/usr/bin/env python3
"""Render an animated black hole (gravitational lensing + rotating accretion disk).

Needs only numpy and ffmpeg.

    python3 render_blackhole.py                      # 1280x720, 8 s -> blackhole.mp4
    python3 render_blackhole.py --vertical           # 720x1280 for Shorts/Reels/TikTok
    python3 render_blackhole.py --preview            # quick low-res test

How it works: every pixel shoots a light ray backwards from the camera. The ray is
bent by Schwarzschild gravity (a = -1.5 * h^2 * r_vec / r^5, units where the
Schwarzschild radius is 1), so rays near the hole curve around it. A ray that falls
inside r < 1 is black (the shadow). A ray that crosses the equatorial plane between the
inner and outer disk radius picks up glowing gas, brighter and bluer toward the centre,
with relativistic Doppler beaming. Anything else shows the star background.
"""
import argparse
import subprocess
import sys
from multiprocessing import Pool

import numpy as np

R_S = 1.0          # Schwarzschild radius
R_IN = 3.0         # innermost stable orbit (3 R_S)
R_OUT = 11.0       # outer edge of the disk
R_ESCAPE = 60.0    # beyond this a ray is considered to have escaped


def hash3(ix, iy, iz):
    """Cheap deterministic per-cell pseudo-random number in [0, 1)."""
    n = (ix * 73856093) ^ (iy * 19349663) ^ (iz * 83492791)
    n = (n ^ (n >> 13)) * 1274126177
    n = n ^ (n >> 16)
    return (n & 0xFFFFFF) / float(0x1000000)


def starfield(d):
    """Procedural stars + faint milky-way band, looked up by ray direction d (N,3)."""
    res = 180.0
    cell = np.floor(d * res).astype(np.int64)
    r1 = hash3(cell[:, 0], cell[:, 1], cell[:, 2])
    r2 = hash3(cell[:, 0] + 17, cell[:, 1] + 31, cell[:, 2] + 47)
    r3 = hash3(cell[:, 0] + 101, cell[:, 1] + 7, cell[:, 2] + 59)
    star = (r1 > 0.9965).astype(np.float64) * (0.35 + 0.65 * r2) ** 2 * 2.2
    tint = np.stack([1.0 - 0.25 * r3, 1.0 - 0.1 * r3, 0.75 + 0.25 * r3], axis=1)
    img = star[:, None] * tint

    # soft galactic band around a tilted plane
    n = np.array([0.25, 0.95, 0.18])
    n /= np.linalg.norm(n)
    band = np.exp(-((d @ n) / 0.22) ** 2)
    clouds = 0.5 + 0.5 * np.sin(d[:, 0] * 9.0 + np.sin(d[:, 2] * 7.0) * 1.6) \
        * np.sin(d[:, 1] * 6.0 + d[:, 0] * 3.0)
    glow = (band * (0.05 + 0.07 * clouds))[:, None] * np.array([0.55, 0.62, 0.9])
    return img + glow


def disk_color(r, phi, t, doppler):
    """Emission colour of the accretion disk at radius r, azimuth phi, time t."""
    temp = (R_IN / r) ** 0.75                     # hotter near the centre
    omega = 2.2 / r ** 1.5                        # Keplerian: inner gas spins faster
    ang = phi - omega * t * 3.0
    # turbulent, spiral-ish streaks that shear with differential rotation
    streak = (0.55
              + 0.25 * np.sin(5.0 * ang + 2.5 * np.log(r))
              + 0.15 * np.sin(13.0 * ang - 4.0 * np.log(r) + 1.3)
              + 0.10 * np.sin(31.0 * ang + 7.0 * r))
    rings = 0.85 + 0.15 * np.sin(r * 9.0)
    edge = np.clip((r - R_IN) / 0.6, 0, 1) * np.clip((R_OUT - r) / 3.0, 0, 1)
    intensity = temp ** 3.2 * streak * rings * edge * doppler ** 2
    # warm white-hot centre fading to deep orange / red
    t_ = np.clip(temp * doppler, 0, 1.6)
    red = np.clip(1.4 * t_ + 0.15, 0, 1.6)
    green = np.clip(1.05 * t_ ** 1.7, 0, 1.4)
    blue = np.clip(0.8 * t_ ** 3.0, 0, 1.2)
    return intensity[:, None] * np.stack([red, green, blue], axis=1) * 3.2


def trace(width, height, cam_pos, cam_target, fov_deg, t, steps):
    """Trace one frame. Returns float RGB (height, width, 3)."""
    fwd = cam_target - cam_pos
    fwd /= np.linalg.norm(fwd)
    right = np.cross(fwd, np.array([0.0, 1.0, 0.0]))
    right /= np.linalg.norm(right)
    up = np.cross(right, fwd)

    aspect = width / height
    tan_half = np.tan(np.radians(fov_deg) / 2.0)
    xs = (np.arange(width) + 0.5) / width * 2 - 1
    ys = 1 - (np.arange(height) + 0.5) / height * 2
    px, py = np.meshgrid(xs * tan_half * aspect, ys * tan_half)
    dirs = (fwd[None, :] + px.reshape(-1, 1) * right[None, :]
            + py.reshape(-1, 1) * up[None, :])
    dirs /= np.linalg.norm(dirs, axis=1, keepdims=True)

    n = dirs.shape[0]
    pos = np.tile(cam_pos, (n, 1))
    vel = dirs.copy()
    h2 = np.sum(np.cross(pos, vel) ** 2, axis=1)  # conserved angular momentum^2

    color = np.zeros((n, 3))
    trans = np.ones(n)                    # remaining transparency along the ray
    alive = np.ones(n, dtype=bool)
    captured = np.zeros(n, dtype=bool)

    for _ in range(steps):
        idx = np.nonzero(alive)[0]
        if idx.size == 0:
            break
        p = pos[idx]
        v = vel[idx]
        r2 = np.sum(p * p, axis=1)
        r = np.sqrt(r2)

        # adaptive step: small near the hole, large far away
        dt = np.clip(0.04 * r, 0.015, 1.6)
        acc = -1.5 * h2[idx][:, None] * p / (r2 ** 2.5)[:, None]
        v_new = v + acc * dt[:, None]
        v_new /= np.linalg.norm(v_new, axis=1, keepdims=True)
        p_new = p + v_new * dt[:, None]

        # crossing of the equatorial plane (y = 0) -> disk emission
        cross = (p[:, 1] * p_new[:, 1]) < 0
        if cross.any():
            ci = np.nonzero(cross)[0]
            w = p[ci, 1] / (p[ci, 1] - p_new[ci, 1])
            hit = p[ci] + (p_new[ci] - p[ci]) * w[:, None]
            rh = np.sqrt(hit[:, 0] ** 2 + hit[:, 2] ** 2)
            on_disk = (rh > R_IN) & (rh < R_OUT)
            if on_disk.any():
                di = ci[on_disk]
                hh = hit[on_disk]
                rr = rh[on_disk]
                phi = np.arctan2(hh[:, 2], hh[:, 0])
                # gas orbits counter-clockwise: velocity direction (-z, 0, x)/r
                orb_speed = np.sqrt(0.5 / rr) * 1.0
                vdir = np.stack([-hh[:, 2], np.zeros_like(rr), hh[:, 0]], axis=1) / rr[:, None]
                # Doppler: the gas moving toward the viewer is brighter and bluer
                beta = np.sum(vdir * (-v_new[di]), axis=1) * orb_speed
                doppler = 1.0 / np.clip(1.0 - beta * 1.0, 0.5, None)
                emit = disk_color(rr, phi, t, doppler)
                gi = idx[di]
                color[gi] += emit * trans[gi][:, None]
                trans[gi] *= 0.28          # disk is mostly opaque

        pos[idx] = p_new
        vel[idx] = v_new

        r_new = np.sqrt(np.sum(p_new * p_new, axis=1))
        fell = r_new < R_S * 1.02
        escaped = r_new > R_ESCAPE
        captured[idx[fell]] = True
        alive[idx[fell | escaped]] = False

    # rays that escaped show the (lensed) star background
    esc = (~captured) & (trans > 0.01)
    if esc.any():
        d_out = vel[esc]
        color[esc] += starfield(d_out) * trans[esc][:, None]

    return color.reshape(height, width, 3)


def upsample(a, h, w):
    """Bilinear resize of (hh, ww, 3) to (h, w, 3)."""
    hh, ww, _ = a.shape
    y = (np.arange(h) + 0.5) * hh / h - 0.5
    x = (np.arange(w) + 0.5) * ww / w - 0.5
    y0 = np.clip(np.floor(y).astype(int), 0, hh - 1)
    x0 = np.clip(np.floor(x).astype(int), 0, ww - 1)
    y1 = np.clip(y0 + 1, 0, hh - 1)
    x1 = np.clip(x0 + 1, 0, ww - 1)
    fy = np.clip(y - y0, 0, 1)[:, None, None]
    fx = np.clip(x - x0, 0, 1)[None, :, None]
    top = a[y0][:, x0] * (1 - fx) + a[y0][:, x1] * fx
    bot = a[y1][:, x0] * (1 - fx) + a[y1][:, x1] * fx
    return top * (1 - fy) + bot * fy


def bloom(img, strength=0.55, passes=3):
    """Cheap glow: repeatedly downsample, box-blur, upsample and add back."""
    h, w, _ = img.shape
    bright = np.clip(img - 1.2, 0, None)
    glow = np.zeros_like(img)
    cur = bright
    for i in range(passes):
        k = 2 ** (i + 2)
        hh, ww = h // k, w // k
        if hh < 4 or ww < 4:
            break
        small = cur[: hh * k, : ww * k].reshape(hh, k, ww, k, 3).mean(axis=(1, 3))
        # separable blur
        for _ in range(2):
            for ax in (0, 1):
                small = (np.roll(small, 1, ax) + 2 * small + np.roll(small, -1, ax)) / 4
        glow += upsample(small, h, w)
    return img + glow * strength * 1.8


def tonemap(img):
    img = img * 1.0
    img = 1.0 - np.exp(-img * 1.35)               # soft highlight roll-off
    img = np.clip(img, 0, 1) ** (1 / 2.2)
    return (img * 255 + 0.5).astype(np.uint8)


def render_frame(args):
    i, total, width, height, steps = args
    u = i / total
    ang = 2 * np.pi * u * 0.20 + 0.6              # slow camera drift around the hole
    dist = 30.0 - 5.0 * np.sin(np.pi * u)         # gentle push in and out
    incl = np.radians(9.0 + 4.0 * np.sin(2 * np.pi * u))   # degrees above the disk plane
    cam = np.array([dist * np.cos(incl) * np.cos(ang),
                    dist * np.sin(incl),
                    dist * np.cos(incl) * np.sin(ang)])
    fov = 34.0 if width >= height else 46.0
    img = trace(width, height, cam, np.zeros(3), fov, t=u * 14.0, steps=steps)
    img = bloom(img)
    return i, tonemap(img)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--output", default="blackhole.mp4")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--vertical", action="store_true", help="720x1280 portrait")
    ap.add_argument("--seconds", type=float, default=8.0)
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--steps", type=int, default=380, help="ray integration steps")
    ap.add_argument("--preview", action="store_true", help="480x270, 2 s, fewer steps")
    ap.add_argument("--workers", type=int, default=0, help="0 = all CPU cores")
    ap.add_argument("--png", help="render a single frame to this PNG instead of a video")
    a = ap.parse_args()

    w, h, secs, steps = a.width, a.height, a.seconds, a.steps
    if a.vertical:
        w, h = 720, 1280
    if a.preview:
        w, h, secs, steps = (270, 480) if a.vertical else (480, 270), 2.0, 260

    if a.png:
        _, frame = render_frame((int(0.35 * 100), 100, w, h, steps))
        write_png(a.png, frame)
        print("wrote", a.png)
        return

    total = int(secs * a.fps)
    ff = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{w}x{h}", "-r", str(a.fps), "-i", "-",
         "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
         "-movflags", "+faststart", a.output],
        stdin=subprocess.PIPE)

    jobs = [(i, total, w, h, steps) for i in range(total)]
    done = 0
    with Pool(a.workers or None) as pool:
        for _, frame in pool.imap(render_frame, jobs):   # imap keeps frame order
            ff.stdin.write(frame.tobytes())
            done += 1
            print(f"\rframe {done}/{total}", end="", file=sys.stderr, flush=True)
    ff.stdin.close()
    ff.wait()
    print(f"\nwrote {a.output} ({w}x{h}, {secs:.0f}s @ {a.fps}fps)")


def write_png(path, rgb):
    """Minimal PNG writer so we don't need Pillow."""
    import struct
    import zlib
    h, w, _ = rgb.shape
    raw = b"".join(b"\x00" + rgb[y].tobytes() for y in range(h))

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)))
        f.write(chunk(b"IDAT", zlib.compress(raw, 6)))
        f.write(chunk(b"IEND", b""))


if __name__ == "__main__":
    main()
