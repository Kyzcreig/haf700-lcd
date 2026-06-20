#!/usr/bin/env python3
"""
haf700-lcd — drive the Cooler Master HAF 700 EVO case LCD from Linux (no MasterPlus, no Windows).

The HAF 700 EVO front LCD is a rooted Android 4.4.2 device (RDA8810 SoC, 480x480) that exposes an
ADB interface over USB (CM VID 2516:01c1, interface 1). The vendor app "MasterPlus" simply transcodes
your image/GIF/video to a 480x480 H.264 mp4, adb-pushes it into the on-panel display app
(com.magic.box), and points a shared-preference at it. This tool does exactly that, from Linux.

Usage:
    haf700-lcd info
    haf700-lcd show   <image|gif|video>   [--fit cover|contain] [--seconds N]
    haf700-lcd screenshot [out.png]
    haf700-lcd restore                      # restore the previously-shown file (undo)

Requires: adb (android-tools-adb) and ffmpeg on PATH. The panel must be connected by USB and rooted
(stock HAF700 panels ship with `su`). Run `haf700-lcd info` to verify it's detected.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import time

PANEL_PKG = "com.magic.box"
PANEL_ACT = f"{PANEL_PKG}/.ui.SplashActivity"
FILES_DIR = f"/data/data/{PANEL_PKG}/files"
PREF = f"/data/data/{PANEL_PKG}/shared_prefs/magic.xml"
PANEL_W = PANEL_H = 480
PANEL_FPS = 25
# Default config header MasterPlus writes for a video item (29 bytes). Only used if no existing
# currentType is present to inherit from. Trailing bytes = namelen + ASCII filename.
DEFAULT_HEADER_HEX = "128000010026110000000000000000000001FFFFFFFF0003FF00000000"


def run(cmd, check=True, capture=True, timeout=120):
    """Run a local command (list form)."""
    r = subprocess.run(cmd, capture_output=capture, text=True, timeout=timeout)
    if check and r.returncode != 0:
        sys.stderr.write((r.stderr or r.stdout or "").strip() + "\n")
        raise SystemExit(f"command failed ({r.returncode}): {' '.join(cmd)}")
    return r


def adb(*args, check=True, capture=True, timeout=120):
    return run(["adb", *args], check=check, capture=capture, timeout=timeout)


def adb_shell(script, check=True, root=False, timeout=120):
    """Run a shell snippet on the panel. root=True wraps in `su -c`."""
    if root:
        inner = script.replace("'", "'\\''")
        full = f"su -c '{inner}'"
    else:
        full = script
    return adb("shell", full, check=check, timeout=timeout)


def require_tools():
    for t in ("adb", "ffmpeg", "ffprobe"):
        if shutil.which(t) is None:
            raise SystemExit(f"missing required tool: {t} (install android-tools-adb / ffmpeg)")


def ensure_device():
    out = adb("devices", check=False).stdout
    lines = [l for l in out.splitlines()[1:] if l.strip() and "\tdevice" in l]
    if not lines:
        raise SystemExit(
            "no ADB device found. Is the HAF700 connected by USB? "
            "Try: adb kill-server && adb start-server && adb devices"
        )
    return lines[0].split("\t")[0]


def cmd_info(_args):
    serial = ensure_device()
    model = adb_shell("getprop ro.product.device", check=False).stdout.strip()
    rel = adb_shell("getprop ro.build.version.release", check=False).stdout.strip()
    size = adb_shell("wm size", check=False).stdout.strip()
    print(f"HAF700 LCD detected:")
    print(f"  adb serial : {serial}")
    print(f"  android    : {rel}  (device codename: {model})")
    print(f"  {size}")
    cur = read_current_filename()
    print(f"  currently showing: {cur or '(unknown)'}")


def build_vf(fit):
    """ffmpeg video filter to make a 480x480 frame with no black bars."""
    if fit == "contain":
        # letterbox-free: scale to fit inside, pad would add bars -> we use cover for 'no black bars'
        # 'contain' kept for completeness but pads; cover is the default for the no-bars requirement.
        return (
            f"scale={PANEL_W}:{PANEL_H}:force_original_aspect_ratio=decrease,"
            f"pad={PANEL_W}:{PANEL_H}:(ow-iw)/2:(oh-ih)/2:color=black"
        )
    # cover (default): scale to cover the square, then center-crop -> fills frame, no bars
    return (
        f"scale={PANEL_W}:{PANEL_H}:force_original_aspect_ratio=increase,"
        f"crop={PANEL_W}:{PANEL_H}"
    )


def transcode(src, fit, seconds):
    """Transcode any image/gif/video to a panel-ready 480x480 h264 mp4. Returns local path."""
    out = f"/tmp/haf700_{int(time.time())}.mp4"
    vf = build_vf(fit)
    # Detect still image (no/!1 frames) -> loop it into a short clip so the player has something to loop.
    probe = run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=nb_frames,duration", "-of", "default=nw=1", src],
        check=False,
    ).stdout
    nb = re.search(r"nb_frames=(\d+)", probe)
    is_still = (nb and nb.group(1) == "1") or src.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".webp"))
    cmd = ["ffmpeg", "-y"]
    if is_still:
        cmd += ["-loop", "1", "-i", src, "-t", str(seconds)]
    else:
        # loop animated/video source to fill at least `seconds` so short gifs aren't a blink
        cmd += ["-stream_loop", "-1", "-i", src, "-t", str(seconds)]
    cmd += [
        "-vf", vf + ",fps=" + str(PANEL_FPS),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-profile:v", "baseline", "-level", "3.0", "-an", out,
    ]
    run(cmd, timeout=180)
    if not os.path.exists(out) or os.path.getsize(out) == 0:
        raise SystemExit("ffmpeg produced no output")
    return out


def read_current_pref():
    """Return the raw currentType hex string from magic.xml, or None."""
    out = adb_shell(f"cat {PREF}", check=False, root=True).stdout
    m = re.search(r'name="currentType">([0-9A-Fa-f]+)<', out)
    return m.group(1).upper() if m else None


def read_current_filename():
    hexs = read_current_pref()
    if not hexs:
        return None
    try:
        b = bytes.fromhex(hexs)
        namelen = b[-1 - 14] if len(b) > 15 else None  # filenames are <epoch>.mp4 = 14 chars
        # robust: last byte-run that is printable ascii ending in .mp4
        tail = b.decode("latin-1")
        m = re.search(r"(\d+\.mp4)$", tail)
        return m.group(1) if m else None
    except Exception:
        return None


def make_current_type(filename):
    """Build a new currentType hex: inherit the existing 29-byte header if present, else default."""
    cur = read_current_pref()
    name = filename.encode("ascii")
    if cur:
        b = bytes.fromhex(cur)
        # strip trailing [namelen][name]; the name is ascii ending .mp4
        tail = b.decode("latin-1")
        m = re.search(r"(\d+\.mp4)$", tail)
        if m:
            header = b[: -(1 + len(m.group(1)))]
        else:
            header = bytes.fromhex(DEFAULT_HEADER_HEX)
    else:
        header = bytes.fromhex(DEFAULT_HEADER_HEX)
    new = header + bytes([len(name)]) + name
    return new.hex().upper()


def cmd_show(args):
    require_tools()
    ensure_device()
    src = args.source
    if not os.path.exists(src):
        raise SystemExit(f"source not found: {src}")
    print(f"transcoding {src} -> 480x480 h264 ({args.fit}, no black bars)…")
    mp4 = transcode(src, args.fit, args.seconds)
    name = f"{int(time.time())}.mp4"
    dst = f"{FILES_DIR}/{name}"
    print(f"pushing {os.path.getsize(mp4)} bytes -> panel as {name}…")
    adb("push", mp4, f"/sdcard/{name}")
    adb_shell(
        f"cp /sdcard/{name} {dst} && chown system.system {dst} && chmod 600 {dst} && rm /sdcard/{name}",
        root=True,
    )
    new_ct = make_current_type(name)
    # back up + swap currentType, then reload the display app
    adb_shell(
        f"cp {PREF} {PREF}.haf700bak && "
        f"sed -i 's#\\(name=\"currentType\">\\)[0-9A-Fa-f]*#\\1{new_ct}#' {PREF} && "
        f"chown system.system {PREF} && chmod 660 {PREF}",
        root=True,
    )
    adb_shell(f"am force-stop {PANEL_PKG}", check=False)
    time.sleep(1)
    adb_shell(f"am start -n {PANEL_ACT}", check=False)
    print(f"✓ now showing {name} on the HAF700 LCD. Verify with: haf700-lcd screenshot")
    os.remove(mp4)


def cmd_screenshot(args):
    ensure_device()
    out = args.out or f"haf700_screen_{int(time.time())}.png"
    adb_shell("screencap -p /sdcard/_haf_shot.png", check=False)
    adb("pull", "/sdcard/_haf_shot.png", out)
    adb_shell("rm /sdcard/_haf_shot.png", check=False)
    print(f"✓ saved panel framebuffer -> {out}")


def cmd_restore(_args):
    ensure_device()
    r = adb_shell(f"[ -f {PREF}.haf700bak ] && cp {PREF}.haf700bak {PREF} && "
                  f"chown system.system {PREF} && echo restored || echo 'no backup'", root=True)
    print(r.stdout.strip())
    adb_shell(f"am force-stop {PANEL_PKG}", check=False)
    time.sleep(1)
    adb_shell(f"am start -n {PANEL_ACT}", check=False)


def main():
    p = argparse.ArgumentParser(prog="haf700-lcd", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("info", help="detect the panel and show its status").set_defaults(func=cmd_info)

    s = sub.add_parser("show", help="display an image / gif / video on the LCD")
    s.add_argument("source")
    s.add_argument("--fit", choices=["cover", "contain"], default="cover",
                   help="cover (fill, center-crop, NO black bars; default) or contain (letterbox)")
    s.add_argument("--seconds", type=int, default=6, help="loop length for stills/short gifs")
    s.set_defaults(func=cmd_show)

    ss = sub.add_parser("screenshot", help="capture what's on the panel right now")
    ss.add_argument("out", nargs="?")
    ss.set_defaults(func=cmd_screenshot)

    sub.add_parser("restore", help="undo the last `show` (restore previous file)").set_defaults(func=cmd_restore)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
