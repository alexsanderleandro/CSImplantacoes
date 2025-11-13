import sys
from pathlib import Path
import shutil
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "cache_images" / "tmp"
BAD = CACHE / "bad"
LOG = ROOT / "cache_images" / "temp_img_debug.log"

try:
    from PIL import Image, ImageFile
    ImageFile.LOAD_TRUNCATED_IMAGES = True
except Exception:
    print("Pillow not available; aborting.")
    sys.exit(2)

BAD.mkdir(parents=True, exist_ok=True)

moved = []
replaced = []
errors = []

for p in sorted(CACHE.glob("*.png")):
    try:
        size = p.stat().st_size
        action = None
        # try to open tolerantly
        try:
            img = Image.open(p)
            img.load()
            bands = img.getbands()
            alpha_present = 'A' in bands or img.mode in ('LA','RGBA') or ('transparency' in img.info)
            a_max = None
            if alpha_present:
                a = img.convert('RGBA').split()[-1]
                a_min, a_max = a.getextrema()
            # decide if suspect: truncated (small) or fully transparent
            suspect = (size < 512) or (alpha_present and a_max == 0)
            if suspect:
                # backup
                dest = BAD / p.name
                idx = 1
                while dest.exists():
                    dest = BAD / f"{p.stem}.{idx}{p.suffix}"
                    idx += 1
                shutil.move(str(p), str(dest))
                moved.append((p.name, size, dest.name))
                # create flattened replacement from the image (if loadable) or create blank
                try:
                    if 'img' in locals():
                        bg = Image.new('RGB', img.size, (255,255,255))
                        try:
                            if img.mode in ('RGBA','LA'):
                                bg.paste(img, mask=img.split()[-1])
                            else:
                                bg.paste(img)
                        except Exception:
                            bg.paste(img)
                        bg.save(p, format='PNG')
                        replaced.append((p.name, dest.name, p.stat().st_size))
                    else:
                        # cannot load image, write a 1x1 white placeholder
                        ph = Image.new('RGB', (1,1), (255,255,255))
                        ph.save(p, format='PNG')
                        replaced.append((p.name, dest.name, p.stat().st_size))
                except Exception as e:
                    errors.append((p.name, str(e)))
                    # attempt to restore original if replacement failed
                    try:
                        shutil.move(str(dest), str(p))
                    except Exception:
                        pass
            else:
                # ok, keep
                pass
        except Exception as e:
            # open failed -> treat as truncated
            dest = BAD / p.name
            idx = 1
            while dest.exists():
                dest = BAD / f"{p.stem}.{idx}{p.suffix}"
                idx += 1
            shutil.move(str(p), str(dest))
            moved.append((p.name, size, dest.name))
            try:
                # create a placeholder flattened file (white background) or attempt to create from partial bytes
                ph = Image.new('RGB', (1,1), (255,255,255))
                ph.save(p, format='PNG')
                replaced.append((p.name, dest.name, p.stat().st_size))
            except Exception as e2:
                errors.append((p.name, f"replace failed: {e2}"))
    except Exception as e:
        errors.append((p.name, str(e)))

# append log
try:
    with open(LOG, 'a', encoding='utf-8') as f:
        ts = datetime.utcnow().isoformat() + 'Z'
        for m in moved:
            f.write(f"{ts} [REPAIR] moved {m[0]} size={m[1]} backup={m[2]}\n")
        for r in replaced:
            f.write(f"{ts} [REPAIR] replaced {r[0]} backup={r[1]} new_size={r[2]}\n")
        for e in errors:
            f.write(f"{ts} [REPAIR] error {e[0]} {e[1]}\n")
except Exception:
    pass

# summary to stdout
print("moved:")
for m in moved:
    print(" -", m)
print("replaced:")
for r in replaced:
    print(" -", r)
print("errors:")
for e in errors:
    print(" -", e)

# exit code
if errors:
    sys.exit(1)
sys.exit(0)
