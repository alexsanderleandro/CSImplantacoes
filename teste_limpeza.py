from rtf_utils import limpar_rtf

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

# Texto já processado para teste
texto_processado = """
Interação recente: green0;splytwninesectdplainlangfe1046fs20
Libera'e7'e3o foi feita e est'e1 funcionando corretamente
"""

def testar_limpeza(texto, descricao):
    print(f"\nTestando: {descricao}")
    print("-" * 50)
    print("Antes:")
    print(texto)
    print("\nDepois:")
    print(limpar_rtf(texto))
    print("-" * 50)

# Testa o texto RTF
testar_limpeza(rtf_text, "Texto RTF")

# Testa o texto já processado
testar_limpeza(texto_processado, "Texto já processado")
