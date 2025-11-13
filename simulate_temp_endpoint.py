import os
from main import _temp_image_path_for_key, _ext_for_mime

key = "124b2dcade80a1a20eeb628d71bdbcabd21f57804ae1b7079e820d6375185f19"

path = _temp_image_path_for_key(key, _ext_for_mime("image/png"))
print(f"Simulating GET /_temp_img/{key}")
print(f"Expected file: {path}")
if path.exists():
    b = path.read_bytes()
    mime = "image/png"
    print(f"Status: 200")
    print(f"Content-Type: {mime}")
    print(f"Content-Length: {len(b)} bytes")
else:
    print("Status: 404 (file not found)")
