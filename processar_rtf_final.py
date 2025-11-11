import re

def extrair_texto_rtf(rtf_text):
    """
    Extrai texto de um documento RTF, lidando com caracteres especiais e Unicode.
    """
    if not rtf_text:
        return ""
    
    # Se for bytes, converte para string
    if isinstance(rtf_text, bytes):
        try:
            rtf_text = rtf_text.decode('utf-8')
        except UnicodeDecodeError:
            try:
                rtf_text = rtf_text.decode('latin-1')
            except:
                return "[Erro ao decodificar os dados]"
    
    # Se não começar com {\rtf, provavelmente já está em texto simples
    if not rtf_text.strip().startswith('{\\rtf'):
        return limpar_texto(rtf_text)
    
    try:
        # Extrai o texto entre as chaves mais externas
        stack = []
        text_parts = []
        
        i = 0
        while i < len(rtf_text):
            if rtf_text[i] == '{':
                stack.append(i)
                i += 1
            elif rtf_text[i] == '}':
                if stack:
                    start = stack.pop()
                    if not stack:  # Se for o fechamento do grupo principal
                        text_parts.append(rtf_text[start+1:i])
                i += 1
            elif rtf_text[i] == '\\':
                # Pula comandos RTF como \u231\'e7
                if i + 1 < len(rtf_text) and rtf_text[i+1] == 'u':
                    # Pula \u e os próximos 4 caracteres (código Unicode)
                    i += 6
                elif i + 1 < len(rtf_text) and rtf_text[i+1] == '\'':
                    # Pula \' e o próximo caractere (código de caractere)
                    i += 3
                else:
                    # Pula até o próximo espaço ou caractere especial
                    i += 1
                    while i < len(rtf_text) and rtf_text[i] not in ' \{};':
                        i += 1
            else:
                # Se não estiver em um grupo aninhado, adiciona o caractere
                if not stack:
                    text_parts.append(rtf_text[i])
                i += 1
        
        # Junta todas as partes
        text = ''.join(text_parts)
        
        # Remove comandos RTF remanescentes
        text = re.sub(r'\\[a-zA-Z0-9*]+\s*', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        
        return text
        
    except Exception as e:
        print(f"Erro ao processar RTF: {e}")
        # Tenta um método mais simples se o primeiro falhar
        try:
            text = re.sub(r'\\[a-zA-Z0-9*]+\s*', ' ', rtf_text)
            text = re.sub(r'\{[^}]*\}', ' ', text)
            text = re.sub(r'\s+', ' ', text).strip()
            return text
        except:
            return "[Erro ao processar o texto RTF]"

def limpar_texto(texto):
    """
    Limpa o texto removendo caracteres especiais e normalizando espaços.
    """
    if not texto:
        return ""
    
    # Remove caracteres de controle
    texto = ''.join(c for c in texto if c.isprintable() or c.isspace())
    
    # Normaliza espaços
    texto = ' '.join(texto.split())
    
    return texto

def main():
    # Exemplo de uso
    rtf_text = r"""
    {\rtf1\deff0{\fonttbl{\f0 Calibri;}{\f1 Tahoma;}}
    {\colortbl ;\red0\green0\blue255 ;}
    {\*\defchp \fs22}
    {\stylesheet {\ql\fs22 Normal;}}
    {\info{\creatim\yr2025\mo10\dy3\hr17\min12}{\version1}}
    \nouicompat\splytwnine\htmautsp\sectd\pard\plain\ql
    {\lang1046\langfe1046\f1\fs20\cf0 
    Libera\u231\'e7\u227\'e3o foi feita e est\u225\'e1 funcionando corretamente
    }
    \f1\fs20\par
    }
    """
    
    texto_limpo = extrair_texto_rtf(rtf_text)
    print("Texto extraído:")
    print("-" * 60)
    print(texto_limpo)
    print("-" * 60)

if __name__ == "__main__":
    main()
