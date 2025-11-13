import os
import unittest

from rtf_utils import extract_first_image_from_rtf


class TestRtfExtract(unittest.TestCase):
    def test_extract_from_dump(self):
        path = os.path.join(os.path.dirname(__file__), "texto_1110195.rtf")
        self.assertTrue(os.path.exists(path), f"RTF dump not found at {path}")
        with open(path, "rb") as f:
            data = f.read()
        img_bytes, mime = extract_first_image_from_rtf(data)
        self.assertIsNotNone(img_bytes, "No image bytes returned")
        self.assertIsNotNone(mime, "No mime returned")
        # validate magic bytes
        if mime == "image/png":
            self.assertTrue(img_bytes.startswith(b"\x89PNG"), "Extracted bytes do not start with PNG signature")
        elif mime == "image/jpeg":
            self.assertTrue(img_bytes.startswith(b"\xff\xd8"), "Extracted bytes do not start with JPEG signature")
        else:
            self.fail(f"Unexpected mime: {mime}")


if __name__ == "__main__":
    unittest.main()
