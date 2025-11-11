from rtf_utils import limpar_rtf

# Texto RTF de exemplo (simplificado para evitar escapes problemáticos no literal)
rtf_text = "{\\rtf1\\ansi {\\b Teste de RTF simplificado} }"

# Processa o texto RTF
texto_limpo = limpar_rtf(rtf_text)

# Exibe o resultado
print("Texto limpo:")
print("-" * 50)
print(texto_limpo)
print("-" * 50)

# Se quiser salvar em um arquivo
with open('texto_limpo.txt', 'w', encoding='utf-8') as f:
    f.write(texto_limpo)

print("\nO texto foi salvo em 'texto_limpo.txt'")

# Teste com a string que você forneceu
texto_errado = "Interação recente: green0;splytwninesectdplainlangfe1046fs20Libera'e7'e3o foi feita e est'e1 funcionando corretamente"
print("\nTeste com o texto já processado:")
print("-" * 50)
print(limpar_rtf(texto_errado))
