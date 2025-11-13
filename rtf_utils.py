"""Utility functions for handling RTF content and text cleaning."""

import re
import unicodedata


def rtf_to_text(rtf_data):
    """
    Convert RTF data to plain text, handling both string and binary RTF content.
    Returns the original data if conversion fails or if it's not RTF.
    """
    if not rtf_data:
        return rtf_data

    # If it's bytes, try to decode as Latin-1 first
    if isinstance(rtf_data, bytes):
        try:
            # First try UTF-8, fall back to Latin-1
            try:
                rtf_text = rtf_data.decode("utf-8")
            except UnicodeDecodeError:
                rtf_text = rtf_data.decode("latin-1")
        except Exception as e:
            print(f"Error decoding bytes: {e}")
            try:
                # If still failing, try to extract text between {\rtf and }
                rtf_str = str(rtf_data)
                start = rtf_str.find("{\\rtf")
                if start >= 0:
                    end = rtf_str.rfind("}")
                    if end > start:
                        rtf_text = rtf_str[start:end + 1]
                    else:
                        rtf_text = rtf_str[start:]
                else:
                    return f"[Binary data: {len(rtf_data)} bytes]"
            except Exception:
                return f"[Binary data: {len(rtf_data)} bytes]"
    else:
        rtf_text = str(rtf_data)

    # Check if it's RTF (starts with {\rtf)
    rtf_text = rtf_text.strip()
    if not rtf_text.startswith("{\\rtf"):
        return rtf_text

    try:
        # Primeiro, converte escapes hex (ex: \'e7) para o caractere correspondente
        def replace_hex(m):
            try:
                b = bytes([int(m.group(1), 16)])
                return b.decode("latin-1")
            except Exception:
                return ""

        rtf_text = re.sub(r"\\'([0-9a-fA-F]{2})", replace_hex, rtf_text)

        # Converte escapes Unicode do tipo \\uN (onde N pode ser negativo). RTF frequentemente usa decimal.
        def replace_unicode(m):
            try:
                n = int(m.group(1))
                if n < 0:
                    n = 65536 + n
                return chr(n)
            except Exception:
                return ""

        rtf_text = re.sub(r"\\u(-?\d+)", replace_unicode, rtf_text)

        # Remove comandos RTF (control words) como \par, \b0, etc., mantendo o texto
        rtf_text = re.sub(r"\\[a-zA-Z]+-?\d*\s?", " ", rtf_text)
        # Remove escapes residuais como \\~ or \\{
        rtf_text = re.sub(r"\\[^a-zA-Z0-9]", " ", rtf_text)

        # Remove chaves e conteúdo de grupos binários residuais -- mantém o texto simples
        rtf_text = rtf_text.replace("{", " ").replace("}", " ")

        # Normaliza espaços
        text = re.sub(r"\s+", " ", rtf_text).strip()

        return text if text.strip() else rtf_text

    except Exception as e:
        print(f"Error converting RTF: {e}")
        try:
            text = re.sub(r"\\[a-zA-Z0-9]+\s*", " ", rtf_text)
            text = re.sub(r"\{[^}]*\}", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
            return text
        except Exception:
            return rtf_text


def limpar_rtf(texto):
    """
    Limpa texto RTF e remove caracteres especiais.
    """
    # aceitar bytes ou str
    if not texto:
        return ""
    try:
        # rtf_to_text já lida com bytes
        texto_limpo = rtf_to_text(texto)
        if texto_limpo is None:
            return ""
        texto_limpo = str(texto_limpo).strip()

        # remover surrogates e caracteres de controle invisíveis
        texto_limpo = "".join(ch for ch in texto_limpo if not (0xD800 <= ord(ch) <= 0xDFFF))
        texto_limpo = "".join(ch for ch in texto_limpo if unicodedata.category(ch)[0] != "C")

        # Se o texto resultante tiver baixa taxa de caracteres legíveis, extrair substrings legíveis ASCII/Unicode
        total = len(texto_limpo)
        if total == 0:
            return ""
        legiveis = sum(1 for ch in texto_limpo if (ch.isprintable() and not unicodedata.category(ch).startswith("C")))
        ratio = legiveis / total
        if ratio < 0.45:
            # extrai blocos legíveis usando um charset latino razoável (A-Z, acentos, dígitos, pontuação comum)
            # isso evita dependência de módulos Unicode avançados
            latin_pattern = r"[A-Za-zÀ-ÖØ-öø-ÿ0-9\-',.;:()\/&%\s]{4,}"
            parts = re.findall(latin_pattern, texto_limpo)
            parts = [p.strip() for p in parts if p.strip()]
            if parts:
                joined = " ... ".join(parts)
                return limpar_unicode_basico(joined)
            # fallback: keep printable ASCII sequences
            ascii_parts = re.findall(r"[\x20-\x7E]{4,}", texto_limpo)
            if ascii_parts:
                return limpar_unicode_basico(" ... ".join(ascii_parts))

        # remover metadados de estilo que aparecem em alguns RTFs (ex: Calibri; Tahoma; ... Table Simple 1;)
        texto_limpo = re.sub(r"Calibri;[^\n]{0,200}?Table Simple 1;?", " ", texto_limpo, flags=re.IGNORECASE)
        texto_limpo = re.sub(r"_dx_frag_StartFragment", " ", texto_limpo, flags=re.IGNORECASE)

        # Substituir HYPERLINKs: HYPERLINK "url" "texto"  -> texto
        try:
            texto_limpo = re.sub(r'HYPERLINK\s+"([^"]+)"\s+"([^"]+)"', r"\2", texto_limpo, flags=re.IGNORECASE)
            # HYPERLINK "url" texto (sem aspas de exibição)
            texto_limpo = re.sub(r'HYPERLINK\s+"([^"]+)"\s+([^\n\r]+)', r"\2", texto_limpo, flags=re.IGNORECASE)
            # remover eventuais tokens HYPERLINK restantes
            texto_limpo = re.sub(r"\bHYPERLINK\b", " ", texto_limpo, flags=re.IGNORECASE)
        except Exception:
            pass

        # remover longas sequências hex/bin (e.g. arquivos embutidos: começando com PK.. -> 504b03)
        m = re.search(r"(504b03|[0-9a-fA-F]{40,})", texto_limpo)
        if m:
            texto_limpo = texto_limpo[: m.start()].strip()

        return limpar_unicode_basico(texto_limpo)
    except Exception as e:
        print(f"Erro ao limpar RTF: {e}")
        try:
            return limpar_unicode_basico(str(texto))
        except Exception:
            return ""


def limpar_unicode_basico(texto):
    """
    Limpeza básica que não converte caracteres válidos em ?
    """
    if not texto:
        return ""
    # substituições básicas
    texto = (
        texto.replace("\u2013", "-")  # en dash
        .replace("\u2014", "-")  # em dash
        .replace("\u2019", "'")  # aspas curvas
        .replace("\u2018", "'")  # aspas curvas
        .replace("\u201c", '"')  # aspas duplas
        .replace("\u201d", '"')  # aspas duplas
        .replace("\u2022", "-")  # bullet
        .replace("\u2026", "...")  # reticências
        .replace("\xa0", " ")  # non-breaking space
    )

    # Normalização extra: remover marcas combinantes duplicadas e normalizar
    try:
        # decompor
        decomposed = unicodedata.normalize("NFD", texto)
        out_chars = []
        prev_combining = False
        for ch in decomposed:
            cat = unicodedata.category(ch)
            is_comb = cat.startswith("M")  # Mark (combining)
            if is_comb and prev_combining:
                # pular marcas combinantes consecutivas duplicadas
                continue
            out_chars.append(ch)
            prev_combining = is_comb
        recomposed = unicodedata.normalize("NFC", "".join(out_chars))
        texto = recomposed
    except Exception:
        pass

    # Corrige duplicação estranha de cedilha dupla e similares (ocorre em dados RTF corrompidos)
    try:
        texto = re.sub(r"(ç)\1+", r"\1", texto, flags=re.IGNORECASE)
    except Exception:
        pass

    # Colapsar vogais duplicadas idênticas (ex.: 'nãão' -> 'não', 'seráá' -> 'será')
    try:
        vowels = "aáàâãäeéèêiíìîoóòôõuúùûü"
        pattern = r"([" + vowels + r"])\1+"
        texto = re.sub(pattern, r"\1", texto, flags=re.IGNORECASE)
    except Exception:
        pass

    # Retorna texto final limpo
    return texto


def limpar_texto_para_pdf(texto):
    """
    Função específica para limpar texto destinado ao PDF - converte acentos para compatibilidade com Helvetica.
    """
    if not texto or not isinstance(texto, str):
        return ""

    # Primeiro passo: remover caracteres invisíveis problemáticos
    caracteres_invisiveis = ["\u200b", "\u200c", "\u200d", "\ufeff", "\u2060"]
    for char in caracteres_invisiveis:
        texto = texto.replace(char, "")

    # Segundo passo: substituições básicas e seguras usando códigos Unicode
    texto = texto.replace("\u2013", "-")  # en dash
    texto = texto.replace("\u2014", "-")  # em dash
    texto = texto.replace("\u2019", "'")  # aspas curvas direita
    texto = texto.replace("\u2018", "'")  # aspas curvas esquerda
    texto = texto.replace("\u201c", '"')  # aspas duplas esquerda
    texto = texto.replace("\u201d", '"')  # aspas duplas direita
    texto = texto.replace("\u2022", "-")  # bullet point
    texto = texto.replace("\u2026", "...")  # reticências
    texto = texto.replace("\u00a0", " ")  # non-breaking space
    texto = texto.replace("\u00b0", "o")  # símbolo de grau

    # Terceiro passo: converter acentos para ASCII usando normalização
    resultado = ""
    for char in texto:
        ascii_val = ord(char)

        if ascii_val < 32:  # Caracteres de controle
            if char in ["\n", "\r", "\t"]:
                resultado += char
            else:
                resultado += " "
        elif ascii_val <= 126:  # ASCII básico - manter como está
            resultado += char
        else:  # Caracteres especiais - tentar converter
            try:
                # Normalização NFD para decompor acentos
                normalized = unicodedata.normalize("NFD", char)
                # Pegar apenas a letra base, removendo marcas diacríticas
                ascii_char = "".join(c for c in normalized if unicodedata.category(c) != "Mn")
                if ascii_char and ord(ascii_char[0]) <= 126:
                    resultado += ascii_char
                else:
                    # Casos especiais que não normalizam bem
                    if char == "ç":
                        resultado += "c"
                    elif char == "Ç":
                        resultado += "C"
                    elif char == "ñ":
                        resultado += "n"
                    elif char == "Ñ":
                        resultado += "N"
                    else:
                        resultado += "?"  # Último recurso
            except Exception:
                resultado += "?"

    # Quarto passo: limpeza final
    # Remove espaços duplos e garante apenas caracteres seguros
    texto_final = " ".join(resultado.split()).strip()

    return texto_final


def extract_first_image_from_rtf(rtf_data):
    r"""
    Tenta extrair a primeira imagem embutida em um bloco RTF (\pict).
    Retorna tupla (bytes, mime_type) ou (None, None) se não encontrar.
    """
    if not rtf_data:
        return None, None

    # normalize to string (latin-1 preserves raw byte values 0-255)
    if isinstance(rtf_data, bytes):
        try:
            s = rtf_data.decode("latin-1")
        except Exception:
            s = rtf_data.decode("utf-8", errors="ignore")
    else:
        s = str(rtf_data)

    def find_group_at_pos(text, pos_open):
        """Given index of an opening brace, return substring of the balanced group."""
        depth = 0
        for i in range(pos_open, len(text)):
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[pos_open:i + 1]
        return text[pos_open:]

    # scan for occurrences of '\pict' and extract the enclosing group using brace-matching
    for m in re.finditer(r"\\pict\b", s, flags=re.IGNORECASE):
        pict_pos = m.start()
        # find the opening brace '{' that starts the group containing this \pict
        open_brace_pos = s.rfind("{", 0, pict_pos)
        if open_brace_pos == -1:
            # fallback: use pict_pos as start
            open_brace_pos = pict_pos
        block = find_group_at_pos(s, open_brace_pos)

        # identify mime by control words
        if re.search(r"\\pngblip", block, flags=re.IGNORECASE):
            pass
        elif re.search(r"\\jpegblip", block, flags=re.IGNORECASE):
            pass

        # If there is a \binN control, try to find the raw binary immediately after it
        bin_match = re.search(r"\\bin(\d+)\b", block)
        if bin_match:
            try:
                bin_len = int(bin_match.group(1))
                # raw bytes are likely present in the decoded latin-1 string after the control
                start = block.find(bin_match.group(0)) + len(bin_match.group(0))
                # skip optional spaces/newlines
                while start < len(block) and block[start] in (" ", "\r", "\n", "\t"):
                    start += 1
                raw = block[start:]
                # take up to bin_len bytes from raw using latin-1 ord mapping
                byte_vals = [ord(ch) for ch in raw[:bin_len]]
                if len(byte_vals) >= 4:
                    img_bytes = bytes(byte_vals)
                    if img_bytes.startswith(b"\x89PNG"):
                        return img_bytes, "image/png"
                    if img_bytes.startswith(b"\xff\xd8"):
                        return img_bytes, "image/jpeg"
            except Exception:
                pass

        # try to find hex sequences inside the block (continuous hex characters)
        # first look for long hex strings (likely embedded file data)
        for hex_match in re.finditer(r"([0-9A-Fa-f]{40,})", block):
            hexclean = hex_match.group(1)
            try:
                img_bytes = bytes.fromhex(hexclean)
                if img_bytes.startswith(b"\x89PNG"):
                    return img_bytes, "image/png"
                if img_bytes.startswith(b"\xff\xd8"):
                    return img_bytes, "image/jpeg"
            except Exception:
                continue

        # allow hex with spaces/newlines between bytes
        hex_with_spaces = re.search(r"(([0-9A-Fa-f]{2}[\s\r\n]+){20,}[0-9A-Fa-f]{2})", block)
        if hex_with_spaces:
            hexdata = re.sub(r"[^0-9A-Fa-f]", "", hex_with_spaces.group(1))
            try:
                img_bytes = bytes.fromhex(hexdata)
                if img_bytes.startswith(b"\x89PNG"):
                    return img_bytes, "image/png"
                if img_bytes.startswith(b"\xff\xd8"):
                    return img_bytes, "image/jpeg"
            except Exception:
                pass

        # decimal sequences inside the block
        dec_match = re.search(r"((?:\d{1,3}[\s,\r\n]){20,}\d{1,3})", block)
        if dec_match:
            nums = re.findall(r"\d{1,3}", dec_match.group(1))
            try:
                byte_vals = [int(n) for n in nums if 0 <= int(n) <= 255]
                img_bytes = bytes(byte_vals)
                if img_bytes.startswith(b"\x89PNG"):
                    return img_bytes, "image/png"
                if img_bytes.startswith(b"\xff\xd8"):
                    return img_bytes, "image/jpeg"
            except Exception:
                pass

    # fallback: scan entire document for long hex or decimal sequences
    for hex_match in re.finditer(r"([0-9A-Fa-f]{80,})", s):
        try:
            img_bytes = bytes.fromhex(hex_match.group(1))
            if img_bytes.startswith(b"\x89PNG"):
                return img_bytes, "image/png"
            if img_bytes.startswith(b"\xff\xd8"):
                return img_bytes, "image/jpeg"
        except Exception:
            continue

    for dec_match in re.finditer(r"((?:\d{1,3}[\s,\r\n]){40,}\d{1,3})", s):
        nums = re.findall(r"\d{1,3}", dec_match.group(1))
        try:
            byte_vals = [int(n) for n in nums if 0 <= int(n) <= 255]
            img_bytes = bytes(byte_vals)
            if img_bytes.startswith(b"\x89PNG"):
                return img_bytes, "image/png"
            if img_bytes.startswith(b"\xff\xd8"):
                return img_bytes, "image/jpeg"
        except Exception:
            continue

    # Final fallback: procurar uma assinatura PNG/JPEG em hex em qualquer lugar do documento
    # e coletar caracteres hex (permitindo espaços/newlines) a partir da assinatura.
    try:
        sig = re.search(r"(89504E47|FFD8FF)", s, flags=re.IGNORECASE)
        if sig:
            start = sig.start()
            hex_parts = []
            # coletar até encontrar o primeiro caractere que não seja hex/nova linha/espaco
            for ch in s[start:]:
                if ch in "0123456789abcdefABCDEF" or ch.isspace():
                    hex_parts.append(ch)
                else:
                    # pare ao encontrar um controle RTF (\, {, }) ou outro caractere
                    break
            hex_str = "".join(hex_parts)
            hex_clean = re.sub(r"[^0-9A-Fa-f]", "", hex_str)
            # deve ser suficientemente grande para ser um arquivo de imagem
            if len(hex_clean) >= 32:
                try:
                    img_bytes = bytes.fromhex(hex_clean)
                    if img_bytes.startswith(b"\x89PNG"):
                        return img_bytes, "image/png"
                    if img_bytes.startswith(b"\xff\xd8"):
                        return img_bytes, "image/jpeg"
                except Exception:
                    pass
    except Exception:
        pass

    return None, None
