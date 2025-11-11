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
        cur.execute("SELECT IdRdm, NumAtendimento, Descricao, RegInclusao FROM CnsRDM WITH (NOLOCK) WHERE NumAtendimento = ? ORDER BY RegInclusao DESC", (num_atendimento,))
        cols = [c[0] for c in cur.description]
        rows = cur.fetchall()
        return [dict(zip(cols, row)) for row in rows]
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
                                        with dlg:
                                            ui.label(f"RDMs vinculadas ao atendimento {n}").classes("text-lg font-bold")
                                            if not rdms:
                                                ui.label("Nenhuma RDM encontrada").classes("text-sm text-gray-500")
                                            else:
                                                for r in rdms:
                                                    with ui.card().classes("mb-2 p-2"):
                                                        ui.label(f"ID: {r.get('IdRdm')} — {r.get('Descricao')}").classes("text-sm")
                                                        ui.label(f"Data: {r.get('RegInclusao')}").classes("text-xs text-gray-500")
                                            ui.button("Fechar", on_click=lambda _: dlg.close())
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
