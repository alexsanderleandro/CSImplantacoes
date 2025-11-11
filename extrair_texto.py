import re

def extrair_texto_rtf(rtf_text):
    # Remove comandos RTF e mantém apenas o texto
    # Remove comandos RTF como \comando
    text = re.sub(r'\\[a-zA-Z0-9]+\s*', ' ', rtf_text)
    # Remove blocos entre chaves {}
    text = re.sub(r'\{[^}]*\}', ' ', text)
    # Remove múltiplos espaços
    text = re.sub(r'\s+', ' ', text).strip()
    return text

# Texto RTF para teste
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

# Processa o texto RTF
print("Processando texto RTF...")
texto_limpo = extrair_texto_rtf(rtf_text)

# Exibe o resultado
print("\nTexto extraído:")
print("-" * 50)
print(texto_limpo)
print("-" * 50)

# Teste com a string que você forneceu
texto_errado = """
Interação recente: green0;splytwninesectdplainlangfe1046fs20
Libera'e7'e3o foi feita e est'e1 funcionando corretamente
"""

print("\nTeste com o texto já processado:")
print("-" * 50)
print(extrair_texto_rtf(texto_errado))
print("-" * 50)
