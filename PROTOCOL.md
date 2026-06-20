# HAF 700 EVO LCD — Protocol & Reverse-Engineering Notes

How the Cooler Master HAF 700 EVO front-panel LCD actually works, and how this tool drives it.

## The device

The LCD enumerates over USB as **`2516:01c1`** ("HAF700", Cooler Master VID `0x2516`). It's a USB 2.0
full-speed **composite device** with two interfaces:

| Interface | Class | Endpoints | Purpose |
|---|---|---|---|
| 0 | HID (`0x03`) | 4-byte interrupt IN/OUT, usage page `0xFF20`, report ID 1 | RGB / control channel (this is what OpenRGB drives for the case lighting) |
| 1 | Vendor-Specific (`0xFF`, subclass `0x42`, protocol `1`) | 64-byte **bulk** IN `0x82` / OUT `0x02` | **ADB** — the LCD image path |

The HID interface's reports are only 4 bytes — far too small for image data. **The LCD is driven over
interface 1**, and that interface's descriptor triple — class `0xFF` / subclass `0x42` / protocol `0x01`
— is the **canonical Android Debug Bridge interface signature**. On Windows it binds to WinUSB via
`winusb.inf`'s `ADB.NT` section (Windows literally labels it "ADB Device"). On Linux it's unclaimed, so
`adb` connects to it directly.

## The panel is an Android computer

`adb shell` reveals a full (rooted) Android device:

```
ro.build.version.release = 4.4.2           # Android 4.4.2 (KitKat)
ro.product.device        = etau
Hardware                 = rda8810          # RDA8810 ARMv7 SoC
kernel                   = 3.10.62
wm size                  = 480x480
display                  = 480x480, 50fps, "Built-in Screen"
adb shell `id`           = uid=0(root)      # root out of the box
```

Relevant installed packages:

| Package | Role |
|---|---|
| `com.magic.box` | The LCD display app ("MagicBox"). Foreground activity `.ui.SplashActivity`. Plays video via **IjkPlayer** (`tv.danmaku.ijk.media.player`). |
| `com.rdamicro.pcdatareceiver` | Receives PC sensor/stat data from MasterPlus over ADB (drives the hardware-monitor display modes). |
| `com.rda.filemanager`, `com.koushikdutta.superuser` | File manager + root. |

## The display mechanism

1. **Content** lives in `/data/data/com.magic.box/files/` as `<epoch>.mp4` files — **480×480 H.264,
   25 fps**. MasterPlus transcodes any image/GIF/video down to this.
2. **What's shown** is selected by the `currentType` key in
   `/data/data/com.magic.box/shared_prefs/magic.xml`. It's a hex-encoded blob:

   ```
   [ 29-byte config header ][ 1-byte filename length ][ filename ASCII ]
   ```

   Example (`currentType` for `1777192101.mp4`):
   ```
   128000010026110000000000000000000001FFFFFFFF0003FF00000000  0E  313737373139323130312E6D7034
   └────────────────── 29-byte header ──────────────────────┘ len  └──── "1777192101.mp4" ─────┘
   ```
   The header encodes display-mode / color / loop flags. To switch the displayed file you keep the
   header and replace only the length-prefixed filename.
3. `com.magic.box` reads `currentType` on (re)start and loops that MP4. Restarting it
   (`am force-stop com.magic.box` + `am start -n com.magic.box/.ui.SplashActivity`) forces a reload.

## The full Linux recipe

```bash
adb devices                 # -> 1234567890ABCDEF  device   (codename etau)

# 1) transcode to the panel format (480x480 h264, no black bars via cover-crop)
ffmpeg -y -i SOURCE \
  -vf "scale=480:480:force_original_aspect_ratio=increase,crop=480:480,fps=25" \
  -c:v libx264 -pix_fmt yuv420p -profile:v baseline -level 3.0 -an  1799990001.mp4

# 2) push into the protected app dir (needs the panel's own root)
adb push 1799990001.mp4 /sdcard/1799990001.mp4
adb shell "su -c 'cp /sdcard/1799990001.mp4 /data/data/com.magic.box/files/ && \
  chown system.system /data/data/com.magic.box/files/1799990001.mp4 && \
  chmod 600 /data/data/com.magic.box/files/1799990001.mp4'"

# 3) point currentType at the new file (swap only the filename hex), reload the app
NEW_HEX=$(printf '1799990001.mp4' | xxd -p)          # filename -> hex
adb shell "su -c 'sed -i \"s#\\(currentType\\\">\\)[0-9A-Fa-f]*#\\1<HEADER_HEX><LEN><$NEW_HEX>#\" \
  /data/data/com.magic.box/shared_prefs/magic.xml'"
adb shell "am force-stop com.magic.box && am start -n com.magic.box/.ui.SplashActivity"
```

(`haf700_lcd.py` automates all of this, including inheriting the existing header so you don't have to
hand-assemble it.)

## Verifying — the panel is its own screenshot tool

Because it's an Android device, you can screenshot exactly what's on the LCD:

```bash
adb shell screencap -p /sdcard/s.png && adb pull /sdcard/s.png
```

This is the ground-truth proof that your content is actually displayed (not just pushed).

## Open / not-yet-mapped

- The **clock** and **hardware-monitor** display modes use different `currentType` header bytes and the
  `com.rdamicro.pcdatareceiver` package (PC pushes live sensor values to it). Not needed for image/GIF/
  video display; not yet reverse-engineered.
- Only validated on one 2024 HAF 700 EVO. The same MagicBox Android panel appears in other Cooler Master
  products and likely works identically.

## Credits

Reverse-engineered 2026 by working through the device with `adb`, `ffmpeg`, and `adb screencap` for
ground-truth verification. Contributions and other-hardware reports welcome.
