from striprtf.striprtf import rtf_to_text


def extrair_texto_rtf(rtf_text):
    """
    Extrai texto de um documento RTF usando a biblioteca striprtf.
    """

    def safe_str(obj):
        try:
            return str(obj)
        except UnicodeEncodeError:
            try:
                return obj.encode("utf-8", errors="replace").decode("utf-8")
            except Exception:
                return "[Dados binários ou inválidos]"

    try:
        # Se for bytes, converte para string
        if isinstance(rtf_text, bytes):
            try:
                rtf_text = rtf_text.decode("utf-8")
            except UnicodeDecodeError:
                try:
                    rtf_text = rtf_text.decode("latin-1")
                except Exception:
                    return "[Erro ao decodificar os dados]"

        # Usa a biblioteca striprtf para converter RTF para texto puro
        text = rtf_to_text(rtf_text)

        # Remove caracteres de controle e normaliza espaços
        text = " ".join(text.split())

        # Trata caracteres especiais de forma segura
        try:
            return text.encode("utf-8", errors="replace").decode("utf-8").strip()
        except Exception:
            return safe_str(text).strip()

    except Exception as e:
        try:
            return f"[Erro ao processar RTF: {str(e).encode('utf-8', errors='replace').decode('utf-8')}]"
        except Exception:
            return "[Erro ao processar RTF]"


# Exemplo de uso
if __name__ == "__main__":
    # Exemplo de RTF com sequências de escape
    rtf_text = r"""{{\rtf1\deff0{\fonttbl{\f0 Calibri;}{\f1 Tahoma;}}
    {\colortbl ;\red0\green0\blue255 ;}
    {\*\defchp \fs22}
    {\stylesheet {\ql\fs22 Normal;}}
    {\info{\creatim\yr2025\mo10\dy3\hr17\min12}{\version1}}
    \nouicompat\splytwnine\htmautsp\sectd\pard\plain\ql
    {\lang1046\langfe1046\f1\fs20\cf0
    Libera\u231\'e7\u227\'e3o foi feita e est\u225\'e1 funcionando corretamente
    }
    \f1\fs20\par
    }"""

    print("Texto RTF original:")
    print("-" * 60)
    print(rtf_text)
    print("-" * 60)

    texto_extraido = extrair_texto_rtf(rtf_text)

    print("\nTexto extraído:")
    print("-" * 60)
    print(texto_extraido)
    print("-" * 60)
