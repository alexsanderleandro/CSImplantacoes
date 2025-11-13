import sys
from pathlib import Path

p = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("cache_images/tmp/db871d867fe87c7d4e792899b66f3bf91ffa78ca34f4786ac41c2555faf37912.png")
print(f"PATH: {p.resolve()}")
print("EXISTS:", p.exists())
if not p.exists():
    sys.exit(1)
print("SIZE:", p.stat().st_size)
print("FIRST 64 BYTES HEX:", p.read_bytes()[:64].hex())

try:
    from PIL import Image, ImageFile
    # allow Pillow to attempt loading truncated images (best-effort)
    ImageFile.LOAD_TRUNCATED_IMAGES = True
except Exception as e:
    print("PIL not installed or failed to import:", e)
    sys.exit(0)

try:
    img = Image.open(p)
    print("FORMAT:", img.format)
    print("MODE:", img.mode)
    print("SIZE:", img.size)
    img.load()
    bands = img.getbands()
    print("BANDS:", bands)
    if 'A' in bands or img.mode in ('LA','RGBA') or 'transparency' in img.info:
        alpha = img.convert('RGBA').split()[-1]
        a_min, a_max = alpha.getextrema()
        print("ALPHA extrema:", (a_min, a_max))
        print("FULLY TRANSPARENT?", a_max == 0)
    else:
        print("NO alpha channel detected")
    # print top-left pixel (RGBA)
    px = img.convert('RGBA').getpixel((0,0))
    print("pixel (0,0) RGBA:", px)
    # create flattened copy for diagnostics
    out = p.with_name(p.stem + "_flattened.png")
    bg = Image.new("RGB", img.size, (255,255,255))
    try:
        if img.mode in ("RGBA", "LA"):
            bg.paste(img, mask=img.split()[-1])
        else:
            bg.paste(img)
        bg.save(out, format='PNG')
        print("WROTE flattened copy to:", out, "size=", out.stat().st_size)
    except Exception as e:
        print("Failed to write flattened copy:", e)

except Exception as e:
    print("Failed to open/process image:", e)
    raise
