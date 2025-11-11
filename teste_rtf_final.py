import sys
import io
from rtf_utils import limpar_rtf

# Configura a saída para UTF-8
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

def limpar_e_mostrar(texto, descricao):
    print(f"\n{'-'*60}")
    print(f"Teste: {descricao}")
    print("-"*60)
    print("Texto original:")
    print(texto)
    
    try:
        resultado = limpar_rtf(texto)
        print("\nTexto limpo:")
        print("-"*60)
        print(resultado)
        print(f"\nTipo do resultado: {type(resultado)}")
        return resultado
    except Exception as e:
        print(f"\nErro ao processar o texto: {e}")
        print(f"Tipo de erro: {type(e).__name__}")
        import traceback
        traceback.print_exc()
        return None

# Teste 1: Texto RTF com caracteres especiais
texto_rtf = r"""
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
limpar_e_mostrar(texto_rtf, "RTF Completo")

# Teste 2: Texto já processado
texto_processado = """
Interação recente: green0;splytwninesectdplainlangfe1046fs20
Libera'e7'e3o foi feita e est'e1 funcionando corretamente
"""
limpar_e_mostrar(texto_processado, "Texto já processado")

# Teste 3: Texto simples
texto_simples = "Liberação foi feita e está funcionando corretamente"
limpar_e_mostrar(texto_simples, "Texto Simples")

# Teste 4: Texto vazio
limpar_e_mostrar("", "Texto Vazio")

# Teste 5: Nenhum texto
limpar_e_mostrar(None, "Nenhum Texto")

print("\n" + "="*60)
print("Testes concluídos!")
