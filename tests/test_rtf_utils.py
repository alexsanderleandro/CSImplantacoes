import unittest

from rtf_utils import limpar_rtf


class TestRtfUtils(unittest.TestCase):
    def test_plain_rtf(self):
        rtf = r"{\rtf1\ansi This is plain text}"
        out = limpar_rtf(rtf)
        self.assertIn("This is plain text", out)

    def test_hex_escape(self):
        rtf = r"{\rtf1\ansi Ol\'e1}"  # Olá (\'e1 -> á in latin1)
        out = limpar_rtf(rtf)
        self.assertIn("Olá", out)

    def test_unicode_escape(self):
        rtf = r"{\rtf1\ansi \u233 }"  # \u233 -> é
        out = limpar_rtf(rtf)
        self.assertIn("é", out)

    def test_hyperlink_removal(self):
        rtf = r"{\rtf1\ansi HYPERLINK \"file.pdf\" \"Relat\'f3rio\"}"  # Relatório
        out = limpar_rtf(rtf)
        self.assertIn("Relat", out)
        self.assertNotIn("HYPERLINK", out)

    def test_binary_tail_removed(self):
        rtf = r"{\rtf1\ansi Texto antes 504b030414000200080000}"  # PK signature (zip)
        out = limpar_rtf(rtf)
        self.assertIn("Texto antes", out)
        self.assertNotIn("504b0304", out)

    def test_bytes_input(self):
        data = b"{\\rtf1\\ansi Ol\\'e1}"
        out = limpar_rtf(data)
        self.assertIn("Olá", out)


if __name__ == "__main__":
    unittest.main()
