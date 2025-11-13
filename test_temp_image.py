import base64
import os
from main import (
    save_temp_image_and_get_url,
    temp_image_exists_on_disk,
    _temp_image_path_for_key,
    _ext_for_mime,
    _image_cache_key,
)


def main():
    # 1x1 PNG (base64)
    png_b64 = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII="
    )
    png_bytes = base64.b64decode(png_b64)
    mime = "image/png"

    rtf_sample = "teste-extrato-imagem-1110195"  # usar conteúdo que gera a mesma chave
    key = _image_cache_key(rtf_sample)
    print(f"[TEST] key={key}")

    url = save_temp_image_and_get_url(key, png_bytes, mime)
    print(f"[TEST] save_temp_image_and_get_url returned: {url}")

    exists = temp_image_exists_on_disk(key)
    print(f"[TEST] temp_image_exists_on_disk: {exists}")

    expected_path = _temp_image_path_for_key(key, _ext_for_mime(mime))
    print(f"[TEST] expected path: {expected_path}")

    if expected_path.exists():
        with open(expected_path, "rb") as f:
            data = f.read()
        print(f"[TEST] file length: {len(data)}")
        sig = data[:8]
        print(f"[TEST] first 8 bytes: {sig}")
        is_png = sig.startswith(b"\x89PNG\r\n\x1a\n")
        print(f"[TEST] looks like PNG: {is_png}")
    else:
        print("[TEST] file not found on disk")


if __name__ == "__main__":
    main()
