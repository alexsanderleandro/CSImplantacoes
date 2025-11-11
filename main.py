# main.py
from nicegui import ui, app
from authentication import verify_user, get_db_connection
from rtf_utils import limpar_rtf
import os
from version import APP_NAME, APP_VERSION
import pyodbc
from datetime import datetime


def sanitize_text(value: object) -> str:
    """Return a UTF-8-safe string for UI output.

    - If value is bytes, decode as utf-8 with replacement for errors.
    - If value is str, remove any surrogate codepoints (U+D800..U+DFFF).
    - Otherwise, convert to str and sanitize.
    """
    if value is None:
        return ""
    # decode bytes
    if isinstance(value, (bytes, bytearray)):
        try:
            s = value.decode('utf-8')
        except Exception:
            s = value.decode('utf-8', errors='replace')
    else:
        s = str(value)

    # remove surrogate codepoints which orjson rejects
    cleaned = ''.join(ch for ch in s if not (0xD800 <= ord(ch) <= 0xDFFF))
    return cleaned


def normalize_description(s: str) -> str:
    """Limpa ruídos típicos deixados pela conversão de RTF:

    - remove bookmarks/labels repetidos como DESCRICAO, DESCRICAO_TAREFA
    - colapsa sequências de pontuação/espacos (ex: ".; ; .; ;")
    - remove palavras adjacentes duplicadas (ex: "DESCRICAO DESCRICAO" -> "DESCRICAO")
    """
    import re
    if not s:
        return ""
    # remover tokens de bookmark/marcadores comuns
    s = re.sub(r"\b(?:DESCRICAO_TAREFA|DESCRICAOTAREFA|DESCRICAO|_dx_frag_StartFragment|_dx_frag_EndFragment)\b", "", s, flags=re.IGNORECASE)
    # colapsar sequências de pontuação e espaços (ex: ".; ; .; ;") em um único espaço
    s = re.sub(r"[\.\;,:\-_/\\\s]{2,}", " ", s)
    # remover repetições adjacentes de uma mesma palavra
    s = re.sub(r"\b(\w+)(?:\s+\1\b)+", r"\1", s, flags=re.IGNORECASE)
    # colapsar espaços múltiplos e trim
    s = re.sub(r"\s+", " ", s).strip()
    return s

# ---------- Configurações Kanban ----------
COLUMNS = [
    ("A iniciar", "#d1d5db", 100),
    ("Visita pré-implantação", "#a3a3a3", 101),
    ("Instalação do sistema", "#c8b6ff", 102),
    ("Implantação em andamento", "#a7f3d0", 103),
    ("Implantação pausada", "#fef08a", 104),
    ("Implantação cancelada", "#f87171", 105),
    ("Visita pós-implantação", "#f5f0d9", 106),
    ("Implantação concluída", "#93c5fd", 107),
]
COLUMN_MAP = {name: {"color": color, "situacao": situ} for (name, color, situ) in COLUMNS}

# ---------- SQL ----------
SQL_ATENDIMENTOS_IMPLANTACAO = """
SELECT
    A.NumAtendimento,
    A.AssuntoAtendimento,
    A.RegInclusao AS Abertura,
    A.CodCliente,
    C.NomeCliente,
    A.Situacao,
    (
        SELECT MAX(I2.RegInclusao)
        FROM AtendimentoIteracao I2 WITH (NOLOCK)
        WHERE I2.NumAtendimento = A.NumAtendimento
    ) AS UltimaIteracao,
    (
        SELECT TOP 1 CONVERT(NVARCHAR(MAX), I3.TextoIteracao)
        FROM AtendimentoIteracao I3 WITH (NOLOCK)
        WHERE I3.NumAtendimento = A.NumAtendimento
        ORDER BY I3.NumIteracao DESC
    ) AS TextoIteracao
FROM CNSAtendimento A WITH (NOLOCK)
INNER JOIN CnsClientes C WITH (NOLOCK)
    ON A.CodCliente = C.CodCliente
    AND A.CodEmpresa = C.CodEmpresa
WHERE
    A.AssuntoAtendimento = N'Implantação'
    AND A.Situacao = 0
ORDER BY C.NomeCliente;
"""

SQL_ATENDIMENTO_ITERACAO = """
SELECT AI.NumAtendimento, AI.Desdobramento, AI.NumIteracao, AI.DataIteracao, 
       AI.HoraIteracao, AI.TextoIteracao, U.NomeUsuario, AI.NomeContato
FROM AtendimentoIteracao AI WITH (NOLOCK)
INNER JOIN Usuarios U WITH (NOLOCK) ON (AI.CodUsuario = U.CodUsuario)
WHERE AI.NumAtendimento = ?
ORDER BY AI.NumIteracao DESC;
"""

# ---------- Funções de DB ----------
def fetch_kanban_cards():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(SQL_ATENDIMENTOS_IMPLANTACAO)
    cols = [c[0] for c in cur.description]
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(zip(cols, row)) for row in rows]

def fetch_history(num_atendimento):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(SQL_ATENDIMENTO_ITERACAO, (num_atendimento,))
    cols = [c[0] for c in cur.description]
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(zip(cols, row)) for row in rows]


def fetch_latest_iteration(num_atendimento):
    """Retorna a última iteração (uma linha) com NomeUsuario e Data/Hora/Texto, ou None."""
    conn = get_db_connection()
    cur = conn.cursor()
    sql = """
    SELECT TOP 1 AI.NumIteracao, AI.DataIteracao, AI.HoraIteracao, AI.TextoIteracao, U.NomeUsuario
    FROM AtendimentoIteracao AI WITH (NOLOCK)
    LEFT JOIN Usuarios U WITH (NOLOCK) ON AI.CodUsuario = U.CodUsuario
    WHERE AI.NumAtendimento = ?
    ORDER BY AI.NumIteracao DESC
    """
    cur.execute(sql, (num_atendimento,))
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        return None
    cols = [c[0] for c in cur.description]
    cur.close()
    conn.close()
    return dict(zip(cols, row))


def fetch_rdms(num_atendimento):
    """Busca RDMs vinculadas ao atendimento (se existir tabela CnsRDM)."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Ajuste: nomes das colunas reais na tabela CnsRDM são diferentes
        # Selecionamos colunas existentes e as aliasamos para manter a API usada pela UI
        cur.execute(
            "SELECT NumRDM AS IdRdm, NumAtendimento, Desdobramento, NomeTipoRDM, DescricaoRDM AS Descricao, RegInclusao, "
            "CASE "
            "WHEN Situacao = 0 THEN 'Priorizar' "
            "WHEN Situacao = 1 THEN 'Executando' "
            "WHEN Situacao = 2 THEN 'Aguardando' "
            "WHEN Situacao = 3 THEN 'Concluída' "
            "WHEN Situacao = 4 THEN 'Cancelada' "
            "WHEN Situacao = 5 THEN 'Verificar' "
            "WHEN Situacao = 6 THEN 'Validar' "
            "WHEN Situacao = 7 THEN 'Enfileirada' "
            "WHEN Situacao = 8 THEN 'Testando' "
            "WHEN Situacao = 9 THEN 'Verificar' "
            "WHEN Situacao = 10 THEN 'Contatar cliente' "
            "WHEN Situacao = 11 THEN 'Aguardando correção' "
            "WHEN Situacao = 12 THEN 'Verificar' "
            "WHEN Situacao = 13 THEN 'Verificar' "
            "WHEN Situacao = 14 THEN 'Verificar' "
            "WHEN Situacao = 15 THEN 'Verificar' "
            "WHEN Situacao = 16 THEN 'Verificar' "
            "WHEN Situacao = 17 THEN 'Efetuar merge' "
            "WHEN Situacao = 18 THEN 'Liberação pendente' "
            "WHEN Situacao = 19 THEN 'Verificar' "
            "WHEN Situacao = 20 THEN 'Revisando testes' "
            "WHEN Situacao = 21 THEN 'Verificar' "
            "WHEN Situacao = 22 THEN 'Verificar' "
            "WHEN Situacao = 23 THEN 'Aguardando (setor de testes)' "
            "WHEN Situacao = 24 THEN 'Em edição' "
            "WHEN Situacao = 25 THEN 'Validação técnica' "
            "END AS SituacaoRDM "
            "FROM CnsRDM WITH (NOLOCK) WHERE NumAtendimento = ? ORDER BY RegInclusao DESC",
            (num_atendimento,)
        )
        cols = [c[0] for c in cur.description]
        rows = cur.fetchall()
        result = [dict(zip(cols, row)) for row in rows]
        # Limpa textos RTF das RDMs (semelhante ao tratamento das interações)
        for r in result:
            try:
                # Limpa e sanitiza descrição (pode vir em RTF)
                raw = r.get('Descricao') or ''
                r['Descricao'] = sanitize_text(limpar_rtf(raw))
                # remover ruídos e marcações repetidas deixadas pela conversão RTF
                r['Descricao'] = normalize_description(r['Descricao'])
            except Exception:
                r['Descricao'] = sanitize_text(r.get('Descricao') or '')
            # sanitizar Desdobramento (normalmente texto simples)
            try:
                r['Desdobramento'] = sanitize_text(r.get('Desdobramento') or '')
            except Exception:
                r['Desdobramento'] = ''
            # sanitizar situação legível da RDM
            try:
                r['SituacaoRDM'] = sanitize_text(r.get('SituacaoRDM') or '')
            except Exception:
                r['SituacaoRDM'] = ''
            # sanitizar NomeTipoRDM
            try:
                r['NomeTipoRDM'] = sanitize_text(r.get('NomeTipoRDM') or '')
            except Exception:
                r['NomeTipoRDM'] = ''
        return result
    except Exception:
        return []
    finally:
        try:
            cur.close()
            conn.close()
        except:
            pass

def update_situacao_on_move(num_atendimento, new_situacao_code):
    sql = "UPDATE CNSAtendimento SET Situacao = ? WHERE NumAtendimento = ?"
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(sql, (new_situacao_code, num_atendimento))
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print("Erro atualizando situacao:", e)
        return False

# ---------- UI ----------
logged_user = {"CodUsuario": None, "NomeUsuario": None}

# contêiner raiz para trocar views
root = ui.element('div').classes("w-full p-4")

# footer de página (top-level) com informação da versão
footer = ui.footer()
footer.add_slot('info', f"<span>{APP_NAME} — v{APP_VERSION}</span>")

def show_login():
    root.clear()
    with root:
        ui.markdown(f"## {APP_NAME} — Login")
        username = ui.input("Usuário").classes("w-96").props("autofocus")
        password = ui.input("Senha", password=True).classes("w-96")
        message = ui.label("")

        def do_login():
            user = verify_user(username.value, password.value)
            if user:
                logged_user.update(user)
                ui.notify(f"Bem-vindo, {user['NomeUsuario']}!")
                show_kanban()
            else:
                message.set_text("Usuário ou senha inválidos")

        ui.button("Entrar", on_click=lambda _: do_login())
    # footer já criado no nível do módulo

def show_kanban():
    root.clear()
    with root:
        ui.label(f"🗂️ {sanitize_text(APP_NAME)} — {sanitize_text(logged_user.get('NomeUsuario', ''))}").classes("text-2xl mb-2 font-bold")
        ui.button("Logout", on_click=lambda _: show_login()).classes("secondary")

        board = ui.row().classes("w-full gap-4 items-start").style("overflow-x: auto;")
        cards_data = fetch_kanban_cards()
        # debug console log to help verify how many rows were fetched for the Kanban
        print(f"[DEBUG] show_kanban: {len(cards_data)} cards loaded")
        # debug: mostrar contagem de cards
        ui.label(f"{len(cards_data)} cards carregados").classes("text-sm text-gray-500 mb-2")

        # Colocar todos os cards inicialmente na coluna "A iniciar"
        column_cards = {name: [] for (name, _, _) in COLUMNS}
        start_col = COLUMNS[0][0]  # nome da primeira coluna ("A iniciar")
        for row in cards_data:
            column_cards[start_col].append(row)

        def render_board():
            board.clear()
            with board:
                for col_name, bg_color, situ_code in COLUMNS:
                    with ui.column().classes("w-72").style("min-width: 18rem;"):
                        ui.label(col_name).classes("text-md font-semibold p-2 rounded").style(f"background:{bg_color};")
                        # Render cards with a select + button mover (compatível com versões sem drop_zone)
                        def format_datetime(value):
                            if value is None:
                                return "-"
                            if isinstance(value, datetime):
                                return value.strftime("%d/%m/%Y %H:%M")
                            try:
                                if isinstance(value, bytes):
                                    s = value.decode(errors='ignore')
                                else:
                                    s = str(value)
                                for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y %H:%M:%S"):
                                    try:
                                        dt = datetime.strptime(s, fmt)
                                        return dt.strftime("%d/%m/%Y %H:%M")
                                    except Exception:
                                        continue
                                return s
                            except Exception:
                                return str(value)

                        for card in column_cards.get(col_name, []):
                            num = card.get("NumAtendimento")
                            cliente = sanitize_text(card.get("NomeCliente") or "-")
                            assunto = sanitize_text(card.get("AssuntoAtendimento") or "-")
                            ultima = format_datetime(card.get("UltimaIteracao"))
                            texto_raw = card.get("TextoIteracao") or ""
                            texto = limpar_rtf(texto_raw)
                            snippet = (texto[:250] + "...") if len(texto) > 250 else texto
                            snippet = sanitize_text(snippet)
                            titulo_bg = COLUMN_MAP.get(col_name, {}).get("color", "#ffffff")

                            # cartão com borda colorida e layout melhorado
                            with ui.card().classes("mb-3 shadow-sm").style(f"border-left:4px solid {titulo_bg};"):
                                with ui.row().classes("items-center justify-between"):
                                    ui.column().classes("mr-2")
                                    # header: cliente + id
                                    with ui.row().classes("items-center justify-between w-full"):
                                        ui.label(cliente).classes("font-semibold text-lg")
                                        ui.label(f"#{num}").classes("text-sm text-gray-600 ml-2")
                                # assunto
                                ui.label(assunto).classes("text-sm mt-1 mb-1")
                                # última interação
                                ui.label(f"Última interação: {ultima}").classes("text-xs text-gray-500 mb-2")
                                # trecho do texto da última iteração
                                if snippet:
                                    ui.label(snippet).classes("text-sm text-gray-700 mb-2")

                                with ui.row().classes("items-center gap-2"):
                                    # mostra analista (última iteração) e botões para histórico e RDMs
                                    latest = fetch_latest_iteration(num)
                                    analyst = sanitize_text((latest.get('NomeUsuario') if latest else None) or '-')
                                    ui.label(f"Analista: {analyst}").classes("text-sm text-gray-600")

                                    ui.button("Histórico", on_click=lambda _, n=num: show_history_dialog(n)).classes("primary")

                                    def show_rdms(_, n=num):
                                        rdms = fetch_rdms(n)
                                        dlg = ui.dialog()
                                        # aumentar largura do diálogo para melhor visibilidade
                                        dlg.classes("w-full max-w-6xl")
                                        with dlg:
                                            # título removido — diálogo exibirá apenas a lista e os totalizadores
                                            if not rdms:
                                                ui.label("Nenhuma RDM encontrada").classes("text-sm text-gray-500")
                                            else:
                                                # ordenar pelas datas de abertura (RegInclusao) - mais antigas primeiro
                                                try:
                                                    rdms_sorted = sorted(rdms, key=lambda x: x.get('RegInclusao') or datetime.max, reverse=False)
                                                except Exception:
                                                    rdms_sorted = rdms

                                                # calcular totalizadores por tipo e por situação
                                                totals_by_tipo = {}
                                                totals_by_situacao = {}
                                                for r in rdms_sorted:
                                                    tipo = (r.get('NomeTipoRDM') or '').strip() or 'N/A'
                                                    sit = (r.get('SituacaoRDM') or '').strip() or 'N/A'
                                                    totals_by_tipo[tipo] = totals_by_tipo.get(tipo, 0) + 1
                                                    totals_by_situacao[sit] = totals_by_situacao.get(sit, 0) + 1

                                                # lista detalhada de RDMs em uma única coluna/form para melhor legibilidade
                                                # envolver a lista em uma linha centralizada para garantir alinhamento correto
                                                with ui.row().classes("w-full justify-center"):
                                                    with ui.column().classes("w-full max-w-4xl").style("overflow:auto; max-height:60vh;padding-right:8px;"):
                                                        for r in rdms_sorted:
                                                            with ui.card().classes("mb-2 p-3 w-full"):
                                                                numrdm = sanitize_text(r.get('IdRdm') or '')
                                                                desdob = sanitize_text(r.get('Desdobramento') or '')
                                                                tipordm = sanitize_text(r.get('NomeTipoRDM') or '')
                                                                situ = sanitize_text(r.get('SituacaoRDM') or '')
                                                                reg = r.get('RegInclusao')
                                                                data_str = format_datetime(reg)
                                                                desc = sanitize_text(r.get('Descricao') or '')

                                                                md = (
                                                                    f"**Nº:** {numrdm} / {desdob}\n\n"
                                                                    f"**Tipo de RDM:** {tipordm}\n\n"
                                                                    f"**Situação:** {situ}\n\n"
                                                                    f"**Abertura:** {data_str}\n\n"
                                                                    f"**Descrição:** {desc}"
                                                                )
                                                                ui.markdown(md)

                                                # exibir totalizadores ao final: por tipo e por situação (bloco com fundo branco)
                                                # totalizadores centralizados com largura limitada para manter alinhamento em telas grandes
                                                with ui.row().classes("w-full mt-4 justify-center"):
                                                    with ui.card().classes("mx-auto w-full max-w-3xl").style("background:#ffffff;padding:12px;border-radius:6px;box-shadow:0 1px 3px rgba(0,0,0,0.08);"):
                                                        with ui.row().classes("w-full gap-8 items-start"):
                                                            with ui.column().classes("w-1/2"):
                                                                ui.markdown("**Total por Tipo de RDM:**\n\n")
                                                                for tipo, cnt in sorted(totals_by_tipo.items(), key=lambda i: (-i[1], i[0])):
                                                                    ui.markdown(f"- **{tipo}**: {cnt}")
                                                            with ui.column().classes("w-1/2"):
                                                                ui.markdown("**Total por Situação de RDM:**\n\n")
                                                                for sit, cnt in sorted(totals_by_situacao.items(), key=lambda i: (-i[1], i[0])):
                                                                    ui.markdown(f"- **{sit}**: {cnt}")
                                                # botão de fechar centralizado abaixo dos totais
                                                with ui.row().classes("w-full mt-4 justify-center"):
                                                    ui.button("Fechar", on_click=lambda _: dlg.close()).classes("primary")
                                        dlg.open()

                                    ui.button("RDMs", on_click=show_rdms).classes("secondary")

                                    # seletor para escolher coluna de destino e botão para mover
                                    options = [name for (name, _, _) in COLUMNS]
                                    sel = ui.select(options, value=col_name).classes("w-full")

                                    def do_move(_, c=card, select_widget=sel):
                                        dest = select_widget.value
                                        if dest == col_name:
                                            ui.notify("O card já está nessa coluna", color="warning")
                                            return
                                        # remover da coluna atual
                                        moved = None
                                        for it in column_cards.get(col_name, []):
                                            if str(it.get("NumAtendimento")) == str(c.get("NumAtendimento")):
                                                moved = it
                                                break
                                        if moved:
                                            column_cards[col_name].remove(moved)
                                            column_cards[dest].append(moved)
                                            new_code = COLUMN_MAP.get(dest, {}).get("situacao")
                                            if new_code is not None:
                                                ok = update_situacao_on_move(moved.get("NumAtendimento"), new_code)
                                                if ok:
                                                    ui.notify(f'✔ "{moved.get("NomeCliente")}" movido para "{dest}"')
                                                else:
                                                    ui.notify("Erro ao atualizar situação", color="negative")
                                            render_board()

                                    ui.button("Mover", on_click=do_move).classes("secondary")

    def show_history_dialog(num_atendimento):
        hist = fetch_history(num_atendimento)
        dlg = ui.dialog()
        with dlg:
            ui.label(f"Histórico do atendimento {num_atendimento}").classes("text-lg font-bold")
            for h in hist:
                with ui.card().classes("mb-2 p-2"):
                    ui.label(f"{sanitize_text(h.get('DataIteracao'))} {sanitize_text(h.get('HoraIteracao'))} — {sanitize_text(h.get('NomeUsuario'))}").classes("text-sm")
                    ui.markdown(sanitize_text(limpar_rtf(h.get("TextoIteracao") or "")))
            ui.button("Fechar", on_click=lambda _: dlg.close())
        dlg.open()

    render_board()

# ---------- Execução ----------
# Em modo normal, mostramos o login. Em modo de desenvolvimento (AUTO_KANBAN=1)
# pulamos o login para abrir direto o Kanban (útil para debug local).
if os.getenv('AUTO_KANBAN') == '1':
    # preenche um usuário de desenvolvimento mínimo
    logged_user.update({"CodUsuario": 0, "NomeUsuario": "dev"})
    show_kanban()
else:
    show_login()

if __name__ in {"__main__", "__mp_main__"}:
    ui.run(title=APP_NAME, reload=True, port=8888, host="0.0.0.0")
