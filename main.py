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
]
COLUMN_MAP = {name: {"color": color, "situacao": situ} for (name, color, situ) in COLUMNS}

# ---------- SQL ----------
SQL_ATENDIMENTOS_IMPLANTACAO = """
SELECT
    A.NumAtendimento,
    A.AssuntoAtendimento,
    A.RegInclusao AS Abertura,
    A.DataProxContato,
    A.CodCliente,
    C.NomeCliente,
    A.Situacao,
    (
        SELECT MAX(I2.RegInclusao)
        FROM AtendimentoIteracao I2 WITH (NOLOCK)
        WHERE I2.NumAtendimento = A.NumAtendimento
          AND I2.Desdobramento = 0
    ) AS UltimaIteracao,
    (
        SELECT TOP 1 CONVERT(NVARCHAR(MAX), I3.TextoIteracao)
        FROM AtendimentoIteracao I3 WITH (NOLOCK)
        WHERE I3.NumAtendimento = A.NumAtendimento
          AND I3.Desdobramento = 0
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
            AND AI.Desdobramento = 0
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
            # sanitizar Desdobramento (preservar 0 em vez de transformá-lo em string vazia)
            try:
                desdob_raw = r.get('Desdobramento')
                r['Desdobramento'] = sanitize_text(desdob_raw) if desdob_raw is not None else ''
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
        # centralizar o formulário de login
        # centralizar horizontal e verticalmente (ocupando a altura da viewport)
        with ui.row().classes("w-full h-screen items-center justify-center"):
            with ui.column().classes("items-center w-full max-w-sm gap-2"):
                # cartão com fundo e sombra ao redor do formulário para destaque
                with ui.card().classes("w-full p-6 rounded shadow-md").style("background:#ffffff;"):
                    ui.markdown(f"## {APP_NAME} — Login").classes("text-center")
                    # inputs responsivos para caberem dentro do cartão
                    username = ui.input("Usuário").classes("w-full").props("autofocus")
                    password = ui.input("Senha", password=True).classes("w-full")
                    message = ui.label("").classes("text-sm text-red-600")

                    def do_login():
                        user = verify_user(username.value, password.value)
                        if user:
                            logged_user.update(user)
                            ui.notify(f"Bem-vindo, {user['NomeUsuario']}!")
                            show_kanban()
                        else:
                            message.set_text("Usuário ou senha inválidos")

                    # centraliza o botão dentro do cartão
                    with ui.row().classes("w-full justify-center mt-2"):
                        ui.button("Entrar", on_click=lambda _: do_login()).classes("primary")
    # footer já criado no nível do módulo

def show_kanban():
    root.clear()
    with root:
        # cabeçalho: título + contador de cards (à esquerda) e botão Logout (canto direito)
        cards_data = fetch_kanban_cards()
        # debug console log to help verify how many rows were fetched for the Kanban
        print(f"[DEBUG] show_kanban: {len(cards_data)} cards loaded")
        with ui.row().classes("w-full items-start mb-2 justify-between"):
            with ui.column().classes("items-start"):
                ui.label(f"🗂️ {sanitize_text(APP_NAME)} — {sanitize_text(logged_user.get('NomeUsuario', ''))}").classes("text-2xl font-bold")
                ui.label(f"{len(cards_data)} cards carregados").classes("text-sm text-gray-500")
            # botão de logout posicionado à direita do cabeçalho
            ui.button("Logout", on_click=lambda _: show_login()).classes("secondary")

        # board responsivo: permite overflow-x em telas pequenas e distribui colunas em telas maiores
        board = ui.row().classes("w-full gap-4 items-start").style("overflow-x: auto;")

        # Colocar todos os cards inicialmente na coluna "A iniciar"
        column_cards = {name: [] for (name, _, _) in COLUMNS}
        start_col = COLUMNS[0][0]  # nome da primeira coluna ("A iniciar")
        for row in cards_data:
            column_cards[start_col].append(row)

        def render_board():
            board.clear()
            with board:
                for col_name, bg_color, situ_code in COLUMNS:
                    # aumentar largura das colunas para aproveitar espaço disponível
                    # usar w-80 (20rem) e min-width maior para melhorar legibilidade em telas grandes
                    # colunas com flex-grow para preenchimento proporcional do espaço disponível
                    # usar basis-0 + flex-1 para que as colunas dividam igualmente o espaço
                    # manter min-width menor para evitar colunas muito estreitas
                    with ui.column().classes("basis-0 flex-1").style("min-width: 12rem;"):
                        ui.label(col_name).classes("text-md font-semibold p-2 rounded w-full text-center").style(f"background:{bg_color};")
                        # Render cards with a select + button mover (compatível com versões sem drop_zone)
                        def format_datetime(value):
                            """Normaliza diferentes formatos de entrada e retorna YYYY-MM-DD HH:MM:SS.

                            Aceita datetime, bytes ou strings em formatos comuns e tenta extrair
                            uma representação consistente com segundos.
                            """
                            if value is None:
                                return "-"
                            # datetime já formatado
                            if isinstance(value, datetime):
                                return value.strftime("%Y-%m-%d %H:%M:%S")
                            try:
                                if isinstance(value, bytes):
                                    s = value.decode(errors='ignore')
                                else:
                                    s = str(value)
                                # tentar vários formatos conhecidos
                                for fmt in (
                                    "%Y-%m-%d %H:%M:%S.%f",
                                    "%Y-%m-%d %H:%M:%S",
                                    "%Y-%m-%d %H:%M",
                                    "%Y-%m-%d",
                                    "%d/%m/%Y %H:%M:%S",
                                    "%d/%m/%Y %H:%M",
                                    "%d/%m/%Y",
                                ):
                                    try:
                                        dt = datetime.strptime(s, fmt)
                                        return dt.strftime("%Y-%m-%d %H:%M:%S")
                                    except Exception:
                                        continue
                                # se não foi possível parsear, retornar a string sanitizada
                                return sanitize_text(s)
                            except Exception:
                                return sanitize_text(str(value))

                        # ordenar cards da coluna por dias em aberto (decrescente)
                        try:
                            now_dt = datetime.now()
                            def _days_open_for_card(card_item):
                                try:
                                    av = card_item.get('Abertura')
                                    if av is None:
                                        return -1
                                    # reutilizar _parse_date se disponível, senão tentar parse simplificado
                                    try:
                                        if isinstance(av, datetime):
                                            dt = av
                                        else:
                                            s = av.decode(errors='ignore') if isinstance(av, (bytes, bytearray)) else str(av)
                                            for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y"):
                                                try:
                                                    dt = datetime.strptime(s, fmt)
                                                    break
                                                except Exception:
                                                    dt = None
                                    except Exception:
                                        dt = None
                                    if not dt:
                                        return -1
                                    return (now_dt - dt).days
                                except Exception:
                                    return -1

                            cards_to_render = sorted(column_cards.get(col_name, []) or [], key=_days_open_for_card, reverse=True)
                        except Exception:
                            cards_to_render = column_cards.get(col_name, []) or []

                        for card in cards_to_render:
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
                                        # calcular dias em aberto a partir de Abertura (RegInclusao)
                                        abertura_val = card.get("Abertura")
                                        def _parse_date(v):
                                            if v is None:
                                                return None
                                            if isinstance(v, datetime):
                                                return v
                                            try:
                                                if isinstance(v, bytes):
                                                    s = v.decode(errors='ignore')
                                                else:
                                                    s = str(v)
                                                for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y"):
                                                    try:
                                                        return datetime.strptime(s, fmt)
                                                    except Exception:
                                                        continue
                                            except Exception:
                                                return None
                                            return None

                                        dt_abertura = _parse_date(abertura_val)
                                        days_open = None
                                        try:
                                            if dt_abertura:
                                                days_open = (datetime.now() - dt_abertura).days
                                        except Exception:
                                            days_open = None

                                        # mostrar id e dias em aberto (dias em vermelho e negrito)
                                        with ui.row().classes("items-center"):
                                            ui.label(f"#{num}").classes("text-sm text-gray-600 ml-2")
                                            if days_open is not None:
                                                # cor azul quando <= 120 dias, vermelho quando > 120 dias
                                                try:
                                                    color_class = "text-blue-600" if int(days_open) <= 120 else "text-red-600"
                                                except Exception:
                                                    color_class = "text-red-600"
                                                lbl = ui.label(f"Aberto há {days_open} dias").classes(f"text-sm font-bold {color_class} ml-3")
                                                # tooltip com a data de abertura no formato dd/mm/aaaa
                                                try:
                                                    if dt_abertura:
                                                        ui.tooltip(lbl, f"Data de abertura: {dt_abertura.strftime('%d/%m/%Y')}")
                                                except Exception:
                                                    pass
                                # mostrar Próximo contato no lugar do assunto (ocupando a mesma linha)
                                prox_val = card.get("DataProxContato")
                                dt_prox = None
                                try:
                                    dt_prox = _parse_date(prox_val)
                                except Exception:
                                    dt_prox = None

                                if dt_prox:
                                    try:
                                        prox_date_str = dt_prox.strftime("%d/%m/%Y")
                                    except Exception:
                                        prox_date_str = sanitize_text(str(prox_val))
                                else:
                                    prox_date_str = "-"

                                # determinar cor: vermelho (passado), preto (hoje), azul (futuro)
                                prox_color = "text-gray-500"
                                try:
                                    if dt_prox:
                                        today = datetime.now().date()
                                        pd = dt_prox.date()
                                        if pd < today:
                                            prox_color = "text-red-600"
                                        elif pd == today:
                                            prox_color = "text-black"
                                        else:
                                            prox_color = "text-blue-600"
                                except Exception:
                                    prox_color = "text-gray-500"

                                ui.label(f"Próximo contato: {prox_date_str}").classes(f"text-sm {prox_color} mt-1 mb-1")
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
                                                                # mostrar 0 quando Desdobramento for 0 (evitar falsy '' quando o valor é 0)
                                                                desdob_raw = r.get('Desdobramento')
                                                                desdob = sanitize_text(desdob_raw) if desdob_raw is not None else ''
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
        # ordenar por DataIteracao asc e HoraIteracao asc quando possível
        def _make_dt(h):
            try:
                d = h.get('DataIteracao')
                t = h.get('HoraIteracao')
                # se já for datetime
                if isinstance(d, datetime):
                    date_part = d
                else:
                    # tentar converter string para date
                    try:
                        date_part = datetime.strptime(str(d), "%Y-%m-%d")
                    except Exception:
                        try:
                            date_part = datetime.strptime(str(d), "%Y-%m-%d %H:%M:%S")
                        except Exception:
                            date_part = datetime.min
                # hora pode ser string hh:mm:ss
                if t:
                    try:
                        if isinstance(t, str):
                            time_part = datetime.strptime(t, "%H:%M:%S").time()
                        else:
                            time_part = t
                    except Exception:
                        time_part = None
                else:
                    time_part = None
                if time_part:
                    return datetime.combine(date_part.date(), time_part)
                return date_part
            except Exception:
                return datetime.min

        try:
            hist_sorted = sorted(hist, key=_make_dt)
        except Exception:
            hist_sorted = hist

        dlg = ui.dialog()
        with dlg:
            # centralizar conteúdo do histórico em lista com largura limitada
            with ui.row().classes("w-full justify-center"):
                with ui.column().classes("w-full max-w-4xl"):
                    # título removido pelo usuário: não exibir label de cabeçalho
                    for h in hist_sorted:
                        usuario = sanitize_text(h.get('NomeUsuario') or '-')
                        texto = sanitize_text(limpar_rtf(h.get('TextoIteracao') or ""))

                        def _format_dt(d, t):
                            # tenta montar um datetime a partir de DataIteracao (data) e HoraIteracao (hora)
                            # lida com casos em que HoraIteracao vem como '1900-01-01 12:50:52' e DataIteracao como '2025-10-17 00:00:00'
                            try:
                                # parse da parte de data
                                date_part = None
                                if isinstance(d, datetime):
                                    date_part = d
                                else:
                                    s = str(d) if d is not None else ''
                                    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y"):
                                        try:
                                            date_part = datetime.strptime(s, fmt)
                                            break
                                        except Exception:
                                            continue
                                if date_part is None:
                                    date_part = datetime.min

                                # parse da parte de hora — aceitar tanto 'HH:MM:SS' quanto um datetime completo com data (ex.: 1900-01-01 12:50:52)
                                time_part = None
                                if isinstance(t, datetime):
                                    time_part = t.time()
                                elif t:
                                    ts = str(t)
                                    for fmt in ("%H:%M:%S", "%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
                                        try:
                                            parsed = datetime.strptime(ts, fmt)
                                            # se o formato incluiu data, extrair a hora
                                            time_part = parsed.time()
                                            break
                                        except Exception:
                                            continue

                                # construir datetime final: usar a data de date_part e a hora de time_part quando disponível
                                if time_part:
                                    combined = datetime.combine(date_part.date(), time_part)
                                else:
                                    combined = date_part

                                # retornar no formato pedido (YYYY-MM-DD HH:MM:SS)
                                return combined.strftime("%Y-%m-%d %H:%M:%S")
                            except Exception:
                                return f"{sanitize_text(d)} {sanitize_text(t)}"

                        data_str = _format_dt(h.get('DataIteracao'), h.get('HoraIteracao'))

                        # cartão por iteração com labels em negrito
                        with ui.card().classes("mb-2 p-3 w-full"):
                            ui.markdown(f"**Data/Hora:** {data_str}  \n\n **Usuário:** {usuario}")
                            # descrição em markdown (texto limpo)
                            ui.markdown(texto)
                    # botão fechar centralizado
                    with ui.row().classes("w-full justify-center mt-4"):
                        ui.button("Fechar", on_click=lambda _: dlg.close()).classes("primary")
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
