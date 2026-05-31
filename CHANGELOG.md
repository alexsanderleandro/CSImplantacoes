# Changelog — Painel de Implantações CEOSoftware

> Versão atual: **26.5.29 rev 1**  
> Última atualização do documento: **29/05/2026**

---

## [26.5.29] — 29/05/2026

### 🏗️ Estrutura & Correções de Bug

- **Correção de aninhamento crítico**: função `_open_implantacoes_dialog` estava incorretamente aninhada dentro de `_do_refresh`; extraída para o nível correto dentro de `show_kanban`.
- **Remoção de botão órfão**: botão duplicado/solto removido do layout principal.
- **Reordenação de colunas**: coluna *"Aguardando RDM"* movida para depois de *"Implantação em andamento"* na lista `COLUMNS`.
- **Correção de código de classificação**: código de *"Aguardando RDM"* corrigido de `50` → `51` para o kanban ativo (`Situacao = 0`).
- **Remoção do botão 🗑️ Cache**: botão e função `_do_clean_cache()` removidos da interface.

---

### 🎨 Redesign — Dashboard Híbrido

- **Kanban substituído por Dashboard híbrido**: layout completamente redesenhado com:
  - **Cards KPI** no topo (Total ativo, Em atraso >120d, Contato hoje + contadores por status)
  - **Lista agrupada por status** (`ui.expansion`) com linhas compactas
- **Paleta Pastel2 (matplotlib)** aplicada nos cabeçalhos de grupo e nos cards KPI de status:
  - `#b3e2cd`, `#fdcdac`, `#cbd5e8`, `#f4cae4`, `#e6f5c9`, `#fff2ae`, `#f1e2cc`, `#cccccc`
- **Grupos sempre exibidos**: mesmo com 0 registros, todos os 8 status são mostrados
- **Todos os grupos carregam recolhidos** por padrão (`ui.expansion` sem `value=True`)
- **Linhas compactas**: dot · #num · Cliente · 👤 Responsável · ⏱ dias · 📅 próx. contato · chips de alerta
- **Botões por linha**: `Histórico` `RDMs` `Atendimentos` `Imagem`

---

### 🗃️ SQL — Correções e Melhorias

- **Removida condição `AssuntoAtendimento`** de ambos os SQLs (kanban ativo e finalizadas)
- **SQL kanban ativo**: usa `CodClassificacaoAtendimento IN (7, 46, 29, 47, 51, 48, 49, 8)` + `Situacao = 0`
- **SQL finalizadas**: corrigido para usar `CodClassificacaoAtendimento = 50` + `Situacao = 1`
  - Diagnóstico revelou: código `50` = 522 registros finalizados; código `51` = 0 registros finalizados
- **`INNER JOIN GrupoEmpresa`** adicionado em ambos os SQLs:
  ```sql
  INNER JOIN GrupoEmpresa G WITH (NOLOCK)
      ON C.CodGrupoEmpresa = G.CodGrupoEmpresa
  ```
- **`G.NomeGrupoEmpresa`** incluído no `SELECT` e no `GROUP BY` (finalizadas)

---

### 🔍 Filtros do Dashboard

- **Filtro por Cliente**: busca parcial por `NomeCliente` (case-insensitive)
- **Filtro por Grupo Empresa** *(novo)*: busca parcial por `NomeGrupoEmpresa`
- **Filtro por Responsável**: busca parcial por `NomeUsuario`
- **Enter** nos campos aciona o filtro automaticamente
- **Botão "Limpar"**: reseta todos os filtros (texto + toggles)
- **Label de contagem**: exibe total filtrado e critérios ativos

#### Filtros Toggle (KPI clicável)

- **🔴 Em atraso >120d** *(novo)*:
  - Clique no card ativa/desativa filtro de registros com abertura > 120 dias
  - Exclui automaticamente registros com contato agendado para hoje
  - Visual: vermelho intenso + `✕` quando ativo
- **📅 Contato hoje** *(novo)*:
  - Clique no card ativa/desativa filtro de registros com `DataProxContato = hoje`
  - Visual: âmbar + `✕` quando ativo
- Ambos os filtros são combináveis entre si e com os filtros de texto

#### Correção de Contagem

- Registros com `DataProxContato = hoje` **não são mais contados nem filtrados como "em atraso"**, mesmo que tenham abertura > 120 dias

---

### 🏁 Implantações Concluídas (Diálogo)

- **Filtro por Grupo Empresa** *(novo)*: campo `🏢 Grupo Empresa` adicionado à barra de filtros do diálogo
- Filtro por parte do `NomeGrupoEmpresa`, combinável com cliente, ano e ordenação
- `Enter` no campo aciona o `_fin_render()` automaticamente

---

### 🔐 Tela de Login — Redesign Profissional

- **Fundo**: gradiente escuro `#0f172a → #1e3a5f → #0f172a` cobrindo 100% da viewport
- **Card centralizado**: bordas arredondadas (18px), sombra profunda, fundo branco
- **Logo**: imagem `assets/logo.png` servida via `app.add_static_files('/assets', ...)` — substituiu emoji
- **Campos**: estilo `outlined dense` com toggle de senha visível e placeholder suave
- **Botão Entrar**: 100% de largura, gradiente azul, sombra colorida, hover com fade
- **Mensagem de erro**: caixa vermelha com ícone ⚠️, visível apenas em falha de autenticação
- **Enter** em qualquer campo aciona o login
- **Versão**: exibida com separador no rodapé do card (margem ajustada para não colar no botão)

---

### ⚙️ Infraestrutura

- **`from nicegui import ui, app`**: `app` adicionado ao import para permitir `add_static_files`
- **`app.add_static_files('/assets', ...)`**: pasta `assets/` registrada antes do `ui.run()`, tornando `assets/logo.png` acessível em `/assets/logo.png`
- **`Path`** já disponível via `from pathlib import Path` (pré-existente)

---

## Estrutura de Colunas (COLUMNS)

| # | Nome | Cor (Pastel2) | Código |
|---|------|--------------|--------|
| 1 | A iniciar | `#b3e2cd` | 100 |
| 2 | Visita pré-implantação | `#fdcdac` | 101 |
| 3 | Instalação do sistema | `#cbd5e8` | 102 |
| 4 | Implantação em andamento | `#f4cae4` | 103 |
| 5 | Aguardando RDM | `#e6f5c9` | 51 |
| 6 | Implantação pausada | `#fff2ae` | 104 |
| 7 | Implantação cancelada | `#f1e2cc` | 105 |
| 8 | Visita pós-implantação | `#cccccc` | 106 |

---

## Regras de Negócio

| Condição | SQL | Critério |
|----------|-----|---------|
| Kanban ativo | `SQL_ATENDIMENTOS_IMPLANTACAO` | `CodClassificacaoAtendimento IN (7,46,29,47,51,48,49,8)` + `Situacao = 0` |
| Finalizadas | `SQL_ATENDIMENTOS_IMPLANTACAO_FINALIZADA` | `CodClassificacaoAtendimento = 50` + `Situacao = 1` |
| Em atraso | Filtro frontend | Abertura > 120 dias **e** sem contato agendado para hoje |
| Contato hoje | Filtro frontend | `DataProxContato = data de hoje` |
