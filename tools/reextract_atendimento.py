import sys
from pathlib import Path
# ensure project root is on sys.path so local modules (authentication, rtf_utils) can be imported
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import hashlib
import shutil
from datetime import datetime

from authentication import get_db_connection
from rtf_utils import extract_first_image_from_rtf

CACHE_DIR = ROOT / "cache_images" / "tmp"
BAD_DIR = CACHE_DIR / "bad"
FLAG_DIR = ROOT / "cache_images"
LOG = FLAG_DIR / "temp_img_debug.log"

CACHE_DIR.mkdir(parents=True, exist_ok=True)
BAD_DIR.mkdir(parents=True, exist_ok=True)

atendimento = sys.argv[1] if len(sys.argv) > 1 else "1110195"
print(f"Re-extracting images for atendimento={atendimento}")

sql = """
SELECT AI.TextoIteracao
FROM AtendimentoIteracao AI WITH (NOLOCK)
WHERE AI.NumAtendimento = ?
  AND AI.Desdobramento = 0
ORDER BY AI.NumIteracao DESC
"""

found = []
try:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(sql, (atendimento,))
    rows = cur.fetchall()
    for row in rows:
        texto = row[0]
        img_bytes, mime = extract_first_image_from_rtf(texto)
        if img_bytes:
            key = hashlib.sha256(img_bytes if isinstance(img_bytes, (bytes, bytearray)) else str(img_bytes).encode('utf-8')).hexdigest()
            ext = '.png' if 'png' in (mime or '').lower() else ('.jpg' if 'jpeg' in (mime or '').lower() or 'jpg' in (mime or '').lower() else '.bin')
            dest = CACHE_DIR / f"{key}{ext}"
            # backup existing
            if dest.exists():
                b = BAD_DIR / dest.name
                idx = 1
                while b.exists():
                    b = BAD_DIR / f"{dest.stem}.{idx}{dest.suffix}"
                    idx += 1
                shutil.move(str(dest), str(b))
                print(f"Backed up existing {dest} -> {b}")
            # write new bytes
            with open(dest, 'wb') as f:
                if isinstance(img_bytes, str):
                    f.write(img_bytes.encode('latin-1'))
                else:
                    f.write(img_bytes)
            # write flag
            flag = FLAG_DIR / f"{key}.hasimg"
            with open(flag, 'w', encoding='utf-8') as ff:
                ff.write('1')
            # log
            try:
                ts = datetime.utcnow().isoformat() + 'Z'
                with open(LOG, 'a', encoding='utf-8') as lf:
                    lf.write(f"{ts} [REEXTRACT] atendimento={atendimento} wrote path={dest} mime={mime} bytes={dest.stat().st_size}\n")
            except Exception:
                pass
            found.append((dest.name, dest.stat().st_size, mime))
    cur.close()
    conn.close()
except Exception as e:
    print(f"DB error or other: {e}")

print('done. found:', found)
