# haf700-lcd

Drive the **Cooler Master HAF 700 EVO** case LCD from **Linux** — no Windows, no MasterPlus.

> The HAF 700 EVO's front LCD is the panel the vendor's **MasterPlus** app controls on Windows only.
> This tool gives you full control from Linux: show any image, GIF, or video on it, and screenshot
> what's currently displayed.

![CI](https://github.com/Kyzcreig/haf700-lcd/actions/workflows/smoke.yml/badge.svg) ![status](https://img.shields.io/badge/status-working-brightgreen) ![platform](https://img.shields.io/badge/platform-linux-blue) ![license](https://img.shields.io/badge/license-MIT-green)

## How it works (the TL;DR of the reverse-engineering)

The HAF 700 EVO LCD isn't a dumb display — it's a **tiny rooted Android device** (Android 4.4.2 on an
RDA8810 ARM SoC, 480×480 screen) that hangs off your motherboard's USB as Cooler Master USB ID
**`2516:01c1`**. Its second USB interface is a standard **ADB** (Android Debug Bridge) interface.

All MasterPlus does is:
1. transcode your image/GIF/video into a **480×480 H.264 MP4**,
2. `adb push` it into the on-panel display app (`com.magic.box`), and
3. update one Android shared-preference so the app plays your file.

`haf700-lcd` does exactly that, from Linux, with `adb` + `ffmpeg`. **No custom USB protocol, no driver,
no reverse-engineered firmware** — it's just an Android device you talk to with `adb`.

As far as I can tell this is the **first public tool to drive this panel from Linux**. If you find an
earlier one, please open an issue — I'd love to link it.

## Requirements

- Linux (tested on Ubuntu)
- `adb` — `sudo apt install android-tools-adb` (or your distro's `android-tools`)
- `ffmpeg` + `ffprobe` — `sudo apt install ffmpeg`
- The HAF 700 EVO front-panel USB cable plugged into a motherboard USB header (it usually is)

The panel ships rooted (it has `su`), which is what lets the app's protected files be written.

## Install

```bash
git clone https://github.com/Kyzcreig/haf700-lcd
cd haf700-lcd
chmod +x haf700_lcd.py
# optional: symlink onto your PATH
sudo ln -s "$PWD/haf700_lcd.py" /usr/local/bin/haf700-lcd
```

No Python dependencies beyond the standard library (it shells out to `adb`/`ffmpeg`).

## Usage

```bash
# verify the panel is detected
haf700-lcd info

# show an image / gif / video (auto-cropped to fill the square, NO black bars)
haf700-lcd show my-art.png
haf700-lcd show loop.gif
haf700-lcd show clip.mp4

# letterbox instead of crop (keeps the whole frame, adds bars)
haf700-lcd show wide.jpg --fit contain

# loop a still / short gif for N seconds (default 6)
haf700-lcd show logo.png --seconds 10

# capture what's currently on the panel (it's an Android framebuffer!)
haf700-lcd screenshot proof.png

# undo the last `show`
haf700-lcd restore
```

### `info` output

```
HAF700 LCD detected:
  adb serial : 1234567890ABCDEF
  android    : 4.4.2  (device codename: etau)
  Physical size: 480x480
  currently showing: 1799990001.mp4
```

## How `show` works internally

1. `ffmpeg` transcodes the source to a 480×480 H.264 baseline MP4 at 25 fps. The default `--fit cover`
   scales-to-fill and center-crops so there are **no black bars**; `--fit contain` letterboxes instead.
   Stills and short GIFs are looped to fill the requested duration.
2. `adb push` lands the MP4 on the panel, then (as root via the panel's `su`) it's copied into
   `/data/data/com.magic.box/files/` with the right owner/mode.
3. The `currentType` key in `com.magic.box`'s `shared_prefs/magic.xml` is rewritten to point at the new
   file (the existing 29-byte config header is preserved; only the trailing length-prefixed filename
   changes).
4. The display app is restarted (`am force-stop` + `am start`) so it re-reads the pref and loops your
   content.

## Protocol notes (for the curious / for porting)

See [`PROTOCOL.md`](PROTOCOL.md) for the full reverse-engineering writeup: USB descriptors, the ADB
interface signature, the `com.magic.box` file/pref mechanism, the `currentType` byte layout, and the
`com.rdamicro.pcdatareceiver` package that handles the hardware-monitor display modes.

## Caveats / not-yet-done

- **Image / GIF / video display: working.** ✅
- **Clock & hardware-monitor display modes** (CPU temp etc.) use a different `currentType` header and the
  `com.rdamicro.pcdatareceiver` package — not yet mapped. PRs welcome.
- Only tested on one HAF 700 EVO (2024). Other Cooler Master cases/coolers that use the same MagicBox
  Android panel may work as-is — reports welcome.

## Development

The hardware-coupled commands need a real panel, but the tricky logic — the `currentType`
(`magic.xml`) codec and the ffmpeg "no black bars" filter — is pure and unit-tested. CI runs them
plus a CLI launch smoke test on every push:

```bash
python -m pytest -v        # 12 tests, no hardware needed
```

## License

MIT — see [LICENSE](LICENSE).

## Disclaimer

Not affiliated with or endorsed by Cooler Master. "HAF", "MasterPlus", and "Cooler Master" are
trademarks of their respective owner. Use at your own risk; this writes to the panel's Android storage
via its own (vendor-shipped) root shell.
