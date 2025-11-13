Este diretório contém imagens temporárias extraídas de campos RTF (`TextoIteracao`).

- Finalidade: armazenar arquivos de imagem temporários para renderização rápida no UI.
- Política de committ: não faz parte do repositório (arquivos são ignorados via `.gitignore`).
- Limpeza: arquivos mais antigos que `CACHE_TTL_DAYS` serão removidos automaticamente pelo cleaner.

Caso precise inspecionar manualmente imagens, verifique este diretório localmente.
