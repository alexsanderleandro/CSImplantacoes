#!/usr/bin/env python3
"""Script de depuração rápido para verificar extração de imagem de TextoIteracao.
Uso:
    python debug_extract_image.py 1110195

Imprime:
- existência de TextoIteracao
- chave de cache (sha256)
- presença do arquivo de flag em cache_images
- resultado de extract_first_image_from_rtf (has_image, mime, bytes_len)

"""
import hashlib
import os
import sys

from authentication import get_db_connection
from rtf_utils import extract_first_image_from_rtf

CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache_images")


def image_cache_key(content):
    if content is None:
        return None
    try:
        if isinstance(content, (bytes, bytearray)):
            b = bytes(content)
        else:
            b = str(content).encode("utf-8", errors="ignore")
        return hashlib.sha256(b).hexdigest()
    except Exception:
        return None


def flag_path_for_key(key):
    return os.path.join(CACHE_DIR, f"{key}.hasimg") if key else None


def fetch_latest_text_for_atendimento(num):
    conn = get_db_connection()
    cur = conn.cursor()
    sql = (
        "SELECT TOP 1 CONVERT(NVARCHAR(MAX), TextoIteracao) "
        "FROM AtendimentoIteracao WITH (NOLOCK) "
        "WHERE NumAtendimento = ? AND Desdobramento = 0 "
        "ORDER BY NumIteracao DESC"
    )
    cur.execute(sql, (num,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return None
    return row[0]


def main():
    if len(sys.argv) < 2:
        print("Usage: python debug_extract_image.py <NumAtendimento>")
        sys.exit(1)
    num = sys.argv[1]
    print(f"Debug extract for NumAtendimento={num}")
    texto = fetch_latest_text_for_atendimento(num)
    if texto is None:
        print("No TextoIteracao found for this atendimento.")
        return
    print("TextoIteracao length:", len(str(texto)))
    key = image_cache_key(texto)
    print("Cache key:", key)
    flag = flag_path_for_key(key)
    print("Flag path:", flag)
    if flag and os.path.exists(flag):
        try:
            with open(flag, "r", encoding="utf-8") as f:
                val = f.read(1)
            print("Flag file exists, value:", val)
        except Exception as e:
            print("Flag file exists but cannot be read:", e)
    else:
        print("No flag file present")

    try:
        img_bytes, mime = extract_first_image_from_rtf(texto)
        has = bool(img_bytes and mime)
        print("Extractor result -> has_image:", has, "mime:", mime, "bytes_len:", len(img_bytes) if img_bytes else 0)
        if img_bytes:
            print("First 64 bytes (hex):", img_bytes[:64].hex())
    except Exception as e:
        print("Extractor raised:", e)


if __name__ == "__main__":
    main()
