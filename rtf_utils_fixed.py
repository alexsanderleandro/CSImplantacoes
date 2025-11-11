"""Utility functions for handling RTF content and text cleaning."""
import re
import unicodedata

def rtf_to_text(rtf_data):
    """
    Convert RTF data to plain text, handling both string and binary RTF content.
    Returns the original data if conversion fails or if it's not RTF.
    """
    if not rtf_data:
        return ""

    # If it's bytes, try to decode as Latin-1 first
    if isinstance(rtf_data, bytes):
        try:
            # First try UTF-8, fall back to Latin-1
            try:
                rtf_text = rtf_data.decode('utf-8')
            except UnicodeDecodeError:
                rtf_text = rtf_data.decode('latin-1')
        except Exception as e:
            print(f"Error decoding bytes: {e}")
            try:
                # If still failing, try to extract text between {\rtf and }
                rtf_str = str(rtf_data)
                start = rtf_str.find('{\\rtf')
                if start >= 0:
                    end = rtf_str.rfind('}')
                    if end > start:
                        rtf_text = rtf_str[start:end+1]
                    else:
                        rtf_text = rtf_str[start:]
                else:
                    return f"[Binary data: {len(rtf_data)} bytes]"
            except:
                return f"[Binary data: {len(rtf_data)} bytes]"
    else:
        rtf_text = str(rtf_data)
    
    # Check if it's RTF (starts with {\rtf)
    rtf_text = rtf_text.strip()
    if not rtf_text.startswith('{\\rtf'):
        return rtf_text
    
    try:
        # Remove os comandos RTF e mantém apenas o texto
        # Primeiro, remove os blocos de controle
        text = re.sub(r'\\([a-z0-9*]+|.)', ' ', rtf_text, flags=re.IGNORECASE)
        # Remove os blocos entre chaves
        text = re.sub(r'\{[^}]*\}', ' ', text)
        # Remove múltiplos espaços e quebras de linha
        text = ' '.join(text.split())
        
        # Tenta decodificar sequências Unicode
        def decode_unicode(match):
            try:
                return chr(int(match.group(1), 16))
            except:
                return match.group(0)
                
        text = re.sub(r'\\u([0-9a-fA-F]{4})', decode_unicode, text)
        
        # Remove caracteres de controle não imprimíveis
        text = ''.join(c for c in text if c.isprintable() or c.isspace())
        
        return text.strip()
        
    except Exception as e:
        print(f"Error converting RTF: {e}")
        # Se tudo falhar, tenta um método mais simples
        try:
            text = re.sub(r'\\[a-zA-Z0-9*]+\s*', ' ', rtf_text)
            text = re.sub(r'\{[^}]*\}', ' ', text)
            text = re.sub(r'\s+', ' ', text).strip()
            return text
        except:
            return rtf_text  # Retorna o original se todas as conversões falharem

def limpar_rtf(texto):
    """
    Limpa texto RTF e remove caracteres especiais.
    """
    if not texto or not isinstance(texto, str):
        return ""
    try:
        texto_limpo = rtf_to_text(texto)
        return limpar_unicode_basico(texto_limpo)
    except Exception as e:
        print(f"Erro ao limpar RTF: {e}")
        return texto

def limpar_unicode_basico(texto):
    """
    Limpeza básica que não converte caracteres válidos em ?
    """
    if not texto:
        return ""
    return (
        texto.replace("\u2013", "-")      # en dash
             .replace("\u2014", "-")      # em dash
             .replace("\u2019", "'")      # aspas curvas
             .replace("\u2018", "'")      # aspas curvas
             .replace("\u201c", '"')      # aspas duplas
             .replace("\u201d", '"')      # aspas duplas
             .replace("\u2022", "-")      # bullet
             .replace("\u2026", "...")    # reticências
             .replace("\xa0", " ")        # non-breaking space
    )

def limpar_texto_para_pdf(texto):
    """
    Função específica para limpar texto destinado ao PDF - converte acentos para compatibilidade com Helvetica.
    """
    if not texto or not isinstance(texto, str):
        return ""
    
    # Primeiro passo: remover caracteres invisíveis problemáticos
    caracteres_invisiveis = [
        '\u200b', '\u200c', '\u200d', '\ufeff', '\u2060'
    ]
    for char in caracteres_invisiveis:
        texto = texto.replace(char, '')
    
    # Segundo passo: substituições básicas e seguras usando códigos Unicode
    texto = texto.replace('\u2013', '-')   # en dash
    texto = texto.replace('\u2014', '-')   # em dash  
    texto = texto.replace('\u2019', "'")   # aspas curvas direita
    texto = texto.replace('\u2018', "'")   # aspas curvas esquerda
    texto = texto.replace('\u201c', '"')   # aspas duplas esquerda
    texto = texto.replace('\u201d', '"')   # aspas duplas direita
    texto = texto.replace('\u2022', '-')   # bullet point
    texto = texto.replace('\u2026', '...')  # reticências
    texto = texto.replace('\u00a0', ' ')   # non-breaking space
    texto = texto.replace('\u00b0', 'o')   # símbolo de grau
    
    # Terceiro passo: converter acentos para ASCII usando normalização
    resultado = ""
    for char in texto:
        ascii_val = ord(char)
        
        if ascii_val < 32:  # Caracteres de controle
            if char in ['\n', '\r', '\t']:
                resultado += char
            else:
                resultado += ' '
        elif ascii_val <= 126:  # ASCII básico - manter como está
            resultado += char
        else:  # Caracteres especiais - tentar converter
            try:
                # Normalização NFD para decompor acentos
                normalized = unicodedata.normalize('NFD', char)
                # Pegar apenas a letra base, removendo marcas diacríticas
                ascii_char = ''.join(c for c in normalized if unicodedata.category(c) != 'Mn')
                if ascii_char and ord(ascii_char[0]) <= 126:
                    resultado += ascii_char
                else:
                    # Casos especiais que não normalizam bem
                    if char == 'ç': 
                        resultado += 'c'
                    elif char == 'Ç': 
                        resultado += 'C'
                    elif char == 'ñ': 
                        resultado += 'n'
                    elif char == 'Ñ': 
                        resultado += 'N'
                    else: 
                        resultado += '?'  # Último recurso
            except:
                resultado += '?'
    
    # Quarto passo: limpeza final
    # Remove espaços duplos e garante apenas caracteres seguros
    texto_final = ' '.join(resultado.split()).strip()
    
    return texto_final
