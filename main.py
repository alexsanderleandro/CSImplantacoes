# main.py
# Adiar import de nicegui para evitar efeitos colaterais durante import/module load
# (ex.: leitura do registro no Windows feita por algumas libs). As variáveis serão
# inicializadas em start_app().
# pyodbc is used by authentication.get_db_connection; import removed here to
# avoid an unused import at module top-level.
import base64
import hashlib
import os
import threading
import time
from datetime import datetime
from pathlib import Path

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import Response

from authentication import get_db_connection, verify_user
from rtf_utils import extract_first_image_from_rtf, limpar_rtf
from nicegui import ui
from version import APP_NAME, APP_VERSION

# estilo reutilizável para imagens exibidas em diálogos (mantém linhas curtas)
IMG_STYLE = "max-width:100%;max-height:60vh;object-fit:contain;display:block;"
ui.page_title(APP_NAME)
ui = None
app = None


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
            s = value.decode("utf-8")
        except Exception:
            s = value.decode("utf-8", errors="replace")
    else:
        s = str(value)

    # remove surrogate codepoints which orjson rejects
    cleaned = "".join(ch for ch in s if not (0xD800 <= ord(ch) <= 0xDFFF))
    return cleaned


# diretório de cache de imagens (já usado para flags .hasimg)
IMAGE_CACHE_DIR = Path(os.getenv("IMAGE_CACHE_DIR", "cache_images"))
TEMP_IMAGE_SUBDIR = "tmp"
IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# debug logging disabled: _append_image_debug is a no-op to avoid writing files
def _append_image_debug(msg: str):
    """No-op placeholder kept for compatibility with previous debug calls."""
    return None


def temp_image_exists_on_disk(key: str) -> bool:
    """Return True if a temp image file for `key` exists on disk.

    This is used instead of a process-local memory cache so the presence
    check works correctly when running multiple workers.
    """
    try:
        tmp_dir = IMAGE_CACHE_DIR / TEMP_IMAGE_SUBDIR
        if not tmp_dir.exists():
            return False
        for p in tmp_dir.glob(f"{key}.*"):
            try:
                if p.is_file():
                    return True
            except Exception:
                continue
        return False
    except Exception:
        return False


def temp_image_endpoint(request: Request, key: str):
    """Starlette endpoint to serve temp images by key.

    Note: annotate `request` as `Request` so FastAPI/Starlette injects it and doesn't treat
    it as a query parameter.
    """
    try:
        # Primary: always serve from disk when present. This avoids relying on
        # process-local in-memory cache which is not shared across multiple
        # workers. If the disk file is not found, fall back to memory as a
        # last-resort (backwards-compatible).
        try:
            tmp_dir = IMAGE_CACHE_DIR / TEMP_IMAGE_SUBDIR
            if tmp_dir.exists():
                for p in tmp_dir.glob(f"{key}.*"):
                    try:
                        with open(p, "rb") as f:
                            data = f.read()
                        ext = p.suffix.lower()
                        mime_guess = "application/octet-stream"
                        if ext == ".png":
                            mime_guess = "image/png"
                        elif ext in (".jpg", ".jpeg"):
                            mime_guess = "image/jpeg"
                        elif ext == ".gif":
                            mime_guess = "image/gif"
                        elif ext == ".webp":
                            mime_guess = "image/webp"
                        # debug logging removed
                        return Response(content=data, media_type=mime_guess)
                    except Exception:
                        continue
        except Exception:
            # disk lookup error: debug logging removed
            pass

        # If not found on disk, return 404. We intentionally removed the
        # process-local in-memory fallback because the app no longer relies on
        # per-process memory cache for temp images.
        # no entry on disk for key — debug logging removed
        raise HTTPException(status_code=404)
    except HTTPException:
        raise
    except Exception:
        # temp_image_endpoint error: debug logging removed
        raise HTTPException(status_code=500)


def _temp_image_path_for_key(key: str, ext: str) -> Path:
    tmp = IMAGE_CACHE_DIR / TEMP_IMAGE_SUBDIR
    tmp.mkdir(parents=True, exist_ok=True)
    return tmp / f"{key}{ext}"


def _ext_for_mime(mime: str) -> str:
    if not mime:
        return ".bin"
    m = mime.lower()
    if "png" in m:
        return ".png"
    if "jpeg" in m or "jpg" in m:
        return ".jpg"
    if "gif" in m:
        return ".gif"
    if "webp" in m:
        return ".webp"
    return ".bin"


def save_temp_image_and_get_url(key: str, img_bytes: bytes, mime: str) -> str:
    """Persistir bytes em disco e retornar a URL pública /_temp_img/<key>.

    Não grava mais em cache em memória por processo — isso evita inconsistências
    quando a aplicação roda com múltiplos workers. A entrada em disco é usada
    como fonte de verdade. O arquivo em disco será criado em
    `cache_images/tmp/<key>.<ext>` e o caminho retornado é a URL relativa.
    """
    if not img_bytes or not mime or not key:
        return None
    try:
        # persist to disk so the image is available to all workers
        try:
            # Attempt to normalize/flatten images that contain alpha channel to
            # avoid transparent PNGs rendering invisible in the UI. This is
            # best-effort: if Pillow is not installed or processing fails, we
            # fall back to writing the original bytes.
            processed_bytes = img_bytes
            try:
                from io import BytesIO

                # Pillow: enable tolerant loading for truncated images so the
                # app can still attempt to render/flatten partially-corrupt
                # PNGs instead of raising OSError. This may produce visual
                # artifacts but avoids hard failures.
                from PIL import Image, ImageFile

                ImageFile.LOAD_TRUNCATED_IMAGES = True

                buf = BytesIO(img_bytes)
                img = Image.open(buf)
                img.load()
                has_alpha = img.mode in ("LA", "RGBA") or ("transparency" in img.info)
                if has_alpha:
                    # composite over white background
                    bg = Image.new("RGB", img.size, (255, 255, 255))
                    try:
                        if img.mode in ("LA", "RGBA"):
                            bg.paste(img, mask=img.split()[-1])
                        else:
                            # other cases where transparency is indicated in info
                            bg.paste(img)
                    except Exception:
                        # fallback: paste without mask
                        bg.paste(img)
                    out_buf = BytesIO()
                    bg.save(out_buf, format="PNG")
                    processed_bytes = out_buf.getvalue()
            except Exception:
                # PIL not available or processing failed -> use original bytes
                processed_bytes = img_bytes

            ext = _ext_for_mime(mime)
            p = _temp_image_path_for_key(key, ext)
            with open(p, "wb") as f:
                f.write(processed_bytes)
            # update mtime to now
            try:
                os.utime(p, None)
            except Exception:
                pass
            # saved temp image to disk — debug logging removed
        except Exception:
            # failed to persist temp image to disk — debug logging removed
            return None
        return f"/_temp_img/{key}"
    except Exception:
        # unexpected error saving temp image — debug logging removed
        return None


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
    s = re.sub(
        r"\b(?:DESCRICAO_TAREFA|DESCRICAOTAREFA|DESCRICAO|_dx_frag_StartFragment|_dx_frag_EndFragment)\b",
        "",
        s,
        flags=re.IGNORECASE,
    )
    # colapsar sequências de pontuação e espaços (ex: ".; ; .; ;") em um único espaço
    s = re.sub(r"[\.\;,:\-_/\\\s]{2,}", " ", s)
    # remover repetições adjacentes de uma mesma palavra
    s = re.sub(r"\b(\w+)(?:\s+\1\b)+", r"\1", s, flags=re.IGNORECASE)
    # colapsar espaços múltiplos e trim
    s = re.sub(r"\s+", " ", s).strip()
    return s
COLUMNS = [
    ("A iniciar",                 "#b3e2cd", 100),  # Pastel2[0] verde menta
    ("Visita pré-implantação",    "#fdcdac", 101),  # Pastel2[1] pêssego
    ("Instalação do sistema",     "#cbd5e8", 102),  # Pastel2[2] azul acinzentado
    ("Implantação em andamento",  "#f4cae4", 103),  # Pastel2[3] rosa
    ("Aguardando RDM",            "#e6f5c9", 51),   # Pastel2[4] verde claro
    ("Implantação pausada",       "#fff2ae", 104),  # Pastel2[5] amarelo
    ("Implantação cancelada",     "#f1e2cc", 105),  # Pastel2[6] bege
    ("Visita pós-implantação",    "#cccccc", 106),  # Pastel2[7] cinza
]
COLUMN_MAP = {name: {"color": color, "situacao": situ} for (name, color, situ) in COLUMNS}

# ---------- SQL ----------
SQL_ATENDIMENTOS_IMPLANTACAO = """
SELECT
    A.NumAtendimento,
    A.Desdobramento,
    A.AssuntoAtendimento,
    A.RegInclusao AS Abertura,
    A.DataProxContato,
    A.CodCliente,
    A.CodClassificacaoAtendimento,
    C.NomeCliente,
    A.Situacao,
	U.NomeUsuario,
    (
        SELECT MAX(I2.RegInclusao)
        FROM AtendimentoIteracao I2 WITH (NOLOCK)
        WHERE I2.NumAtendimento = A.NumAtendimento
          AND I2.Desdobramento = A.Desdobramento   
    ) AS UltimaIteracao,
    (
        SELECT TOP 1 CONVERT(NVARCHAR(MAX), I3.TextoIteracao)
        FROM AtendimentoIteracao I3 WITH (NOLOCK)
        WHERE I3.NumAtendimento = A.NumAtendimento
          AND I3.Desdobramento = A.Desdobramento   
        ORDER BY I3.NumIteracao DESC
    ) AS TextoIteracao
FROM CNSAtendimento A  
INNER JOIN CnsClientes C WITH (NOLOCK)
    ON A.CodCliente = C.CodCliente
    AND A.CodEmpresa = C.CodEmpresa
INNER JOIN Usuarios U WITH (NOLOCK)
    ON A.CodUsuario = U.CodUsuario
WHERE
    A.AssuntoAtendimento = N'Implantação'
    AND A.Situacao = 0
    --AND A.Desdobramento = 0  
ORDER BY
    C.NomeCliente;

"""

# SQL para listagem de implantações finalizadas (usada pela página/diálogo de "Implantações finalizadas")
SQL_ATENDIMENTOS_IMPLANTACAO_FINALIZADA = """
SELECT
    A.NumAtendimento,
    A.Desdobramento,
    A.AssuntoAtendimento,
    A.RegInclusao AS Abertura,
    A.CodCliente,
    C.NomeCliente,
    A.Situacao,
    U.NomeUsuario,
    MAX(I.RegInclusao) AS UltimaIteracao,
    (
        SELECT TOP 1 CONVERT(NVARCHAR(MAX), I2.TextoIteracao)
        FROM AtendimentoIteracao I2 WITH (NOLOCK)
        WHERE I2.NumAtendimento = A.NumAtendimento
          AND I2.Desdobramento = 0
        ORDER BY I2.NumIteracao DESC
    ) AS TextoIteracao
FROM CNSAtendimento A WITH (NOLOCK)
INNER JOIN CnsClientes C WITH (NOLOCK)
    ON A.CodCliente = C.CodCliente
    AND A.CodEmpresa = C.CodEmpresa
INNER JOIN Usuarios U WITH (NOLOCK)
    ON A.CodUsuario = U.CodUsuario
LEFT JOIN AtendimentoIteracao I WITH (NOLOCK)
    ON I.NumAtendimento = A.NumAtendimento
    AND I.Desdobramento = A.Desdobramento
WHERE
    A.AssuntoAtendimento = N'Implantação'
    AND A.Situacao = 1
    AND A.CodClassificacaoAtendimento = 51
    AND A.Desdobramento = 0
GROUP BY
    A.NumAtendimento,
    A.Desdobramento,
    A.AssuntoAtendimento,
    A.RegInclusao,
    A.CodCliente,
    C.NomeCliente,
    A.Situacao,
    U.NomeUsuario
ORDER BY
    C.NomeCliente;

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


def fetch_implantacoes_finalizadas():
    """Busca atendimentos de implantação com Situacao = 1 (finalizados).

    Retorna lista de dicionários compatível com a UI usada pela página/diálogo
    de 'Implantações finalizadas'.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(SQL_ATENDIMENTOS_IMPLANTACAO_FINALIZADA)
        cols = [c[0] for c in cur.description]
        rows = cur.fetchall()
        return [dict(zip(cols, row)) for row in rows]
    except Exception as _db_err:
        import traceback
        print(f"[fetch_implantacoes_finalizadas] ERRO: {_db_err}")
        traceback.print_exc()
        raise  # re-levanta para que o caller possa exibir ui.notify
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


def fetch_history(num_atendimento, desdobramento=None):
    """Busca iterações do atendimento. Se `desdobramento` for informado, filtra
    apenas pelas iterações desse desdobramento.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        if desdobramento is None:
            cur.execute(SQL_ATENDIMENTO_ITERACAO, (num_atendimento,))
        else:
            # filtrar por NumAtendimento e Desdobramento
            sql = SQL_ATENDIMENTO_ITERACAO.replace(
                "WHERE AI.NumAtendimento = ?",
                "WHERE AI.NumAtendimento = ? AND AI.Desdobramento = ?",
            )
            cur.execute(sql, (num_atendimento, desdobramento))
        cols = [c[0] for c in cur.description]
        rows = cur.fetchall()
        return [dict(zip(cols, row)) for row in rows]
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


def fetch_latest_iteration(num_atendimento, desdobramento=None):
    """Retorna a última iteração (uma linha) com NomeUsuario e Data/Hora/Texto, ou None.

    Se `desdobramento` for informado, filtra apenas as iterações daquele desdobramento.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        if desdobramento is None:
            sql = """
            SELECT TOP 1 AI.NumIteracao, AI.DataIteracao, AI.HoraIteracao, AI.TextoIteracao, U.NomeUsuario
            FROM AtendimentoIteracao AI WITH (NOLOCK)
            LEFT JOIN Usuarios U WITH (NOLOCK) ON AI.CodUsuario = U.CodUsuario
            WHERE AI.NumAtendimento = ?
            ORDER BY AI.NumIteracao DESC
            """
            cur.execute(sql, (num_atendimento,))
        else:
            sql = """
            SELECT TOP 1 AI.NumIteracao, AI.DataIteracao, AI.HoraIteracao, AI.TextoIteracao, U.NomeUsuario
            FROM AtendimentoIteracao AI WITH (NOLOCK)
            LEFT JOIN Usuarios U WITH (NOLOCK) ON AI.CodUsuario = U.CodUsuario
            WHERE AI.NumAtendimento = ? AND AI.Desdobramento = ?
            ORDER BY AI.NumIteracao DESC
            """
            cur.execute(sql, (num_atendimento, desdobramento))
        row = cur.fetchone()
        if not row:
            return None
        cols = [c[0] for c in cur.description]
        return dict(zip(cols, row))
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


def fetch_rdms(num_atendimento):
    """Busca RDMs vinculadas ao atendimento (se existir tabela CnsRDM)."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Ajuste: nomes das colunas reais na tabela CnsRDM são diferentes
        # Selecionamos colunas existentes e as aliasamos para manter a API usada pela UI
        sql = (
            "SELECT NumRDM AS IdRdm, NumAtendimento, Desdobramento, NomeTipoRDM, "
            "DescricaoRDM AS Descricao, RegInclusao, CASE "
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
            "FROM CnsRDM WITH (NOLOCK) WHERE NumAtendimento = ? ORDER BY RegInclusao DESC"
        )
        cur.execute(sql, (num_atendimento,))
        cols = [c[0] for c in cur.description]
        rows = cur.fetchall()
        result = [dict(zip(cols, row)) for row in rows]
        # Limpa textos RTF das RDMs (semelhante ao tratamento das interações)
        for r in result:
            try:
                # Limpa e sanitiza descrição (pode vir em RTF)
                raw = r.get("Descricao") or ""
                r["Descricao"] = sanitize_text(limpar_rtf(raw))
                # remover ruídos e marcações repetidas deixadas pela conversão RTF
                r["Descricao"] = normalize_description(r["Descricao"])
            except Exception:
                r["Descricao"] = sanitize_text(r.get("Descricao") or "")
            # sanitizar Desdobramento (preservar 0 em vez de transformá-lo em string vazia)
            try:
                desdob_raw = r.get("Desdobramento")
                r["Desdobramento"] = sanitize_text(desdob_raw) if desdob_raw is not None else ""
            except Exception:
                r["Desdobramento"] = ""
            # sanitizar situação legível da RDM
            try:
                r["SituacaoRDM"] = sanitize_text(r.get("SituacaoRDM") or "")
            except Exception:
                r["SituacaoRDM"] = ""
            # sanitizar NomeTipoRDM
            try:
                r["NomeTipoRDM"] = sanitize_text(r.get("NomeTipoRDM") or "")
            except Exception:
                r["NomeTipoRDM"] = ""
        return result
    except Exception:
        return []
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


def update_situacao_on_move(num_atendimento, new_situacao_code):
    # Por decisão do cliente, a operação de mover NÃO deve alterar o banco de dados
    # de forma alguma (nenhum UPDATE ou INSERT). Esta função foi mantida como
    # placeholder para compatibilidade, mas não realizará nenhuma operação de
    # escrita no banco. Se for chamada, apenas retorna False indicando que nenhuma
    # atualização foi feita.
    try:
        # opcional: log local para diagnóstico (não persiste no DB)
        print(f"update_situacao_on_move called for {num_atendimento} -> {new_situacao_code} (no-op)")
    except Exception:
        pass
    return False


# note: historic DB inserts for moves were removed — move observations are shown in-memory only
SQL_ATENDIMENTOS_POR_CLIENTE = """
select CodCliente, NumAtendimento, Desdobramento, NomeTipoAtendimento, AssuntoAtendimento, Situacao
from cnsAtendimento
where CodCliente = ?
"""


def fetch_atendimentos_por_cliente(cod_cliente):
    """Retorna lista de dicionários com os atendimentos do cliente identificado por `cod_cliente`.

    Se ocorrer qualquer erro de consulta, retorna lista vazia.
    """
    try:
        # get_db_connection é o helper utilizado pelo restante do módulo
        conn = get_db_connection()
    except Exception:
        return []
    try:
        cur = conn.cursor()
        cur.execute(SQL_ATENDIMENTOS_POR_CLIENTE, (cod_cliente,))
        cols = [c[0] for c in (cur.description or [])]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        try:
            cur.close()
        except Exception:
            pass
        return rows
    except Exception:
        try:
            cur.close()
        except Exception:
            pass
        return []


# ---------- UI ----------
logged_user = {"CodUsuario": None, "NomeUsuario": None}

# contêiner raiz para trocar views (inicializado no start_app)
root = None

# diretório para armazenar imagens extraídas em cache
CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache_images")
os.makedirs(CACHE_DIR, exist_ok=True)
# TTL do cache em dias (pode ser alterado via variável de ambiente CACHE_TTL_DAYS)
try:
    CACHE_TTL_DAYS = int(os.getenv("CACHE_TTL_DAYS", "30"))
except Exception:
    CACHE_TTL_DAYS = 30


def _image_cache_key(content) -> str:
    """Retorna a chave (sha256 hex) para o conteúdo fornecido.

    Aceita bytes/str/None.
    """
    if content is None:
        return None
    try:
        if isinstance(content, (bytes, bytearray)):
            b = bytes(content)
        else:
            b = str(content).encode("utf-8", errors="ignore")
        return hashlib.sha256(b).hexdigest()
    except Exception:
        return None


def _image_flag_path_for_key(key: str) -> str:
    return os.path.join(CACHE_DIR, f"{key}.hasimg") if key else None


def get_image_flag_for_content(content) -> "bool|None":
    """Retorna True/False se o cache indicar presença de imagem, ou None se não houver cache."""
    try:
        key = _image_cache_key(content)
        if not key:
            return None
        p = _image_flag_path_for_key(key)
        if p and os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    v = f.read(1)
                return v == "1"
            except Exception:
                return None
        return None
    except Exception:
        return None


def set_image_flag_for_content(content, exists: bool):
    """Grava arquivo de flag indicando se o conteúdo contém uma imagem.

    O arquivo é limpo pelo `clean_cache()` baseado em mtime.
    """
    try:
        key = _image_cache_key(content)
        if not key:
            return
        p = _image_flag_path_for_key(key)
        if not p:
            return
        with open(p, "w", encoding="utf-8") as f:
            f.write("1" if exists else "0")
    except Exception:
        pass


def clean_cache():
    """Remove arquivos do cache mais antigos que CACHE_TTL_DAYS (baseado em mtime)."""
    try:
        now = time.time()
        ttl_seconds = CACHE_TTL_DAYS * 24 * 3600
        removed = 0

        # percorrer arquivos no diretório de cache (inclui subdiretórios)
        for root_dir, dirs, files in os.walk(CACHE_DIR):
            # preservar o subdiretório TEMP_IMAGE_SUBDIR (ex: tmp/) — iremos limpar seus arquivos, mas não o próprio diretório
            for fname in files:
                try:
                    full = os.path.join(root_dir, fname)
                    # checar mtime
                    mtime = os.path.getmtime(full)
                    if (now - mtime) > ttl_seconds:
                        try:
                            os.remove(full)
                            removed += 1
                        except Exception:
                            pass
                except Exception:
                    continue

        if removed:
            # debug print removed
            pass
        return removed
    except Exception as e:
        # debug print removed
        return 0

    # após remoção de arquivos, tentar remover subdiretórios vazios (ex: tmp/)
    try:
        for name in os.listdir(CACHE_DIR):
            full = os.path.join(CACHE_DIR, name)
            try:
                # preservar o diretório TEMP_IMAGE_SUBDIR (p.ex. tmp/) mesmo que esteja vazio;
                # apenas limpar seu conteúdo — não removemos esse diretório
                if os.path.isdir(full) and name != TEMP_IMAGE_SUBDIR:
                    # listar conteúdo; se vazio, remover diretório
                    if not os.listdir(full):
                        try:
                            os.rmdir(full)
                        except Exception:
                            pass
            except Exception:
                continue
    except Exception:
        pass


def start_periodic_cache_clean(interval_hours=None):
    """Start a daemon thread that calls clean_cache() every interval_hours.

    If interval_hours is None the value is read from env CACHE_CLEAN_INTERVAL_HOURS
    (default 24).
    """
    try:
        if interval_hours is None:
            try:
                interval_hours = int(os.getenv("CACHE_CLEAN_INTERVAL_HOURS", "24"))
            except Exception:
                interval_hours = 24
        interval = max(1, int(interval_hours))
    except Exception:
        interval = 24

    def _worker():
        try:
            while True:
                time.sleep(interval * 3600)
                try:
                    clean_cache()
                except Exception as e:
                    # debug print removed
                    pass
        except Exception as e:
            # debug print removed
            pass

    t = threading.Thread(target=_worker, name="cache-cleaner", daemon=True)
    t.start()


# NOTE: removed start_periodic_temp_cache_clean because the application no
# longer maintains a process-local TEMP_IMAGE_CACHE for temp images.

# footer será criado no start_app()
footer = None


def start_app(host: str = "0.0.0.0", port: int = 8080):
    """Inicializa NiceGUI de forma lazy e inicia a aplicação UI.

    Isso evita que a importação do módulo NiceGUI execute ações pesadas
    automaticamente ao importar este módulo (útil para testes unitários).
    """
    global ui, app, root, footer
    try:
        from nicegui import app as _app
        from nicegui import ui as _ui
    except Exception:
        # re-raise for visibility
        raise
    ui = _ui
    app = _app
    # definir título do navegador igual ao nome da aplicação (compatível com várias versões do NiceGUI)
    try:
        # ui.title existe em versões recentes do NiceGUI; envolver em try/except para compatibilidade
        ui.title(sanitize_text(APP_NAME))
    except Exception:
        try:
            # fallback: injetar <title> no head via ui.html (não sanitizando porque APP_NAME já foi sanitizado)
            ui.html(f"<title>{sanitize_text(APP_NAME)}</title>", sanitize=False)
            # CSS global para reduzir espaçamento vertical entre linhas e elementos
            ui.html('''
                <style>
                    /* reduzir line-height geral e margens verticais para compactar linhas */
                    html, body, * {
                        line-height: 1.15 !important;
                    }
                    /* reduzir margens padrão aplicadas por classes utilitárias */
                    p, li, label, span, div, .text-sm, .text-xs {
                        margin-top: 0 !important;
                        margin-bottom: 0.125rem !important;
                    }
                    /* ajustar utilitários mais comuns */
                    .mb-2 { margin-bottom: 0.25rem !important; }
                    .mb-1 { margin-bottom: 0.125rem !important; }
                    .mb-0 { margin-bottom: 0 !important; }
                    .mt-2 { margin-top: 0.25rem !important; }
                    .mt-1 { margin-top: 0.125rem !important; }
                    /* reduzir espaçamento interno dos cards para ficar mais compacto */
                    .card, .nicegui-card, .ui-card { padding-top: 0.25rem !important; padding-bottom: 0.25rem !important; }
                </style>
            ''', sanitize=False)
        except Exception:
            pass
    # garantir que o título seja definido no client-side (override do NiceGUI) — usar script para forçar
    try:
        safe_app_js = sanitize_text(APP_NAME).replace("'", "\\'")
        ui.html(f"<script>document.title = '{safe_app_js}';</script>", sanitize=False)
    except Exception:
        pass
    # caso NiceGUI/cliente sobrescreva o título depois do carregamento, usar um observer
    try:
        safe_app_js = sanitize_text(APP_NAME).replace("'", "\\'")
        observer_script = (
            "<script>"
            "(function(){"
            f"const desired = '{safe_app_js}';"
            "function setTitle(){ document.title = desired; }"
            "setTitle();"
            "const titleEl = document.querySelector('title');"
            "if (titleEl){ const mo = new MutationObserver(()=> setTitle()); mo.observe(titleEl, { childList:true, characterData:true, subtree:true }); }"
            "let tries=0; const t = setInterval(()=>{ setTitle(); if(++tries>10) clearInterval(t); }, 500);"
            "})();"
            "</script>"
        )
        ui.html(observer_script, sanitize=False)
    except Exception:
        pass

    # rota /static removida (não servimos arquivos estáticos locais)

    # registrar handler de shutdown para limpar o cache automaticamente
    try:
        def _on_shutdown():
            try:
                removed = clean_cache()
            except Exception as e:
                # debug print removed
                pass

        # FastAPI/Starlette suporta add_event_handler para 'shutdown'
        try:
            app.add_event_handler("shutdown", _on_shutdown)
        except Exception:
            # caso a aplicação NiceGUI não exponha add_event_handler em alguma versão,
            # simplesmente ignoramos e não quebramos a inicialização.
            pass
    except Exception:
        pass

    # montar rota estática para servir imagens temporárias
    # registrar endpoint dinâmico para servir imagens em memória: /_temp_img/{key}
    try:
        app.add_api_route("/_temp_img/{key}", temp_image_endpoint, methods=["GET"])
    except Exception as e:
        # debug print removed
        pass

    # rota fallback (HTML) para 'Implantações finalizadas'
    # Evita usar `ui.page` (que não pode ser misturado com UI no escopo global).
    try:
        from fastapi.responses import HTMLResponse

        def _implantacoes_finalizadas_html(request: Request):
            try:
                # obter filtro de ano via query param
                year_param = request.query_params.get("year")
                try:
                    year_filter = int(year_param) if year_param else None
                except Exception:
                    year_filter = None

                cards = fetch_implantacoes_finalizadas() or []

                # helper para converter valores possivelmente datetime/str em date
                def _to_dt(v):
                    if v is None:
                        return None
                    if isinstance(v, datetime):
                        return v
                    s = str(v)
                    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y"):
                        try:
                            return datetime.strptime(s, fmt)
                        except Exception:
                            continue
                    return None

                # coletar anos disponíveis (baseado em Abertura)
                years = set()
                processed = []
                for c in cards:
                    abertura = _to_dt(c.get("Abertura"))
                    if abertura:
                        years.add(abertura.year)
                    processed.append((c, abertura))

                years_list = sorted(years)

                # aplicar filtro por ano (se presente)
                if year_filter:
                    processed = [t for t in processed if t[1] and t[1].year == year_filter]

                rows = []
                for c, abertura in processed:
                    num = c.get('NumAtendimento')
                    nome = sanitize_text(c.get('NomeCliente') or '-')
                    analista = sanitize_text(c.get('NomeUsuario') or '-')
                    ultima = _to_dt(c.get('UltimaIteracao'))
                    abertura_str = abertura.strftime('%Y-%m-%d') if abertura else '-'
                    ultima_str = ultima.strftime('%Y-%m-%d %H:%M:%S') if ultima else '-'
                    periodo = ''
                    try:
                        if abertura and ultima:
                            periodo = f"Período de implantação: {(ultima - abertura).days} dias"
                    except Exception:
                        periodo = ''
                    rows.append(
                        f"<li><strong>{nome}</strong> #{num} — Abertura: {abertura_str} — Última interação: {ultima_str}"
                        f"<br/><small>{periodo} — Analista: {analista}</small></li>"
                    )

                # montar formulário de filtro por ano
                options_html = '<option value="">Todos</option>'
                for y in years_list:
                    sel = ' selected' if (year_filter and y == year_filter) else ''
                    options_html += f'<option value="{y}"{sel}>{y}</option>'

                body = "<ul>" + "".join(rows) + "</ul>" if rows else "<p>Nenhum atendimento encontrado.</p>"
                html = (
                    "<html><head><meta charset=\"utf-8\"><title>Implantações finalizadas</title></head>"
                    "<body style=\"font-family: Arial, Helvetica, sans-serif; padding:16px;\">"
                    "<h1>Implantações finalizadas</h1>"
                    "<form method=\"get\" style=\"margin-bottom:12px;\">"
                    f"Filtrar por ano: <select name=\"year\">{options_html}</select> <button type=\"submit\">Aplicar</button></form>"
                    f"{body}"
                    "<p style=\"margin-top:16px;\"><a href=\"/\">Voltar ao Kanban</a></p>"
                    "</body></html>"
                )
                return HTMLResponse(html)
            except Exception as e:
                return HTMLResponse(f"<html><body><h1>Erro</h1><pre>{e}</pre></body></html>", status_code=500)

        app.add_api_route("/implantacoes_finalizadas", _implantacoes_finalizadas_html, methods=["GET"])
    except Exception:
        pass

    # página de teste do gráfico removida (opção desabilitada)
    # endpoint PNG do gráfico removido (não utilizado)

    # criar contêiner raiz e footer
    root = ui.element("div").classes("w-full p-4")
    footer = ui.footer()
    footer.add_slot("info", f"<span>{APP_NAME} — v{APP_VERSION}</span>")

    # iniciar limpeza periódica do cache
    try:
        # executar uma limpeza imediata ao iniciar a aplicação (garante limpeza em ambientes
        # onde o módulo é importado e start_app é chamado sem passar pelo guard __main__)
        try:
            removed_on_start = clean_cache()
            if removed_on_start:
                # debug print removed
                pass
        except Exception:
            pass

        start_periodic_cache_clean()
    except Exception:
        pass

    # Nota: não iniciamos limpeza periódica de cache em memória.

    # ambiente de teste: se TEST_NUM_ATENDIMENTO estiver definida, tentar
    # pré-popular o cache temporário em disco com a imagem extraída da última
    # iteração desse atendimento (útil para debug local e reprodução automática)
    try:
        test_num = os.getenv("TEST_NUM_ATENDIMENTO")
        if test_num:
            try:
                na = int(test_num)
                latest = fetch_latest_iteration(na)
                if latest and isinstance(latest, dict):
                    rtf = latest.get("TextoIteracao") or ""
                    try:
                        img_b, mime = extract_first_image_from_rtf(rtf)
                        if img_b and mime:
                            key = _image_cache_key(rtf)
                            # debug: log the expected on-disk path and whether it exists before write
                            try:
                                ext = _ext_for_mime(mime)
                                expected_path = _temp_image_path_for_key(key, ext)
                                msg = (
                                    f"[DEBUG] TEST populate: will write temp image path={expected_path} "
                                    f"exists_before={expected_path.exists()} ext={ext}"
                                )
                                # debug logging removed
                            except Exception:
                                pass
                            url = save_temp_image_and_get_url(key, img_b, mime)
                            set_image_flag_for_content(rtf, True)
                            # debug print removed
                        else:
                            # debug print removed
                            pass
                    except Exception as e:
                        # debug print removed
                        pass
                else:
                    # debug print removed
                    pass
            except Exception as e:
                # debug print removed
                pass
    except Exception:
        pass

    # mostrar view inicial (login)
    show_login()

    # iniciar servidor UI
    ui.run(host=host, port=port)


def show_login():
    global root
    # root pode ter sido removido pelo contexto do NiceGUI (por exemplo após reload);
    # limpar de forma segura: se root.clear() falhar, recriamos o elemento root.
    try:
        if root is None:
            raise RuntimeError("root not initialized")
        root.clear()
    except Exception:
        # criar um container apropriado (ui.column) no contexto atual
        root = ui.column().classes("w-full p-4")

    with root:
        # centralizar o formulário de login
        # centralizar horizontal e verticalmente (ocupando a altura da viewport)
        with ui.row().classes("w-full h-screen items-center justify-center"):
            with ui.column().classes("items-center w-full max-w-sm gap-2"):
                # cartão com fundo e sombra ao redor do formulário para destaque
                with ui.card().classes("w-full p-6 rounded shadow-md").style("background:#ffffff;"):
                    ui.markdown(f"## {APP_NAME}").classes("text-center")
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
    global root
    try:
        if root is None:
            raise RuntimeError("root not initialized")
        root.clear()
    except Exception:
        root = ui.column().classes("w-full p-4")

    # preparar estruturas de colunas antes de definir callbacks (evita problemas de closure)
    column_cards = {name: [] for (name, _, _) in COLUMNS}
    start_col = COLUMNS[0][0]
    column_containers = {}
    # armazenar os widgets de label de cabeçalho para podermos atualizar os totalizadores
    header_labels = {}

    # construir mapa reverso: situacao_code -> column_name
    situ_to_column = {v['situacao']: k for k, v in COLUMN_MAP.items() if v.get('situacao') is not None}

    cards_data = fetch_kanban_cards()

    # ── funções auxiliares (definidas antes de serem referenciadas nos botões) ─────
    def _do_refresh(_=None):
        try:
            new_cards = fetch_kanban_cards()
            new_column_cards = {name: [] for (name, _, _) in COLUMNS}
            classification_to_column = {
                7: 'A iniciar', 46: 'Visita pré-implantação', 29: 'Instalação do sistema',
                47: 'Implantação em andamento', 48: 'Implantação pausada',
                49: 'Implantação cancelada', 8: 'Visita pós-implantação', 51: 'Aguardando RDM',
            }
            for r in new_cards:
                try:
                    code = r.get('CodClassificacaoAtendimento')
                    code_int = int(code) if code is not None else None
                    col = classification_to_column.get(code_int, start_col)
                except Exception:
                    col = start_col
                new_column_cards.setdefault(col, []).append(r)
            changed_cols = []
            total_added = total_removed = 0
            for col_name in new_column_cards:
                old_ids = {c.get('NumAtendimento') for c in (column_cards.get(col_name) or [])}
                new_ids = {c.get('NumAtendimento') for c in (new_column_cards.get(col_name) or [])}
                added   = new_ids - old_ids
                removed = old_ids - new_ids
                if added or removed:
                    column_cards[col_name] = list(new_column_cards.get(col_name) or [])
                    changed_cols.append(col_name)
                    total_added   += len(added)
                    total_removed += len(removed)
            if changed_cols:
                render_dashboard()
            else:
                ui.notify('Nenhuma alteração detectada nos cards.', color='info')
                return
            ui.notify(f'Atualização concluída: {len(new_cards)} cards (+{total_added}/-{total_removed})', color='positive')
        except Exception as e:
            ui.notify(f'Erro ao atualizar cards: {e}', color='negative')

    def _open_implantacoes_dialog(_=None):
        def _to_dt(v):
            if v is None:
                return None
            if isinstance(v, datetime):
                return v
            s = str(v)
            for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S",
                        "%Y-%m-%d", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y"):
                try:
                    return datetime.strptime(s, fmt)
                except Exception:
                    continue
            return None
        try:
            fin_cards = fetch_implantacoes_finalizadas() or []
        except Exception as e:
            ui.notify(f'Erro ao carregar implantações finalizadas: {e}', color='negative')
            fin_cards = []
        years = set()
        processed = []
        for c in fin_cards:
            abertura  = _to_dt(c.get('Abertura'))
            ultima_dt = _to_dt(c.get('UltimaIteracao'))
            dur = max(0, (ultima_dt - abertura).days) if (abertura and ultima_dt) else None
            if ultima_dt:
                years.add(ultima_dt.year)
            processed.append((c, abertura, ultima_dt, dur))
        years_list = sorted(years, reverse=True)
        year_opts  = ['Todos'] + [str(y) for y in years_list]
        sort_opts  = ['Cliente A → Z', 'Cliente Z → A', 'Dias: menor → maior', 'Dias: maior → menor']
        dlg = ui.dialog()
        dlg.props('maximized')
        with dlg:
            with ui.card().classes('w-full h-full').style('border-radius:0;padding:0;margin:0;'):
                ui.html("""<style>
                  .fin-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(310px,1fr));gap:14px;padding:16px;}
                  .fin-card{border-radius:8px;border:1px solid #e2e8f0;background:#fff;box-shadow:0 2px 6px rgba(0,0,0,.07);overflow:hidden;}
                  .fin-card-head{background:linear-gradient(90deg,#1e3a5f,#2563eb);padding:10px 14px;}
                  .fin-badge{display:inline-block;border-radius:20px;padding:2px 10px;font-size:.72rem;font-weight:600;}
                  .fin-bar-bg{background:#e2e8f0;border-radius:4px;height:6px;overflow:hidden;margin-top:8px;}
                  .fin-bar-ok{height:6px;border-radius:4px;background:linear-gradient(90deg,#22c55e,#16a34a);}
                  .fin-bar-slow{height:6px;border-radius:4px;background:linear-gradient(90deg,#f97316,#dc2626);}
                </style>""", sanitize=False)
                with ui.row().classes('items-center justify-between w-full px-4 py-3 flex-wrap gap-2').style(
                    'background:linear-gradient(135deg,#1e3a5f,#0f2440);flex-shrink:0;'
                ):
                    with ui.row().classes('items-center gap-2'):
                        ui.label('🏁').style('font-size:1.5rem;')
                        with ui.column().classes('gap-0'):
                            ui.label('Implantações Concluídas').classes('text-xl font-bold text-white')
                            ui.label('Histórico de projetos finalizados').classes('text-xs').style('color:#93c5fd;')
                    with ui.row().classes('items-center gap-3 flex-wrap'):
                        fin_total_label = ui.label('').classes('text-sm font-semibold text-white')
                        ui.button('✕ Fechar', on_click=lambda _=None: dlg.close()).classes('font-semibold text-sm').style(
                            'background:rgba(255,255,255,.18);color:#fff;border:1px solid rgba(255,255,255,.35);border-radius:6px;padding:4px 14px;'
                        )
                with ui.row().classes('items-end gap-3 px-4 py-3 flex-wrap').style(
                    'background:#f1f5f9;border-bottom:1px solid #e2e8f0;flex-shrink:0;'
                ):
                    with ui.column().classes('gap-0'):
                        ui.label('🔍 Buscar cliente').classes('text-xs text-gray-500 font-medium')
                        fin_search = ui.input(placeholder='Digite parte do nome…').classes('w-56').style('background:#fff;border-radius:6px;')
                    with ui.column().classes('gap-0'):
                        ui.label('📅 Filtrar por ano').classes('text-xs text-gray-500 font-medium')
                        fin_year = ui.select(year_opts, value='Todos').classes('w-32').style('background:#fff;border-radius:6px;')
                    with ui.column().classes('gap-0'):
                        ui.label('↕ Ordenar por').classes('text-xs text-gray-500 font-medium')
                        fin_sort = ui.select(sort_opts, value=sort_opts[0]).classes('w-48').style('background:#fff;border-radius:6px;')
                    ui.button('Aplicar', on_click=lambda _=None: _fin_render()).classes('font-semibold text-sm text-white').style(
                        'background:#2563eb;border-radius:6px;padding:6px 18px;align-self:flex-end;'
                    )
                fin_stats = ui.row().classes('items-center gap-3 px-4 py-2 flex-wrap').style(
                    'background:#fff;border-bottom:1px solid #e2e8f0;flex-shrink:0;'
                )
                with ui.scroll_area().classes('w-full').style('flex:1;min-height:0;'):
                    fin_cards_col = ui.column().classes('w-full').style('gap:0;padding:0;')

                def _fin_render():
                    yf = None
                    try:
                        yv = fin_year.value
                        yf = int(yv) if yv and yv != 'Todos' else None
                    except Exception:
                        pass
                    st = (fin_search.value or '').strip().lower()
                    sv = fin_sort.value
                    to_show = [
                        (c, ab, ul, dur) for c, ab, ul, dur in processed
                        if not (yf and (not ul or ul.year != yf))
                        and (not st or st in sanitize_text(c.get('NomeCliente') or '').lower())
                    ]
                    if sv == 'Cliente A → Z':
                        to_show.sort(key=lambda t: sanitize_text(t[0].get('NomeCliente') or '').lower())
                    elif sv == 'Cliente Z → A':
                        to_show.sort(key=lambda t: sanitize_text(t[0].get('NomeCliente') or '').lower(), reverse=True)
                    elif sv == 'Dias: menor → maior':
                        to_show.sort(key=lambda t: (t[3] if t[3] is not None else 99999))
                    elif sv == 'Dias: maior → menor':
                        to_show.sort(key=lambda t: (t[3] if t[3] is not None else -1), reverse=True)
                    duracoes = [t[3] for t in to_show if t[3] is not None]
                    total_v  = len(to_show)
                    avg_d    = round(sum(duracoes) / len(duracoes)) if duracoes else None
                    min_d    = min(duracoes) if duracoes else None
                    max_d    = max(duracoes) if duracoes else None
                    max_prop = max_d if max_d and max_d > 0 else 1
                    fin_total_label.set_text(f"{total_v} registro{'s' if total_v != 1 else ''}")
                    fin_stats.clear()
                    with fin_stats:
                        for icon, lbl, val, bg, fg in [
                            ('📋', 'Total', str(total_v), '#dbeafe', '#1e40af'),
                            ('📅', 'Média (dias)', f'{avg_d}d' if avg_d is not None else 'N/A', '#dcfce7', '#15803d'),
                            ('⚡', 'Mais rápido', f'{min_d}d' if min_d is not None else 'N/A', '#fef9c3', '#854d0e'),
                            ('🐢', 'Mais longo', f'{max_d}d' if max_d is not None else 'N/A', '#fee2e2', '#b91c1c'),
                        ]:
                            with ui.card().classes('px-4 py-2 items-center').style(
                                f'background:{bg};border:none;box-shadow:none;border-radius:8px;min-width:110px;text-align:center;'
                            ):
                                ui.label(f'{icon} {lbl}').classes('text-xs font-medium').style(f'color:{fg};')
                                ui.label(val).classes('text-xl font-bold').style(f'color:{fg};')
                    fin_cards_col.clear()
                    if not to_show:
                        with fin_cards_col:
                            ui.html('<div style="text-align:center;padding:60px 0;color:#94a3b8;width:100%;"><div style="font-size:3rem;">📭</div><div style="font-size:1rem;margin-top:8px;">Nenhum registro encontrado</div></div>', sanitize=False)
                        return
                    html_cards = []
                    for c, abertura, ultima, dur in to_show:
                        num      = c.get('NumAtendimento')
                        nome     = sanitize_text(c.get('NomeCliente') or '-')
                        analista = sanitize_text(c.get('NomeUsuario') or '-')
                        ab_str   = abertura.strftime('%d/%m/%Y') if abertura else '-'
                        ul_str   = ultima.strftime('%d/%m/%Y')   if ultima   else '-'
                        bar_pct  = round((dur / max_prop) * 100) if dur is not None else 0
                        bar_cls  = 'fin-bar-slow' if (avg_d and dur and dur > avg_d) else 'fin-bar-ok'
                        dur_lbl  = f'{dur} dias' if dur is not None else 'N/A'
                        b_bg = '#dcfce7' if (avg_d and dur is not None and dur <= avg_d) else '#fee2e2'
                        b_fg = '#15803d' if (avg_d and dur is not None and dur <= avg_d) else '#b91c1c'
                        html_cards.append(f'<div class="fin-card"><div class="fin-card-head"><div style="font-weight:700;color:#fff;font-size:.95rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="{nome}">{nome}</div><div style="font-size:.75rem;color:#bfdbfe;margin-top:2px;">Atend. #{num}</div></div><div style="padding:12px 14px;"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;"><span style="font-size:.78rem;color:#64748b;">👤 {analista}</span><span class="fin-badge" style="background:{b_bg};color:{b_fg};">&#9201; {dur_lbl}</span></div><div style="font-size:.75rem;color:#64748b;display:flex;gap:14px;margin-bottom:4px;"><span>📅 <strong style="color:#1e293b;">{ab_str}</strong></span><span>✅ <strong style="color:#1e293b;">{ul_str}</strong></span></div><div class="fin-bar-bg"><div class="{bar_cls}" style="width:{bar_pct}%;"></div></div></div></div>')
                    with fin_cards_col:
                        ui.html('<div class="fin-grid">' + ''.join(html_cards) + '</div>', sanitize=False)

                fin_search.on('keydown.enter', lambda _=None: _fin_render())
                fin_year.on('update:model-value', lambda _=None: _fin_render())
                fin_sort.on('update:model-value', lambda _=None: _fin_render())
                _fin_render()
        dlg.open()

    with root:
        # ── CSS do painel principal ────────────────────────────────────────
        ui.html("""<style>
          .kb-header{background:linear-gradient(135deg,#1e3a5f 0%,#0f2440 100%);padding:14px 20px;}
          .kb-filterbar{background:#f1f5f9;border-bottom:2px solid #e2e8f0;padding:10px 20px;}
          .kb-stat{border-radius:8px;padding:6px 16px;font-size:.78rem;font-weight:600;display:inline-flex;align-items:center;gap:6px;}
        </style>""", sanitize=False)

        # ── cabeçalho principal ────────────────────────────────────────────
        with ui.element('div').classes('kb-header w-full mb-0'):
            with ui.row().classes('items-center justify-between w-full flex-wrap gap-3'):
                # lado esquerdo: título + info do usuário
                with ui.row().classes('items-center gap-3'):
                    ui.label('🗂️').style('font-size:1.8rem;')
                    with ui.column().classes('gap-0'):
                        safe_app  = sanitize_text(APP_NAME)
                        safe_ver  = sanitize_text(APP_VERSION)
                        safe_user = sanitize_text(logged_user.get('NomeUsuario', ''))
                        ui.html(
                            f"<div style='font-size:1.25rem;font-weight:700;color:#fff;'>{safe_app}"
                            f"<span style='font-size:.8rem;font-weight:400;color:#93c5fd;margin-left:8px;'>v{safe_ver}</span></div>"
                            f"<div style='font-size:.82rem;color:#bfdbfe;'>👤 {safe_user}</div>",
                            sanitize=False,
                        )
                # lado direito: contadores + botões de ação
                with ui.row().classes('items-center gap-2 flex-wrap'):
                    cards_count_label = ui.html(
                        f"<span class='kb-stat' style='background:rgba(255,255,255,.15);color:#fff;'>"
                        f"📋 {len(cards_data)} cards</span>",
                        sanitize=False,
                    )
                    ui.button('🔄 Atualizar', on_click=_do_refresh).classes('text-sm font-semibold text-white').style(
                        'background:#059669;border-radius:6px;padding:5px 14px;'
                    )
                    ui.button('🏁 Concluídas', on_click=_open_implantacoes_dialog).classes('text-sm font-semibold text-white').style(
                        'background:#dc2626;border-radius:6px;padding:5px 14px;'
                    )
                    ui.button(' Sair', on_click=lambda _=None: show_login()).classes('text-sm font-semibold text-white').style(
                        'background:#f97316;border-radius:6px;padding:5px 14px;'
                    )

        # ── barra de filtros ───────────────────────────────────────────────
        with ui.element('div').classes('kb-filterbar w-full mb-2'):
            with ui.row().classes('items-end gap-4 flex-wrap'):
                with ui.column().classes('gap-0'):
                    ui.label('🔍 Cliente').classes('text-xs text-gray-500 font-medium')
                    filter_cliente = ui.input(placeholder='Parte do nome do cliente…').classes('w-56').style(
                        'background:#fff;border-radius:6px;'
                    )
                with ui.column().classes('gap-0'):
                    ui.label('👤 Responsável').classes('text-xs text-gray-500 font-medium')
                    filter_usuario = ui.input(placeholder='Parte do nome do responsável…').classes('w-52').style(
                        'background:#fff;border-radius:6px;'
                    )
                ui.button('Aplicar filtro', on_click=lambda _=None: _apply_filter()).classes(
                    'text-sm font-semibold text-white'
                ).style('background:#2563eb;border-radius:6px;padding:6px 18px;align-self:flex-end;')
                ui.button('Limpar', on_click=lambda _=None: _clear_filter()).classes(
                    'text-sm font-semibold'
                ).style('background:#e5e7eb;color:#374151;border-radius:6px;padding:6px 14px;align-self:flex-end;')
                filter_count_label = ui.label('').classes('text-sm text-gray-500 self-end')

    # ── distribuir cards iniciais ─────────────────────────────────────────
    _CLASS_TO_COL = {
        7: 'A iniciar', 46: 'Visita pré-implantação', 29: 'Instalação do sistema',
        47: 'Implantação em andamento', 51: 'Aguardando RDM',
        48: 'Implantação pausada', 49: 'Implantação cancelada', 8: 'Visita pós-implantação',
    }
    for _row in cards_data:
        try:
            _code = _row.get('CodClassificacaoAtendimento')
            _code_int = int(_code) if _code is not None else None
            _dest = _CLASS_TO_COL.get(_code_int)
            if _dest:
                column_cards.setdefault(_dest, []).append(_row)
        except Exception:
            continue

    # ── container principal do dashboard ──────────────────────────────────
    with root:
        dashboard_col = ui.column().classes('w-full').style('gap:0; padding:0 16px 24px 16px;')

    # ── estado do filtro ativo ─────────────────────────────────────────────
    active_filter = {'cliente': '', 'usuario': ''}

    # ── helpers de data ────────────────────────────────────────────────────
    def _parse_dt(v):
        if v is None:
            return None
        if isinstance(v, datetime):
            return v
        s = v.decode(errors='ignore') if isinstance(v, (bytes, bytearray)) else str(v)
        for fmt in ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d',
                    '%d/%m/%Y %H:%M:%S', '%d/%m/%Y'):
            try:
                return datetime.strptime(s, fmt)
            except Exception:
                pass
        return None

    def _days_since(v):
        dt = _parse_dt(v)
        return (datetime.now() - dt).days if dt else None

    def _fmt_date(v):
        dt = _parse_dt(v)
        return dt.strftime('%d/%m/%Y') if dt else '-'

    def _apply_filter(_=None):
        active_filter['cliente'] = (filter_cliente.value or '').strip().lower()
        active_filter['usuario'] = (filter_usuario.value or '').strip().lower()
        render_dashboard()
        fc, fu = active_filter['cliente'], active_filter['usuario']
        if fc or fu:
            total = sum(
                len([c for c in (column_cards.get(col, []) or [])
                     if (not fc or fc in sanitize_text(c.get('NomeCliente') or '').lower())
                     and (not fu or fu in sanitize_text(c.get('NomeUsuario') or '').lower())])
                for col, _, _ in COLUMNS
            )
            parts = ([f'cliente "{filter_cliente.value}"'] if fc else []) + \
                    ([f'responsável "{filter_usuario.value}"'] if fu else [])
            filter_count_label.set_text(f'🔎 {total} card(s) — {" + ".join(parts)}')
        else:
            filter_count_label.set_text('')

    def _clear_filter(_=None):
        filter_cliente.set_value('')
        filter_usuario.set_value('')
        active_filter.update({'cliente': '', 'usuario': ''})
        filter_count_label.set_text('')
        render_dashboard()

    filter_cliente.on('keydown.enter', _apply_filter)
    filter_usuario.on('keydown.enter', _apply_filter)

    # ── render principal ───────────────────────────────────────────────────
    def render_dashboard(cols_to_update=None):
        fc = active_filter.get('cliente', '')
        fu = active_filter.get('usuario', '')
        hoje = datetime.now().date()

        # filtrar por coluna
        col_filtered = {}
        all_cards = []
        for col_name, col_color, _ in COLUMNS:
            raw = column_cards.get(col_name, []) or []
            filt = [c for c in raw
                    if (not fc or fc in sanitize_text(c.get('NomeCliente') or '').lower())
                    and (not fu or fu in sanitize_text(c.get('NomeUsuario') or '').lower())]
            col_filtered[col_name] = (filt, col_color)
            all_cards.extend(filt)

        total_geral = len(all_cards)
        n_atrasados = sum(1 for c in all_cards if (_days_since(c.get('Abertura')) or 0) > 120)
        n_prox_hoje = sum(
            1 for c in all_cards
            if (dt := _parse_dt(c.get('DataProxContato'))) and dt.date() == hoje
        )

        dashboard_col.clear()
        with dashboard_col:
            # ── CSS ─────────────────────────────────────────────────────
            ui.html("""<style>
              .db-kpi{background:#fff;border:1px solid #e2e8f0;border-radius:10px;
                      padding:14px 20px;text-align:center;min-width:120px;
                      box-shadow:0 1px 4px rgba(0,0,0,.06);}
              .db-chip{display:inline-block;border-radius:20px;padding:1px 9px;
                       font-size:.7rem;font-weight:600;white-space:nowrap;}
              .db-row{display:flex;align-items:center;gap:10px;padding:8px 14px;
                      border-bottom:1px solid #f1f5f9;}
              .db-dot{width:10px;height:10px;border-radius:50%;flex-shrink:0;}
              .db-act{border:1px solid #e2e8f0!important;border-radius:5px!important;
                      padding:2px 10px!important;font-size:.72rem!important;
                      background:#fff!important;color:#374151!important;
                      box-shadow:none!important;min-height:unset!important;}
              .db-act:hover{background:#f1f5f9!important;}
              .db-section{border-radius:8px;overflow:hidden;margin-bottom:10px;
                          box-shadow:0 1px 4px rgba(0,0,0,.05);}
              .db-section>.q-expansion-item__container>.q-item{color:#1e293b!important;font-weight:600;}
            </style>""", sanitize=False)

            # ── KPIs ─────────────────────────────────────────────────────
            with ui.row().classes('w-full gap-3 py-3 flex-wrap items-stretch'):
                for icon, label, val, bg, fg in [
                    ('📋', 'Total ativo',      str(total_geral), '#dbeafe', '#1e40af'),
                    ('🔴', 'Em atraso >120d',  str(n_atrasados), '#fee2e2', '#b91c1c'),
                    ('📅', 'Contato hoje',      str(n_prox_hoje), '#fef9c3', '#854d0e'),
                ]:
                    ui.html(
                        f'<div class="db-kpi" style="background:{bg};border-color:{bg};">'
                        f'<div style="font-size:.68rem;font-weight:600;color:{fg};margin-bottom:4px;">{icon} {label}</div>'
                        f'<div style="font-size:1.6rem;font-weight:700;color:{fg};">{val}</div></div>',
                        sanitize=False)
                for col_name, col_color, _ in COLUMNS:
                    cnt = len(col_filtered[col_name][0])
                    ui.html(
                        f'<div class="db-kpi" style="background:{col_color};border-color:{col_color};border-top:3px solid {col_color};min-width:110px;">'
                        f'<div style="font-size:.65rem;font-weight:600;color:#374151;margin-bottom:3px;">'
                        f'{sanitize_text(col_name)}</div>'
                        f'<div style="font-size:1.3rem;font-weight:700;color:#1e293b;">{cnt}</div></div>',
                        sanitize=False)

            # ── grupos por status ────────────────────────────────────────
            for col_name, col_color, _ in COLUMNS:
                cards_in_col, _ = col_filtered[col_name]
                cards_sorted = sorted(
                    cards_in_col,
                    key=lambda c: (_days_since(c.get('Abertura')) or 0),
                    reverse=True
                )
                with ui.expansion(
                    f'{col_name}   ({len(cards_in_col)})',
                ).classes('w-full db-section').style(
                    f'border-left:4px solid {col_color};background:#fff;'
                ).props(f'header-style="background:{col_color};color:#1e293b;font-weight:600;"'):
                    if not cards_in_col:
                        with ui.row().classes('px-4 py-3'):
                            ui.label('Nenhum registro neste status.').classes('text-sm text-gray-400 italic')
                    for card in cards_sorted:
                        num      = card.get('NumAtendimento')
                        nome     = sanitize_text(card.get('NomeCliente') or '-')
                        resp     = sanitize_text(card.get('NomeUsuario') or '-')
                        days     = _days_since(card.get('Abertura'))
                        prox_v   = card.get('DataProxContato')
                        prox_str = _fmt_date(prox_v)
                        prox_dt  = _parse_dt(prox_v)
                        atrasado     = (days or 0) > 120
                        prox_vencida = prox_dt and prox_dt.date() < hoje
                        prox_hoje_flag = prox_dt and prox_dt.date() == hoje
                        days_bg  = '#fee2e2' if atrasado else '#dbeafe'
                        days_fg  = '#b91c1c' if atrasado else '#1e40af'
                        days_txt = f'{days}d' if days is not None else '?'
                        prox_clr = ('#dc2626' if prox_vencida else
                                    ('#d97706' if prox_hoje_flag else '#2563eb'))
                        prox_icon = ('🔴' if prox_vencida else
                                     ('🟡' if prox_hoje_flag else '📅'))
                        texto_raw = card.get('TextoIteracao') or ''
                        desdob    = card.get('Desdobramento')

                        with ui.row().classes(
                            'items-center gap-2 w-full flex-wrap'
                        ).style('border-bottom:1px solid #f1f5f9;padding:8px 14px;'):
                            # dot colorido
                            ui.html(
                                f'<span class="db-dot" style="background:{col_color};"></span>',
                                sanitize=False)
                            # nome + número
                            ui.html(
                                f'<span style="font-weight:600;font-size:.88rem;color:#0f172a;'
                                f'min-width:180px;max-width:260px;overflow:hidden;'
                                f'text-overflow:ellipsis;white-space:nowrap;" title="{nome}">'
                                f'<span style="color:#94a3b8;font-weight:400;">#{num}</span> {nome}</span>',
                                sanitize=False)
                            # responsável
                            ui.html(
                                f'<span style="font-size:.78rem;color:#64748b;min-width:110px;">'
                                f'👤 {resp}</span>',
                                sanitize=False)
                            # dias aberto
                            ui.html(
                                f'<span class="db-chip" style="background:{days_bg};color:{days_fg};">'
                                f'⏱ {days_txt}</span>',
                                sanitize=False)
                            # próximo contato
                            ui.html(
                                f'<span style="font-size:.78rem;color:{prox_clr};">'
                                f'{prox_icon} {prox_str}</span>',
                                sanitize=False)
                            # alertas
                            if atrasado:
                                ui.html(
                                    '<span class="db-chip" style="background:#fee2e2;color:#b91c1c;">⚠ Atraso</span>',
                                    sanitize=False)
                            if prox_vencida:
                                ui.html(
                                    '<span class="db-chip" style="background:#fef9c3;color:#854d0e;">📞 Vencido</span>',
                                    sanitize=False)

                            # ── botões de ação ────────────────────────────
                            ui.button(
                                'Histórico',
                                on_click=lambda _, n=num, d=desdob: show_history_dialog(n, d)
                            ).classes('db-act')

                            def _rdm_click(_, n=num):
                                rdms = fetch_rdms(n)
                                dlg_r = ui.dialog()
                                dlg_r.classes('w-full max-w-5xl')
                                with dlg_r:
                                    if not rdms:
                                        ui.label('Nenhuma RDM encontrada').classes('text-sm text-gray-500')
                                    else:
                                        from collections import defaultdict as _dd
                                        sm = _dd(list)
                                        for r in rdms:
                                            sm[r.get('SituacaoRDM')].append(r)
                                        with ui.scroll_area().classes('w-full').style('max-height:80vh;'):
                                            for sk in sorted(sm.keys(), key=lambda x: str(x)):
                                                grp = sm[sk]
                                                ui.label(f'{sanitize_text(str(sk) if sk else "")}: {len(grp)}').classes('text-sm font-semibold mt-2')
                                                tm = _dd(list)
                                                for r in grp:
                                                    tm[r.get('NomeTipoRDM') or ''].append(r)
                                                for tn in sorted(tm.keys()):
                                                    ui.label(f'{sanitize_text(str(tn))}: {len(tm[tn])}').style(
                                                        'background:#6b7280;color:#fff;padding:3px 8px;border-radius:5px;').classes('text-sm mb-1')
                                                    for r in tm[tn]:
                                                        md = (
                                                            f"**Nº:** {sanitize_text(str(r.get('IdRdm') or ''))}/{sanitize_text(str(r.get('Desdobramento') or ''))}\n\n"
                                                            f"**Tipo:** {sanitize_text(r.get('NomeTipoRDM') or '')}\n\n"
                                                            f"**Situação:** {sanitize_text(r.get('SituacaoRDM') or '')}\n\n"
                                                            f"**Descrição:** {sanitize_text(r.get('Descricao') or '')}"
                                                        )
                                                        with ui.card().classes('mb-2 p-3 w-full').style('background:#fff;'):
                                                            ui.markdown(md).style('white-space:pre-wrap;overflow-wrap:anywhere;word-break:break-word;')
                                    with ui.row().classes('w-full mt-3 justify-center'):
                                        ui.button('Fechar', on_click=lambda _=None: dlg_r.close()).classes('primary')
                                dlg_r.open()
                            ui.button('RDMs', on_click=_rdm_click).classes('db-act')

                            def _atend_click(_, c=card):
                                cod = c.get('CodCliente') or c.get('CodigoCliente') or c.get('CodCli')
                                if not cod:
                                    ui.notify('Código do cliente não disponível', color='warning')
                                    return
                                rows = fetch_atendimentos_por_cliente(cod) or []
                                from collections import defaultdict as _dd2
                                sg = _dd2(list)
                                for r in rows:
                                    try:
                                        sg[int(r.get('Situacao'))].append(r)
                                    except Exception:
                                        sg[None].append(r)
                                dlg_a = ui.dialog()
                                dlg_a.classes('w-full')
                                with dlg_a:
                                    with ui.row().classes('w-full justify-center'):
                                        with ui.column().classes('w-full max-w-3xl'):
                                            with ui.card().classes('p-3').style('background:#fff;'):
                                                ui.label(f'Total: {len(rows)}').style(
                                                    'background:#7f1d1d;color:#fff;padding:4px;border-radius:6px;'
                                                ).classes('text-sm font-semibold')
                                                for sc, sl in ((0, 'Em aberto'), (1, 'Concluídos')):
                                                    grp = sg.get(sc, [])
                                                    ui.label(f'{sl}: {len(grp)}').classes('text-sm font-semibold mt-1')
                                                    tm2 = _dd2(list)
                                                    for r in grp:
                                                        tm2[r.get('NomeTipoAtendimento') or ''].append(r)
                                                    for tn in sorted(tm2.keys()):
                                                        ui.label(f'{sanitize_text(str(tn))}: {len(tm2[tn])}').style(
                                                            'background:#6b7280;color:#fff;padding:3px 8px;border-radius:5px;').classes('text-sm')
                                                        for r in tm2[tn]:
                                                            ui.label(
                                                                f"{r.get('NumAtendimento')}/{r.get('Desdobramento')} — "
                                                                f"{sanitize_text(str(r.get('AssuntoAtendimento') or ''))}"
                                                            ).classes('text-sm ml-2')
                                                with ui.row().classes('w-full justify-center mt-2'):
                                                    ui.button('Fechar', on_click=lambda _=None: dlg_a.close()).classes('primary')
                                dlg_a.open()
                            ui.button('Atendimentos', on_click=_atend_click).classes('db-act')

                            # imagem
                            _img_avail = False
                            try:
                                _cached = get_image_flag_for_content(texto_raw)
                                if _cached is None:
                                    _ti, _tm = extract_first_image_from_rtf(texto_raw)
                                    _img_avail = bool(_ti and _tm)
                                    set_image_flag_for_content(texto_raw, _img_avail)
                                else:
                                    _img_avail = bool(_cached)
                            except Exception:
                                _img_avail = False

                            if _img_avail:
                                def _img_click(_, rtf=texto_raw):
                                    ib, im = extract_first_image_from_rtf(rtf)
                                    dlg_i = ui.dialog()
                                    with dlg_i:
                                        if ib and im:
                                            ui.image(f'data:{im};base64,{base64.b64encode(ib).decode()}').style(IMG_STYLE)
                                        else:
                                            ui.label('[Imagem] — não foi possível extrair').classes('text-sm text-gray-600')
                                        with ui.row().classes('w-full justify-end gap-2'):
                                            ui.button('Fechar', on_click=lambda _=None: dlg_i.close()).classes('secondary')
                                    dlg_i.open()
                                ui.button('Imagem', on_click=_img_click).classes('db-act')

    render_dashboard()


def show_history_dialog(num_atendimento, desdobramento=None):
    hist = fetch_history(num_atendimento, desdobramento)

    # ordenar por DataIteracao asc e HoraIteracao asc quando possível
    def _make_dt(h):
        try:
            d = h.get("DataIteracao")
            t = h.get("HoraIteracao")
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
        # ordenar por DataIteracao/HoraIteracao em ordem decrescente (mais recentes primeiro)
        hist_sorted = sorted(hist, key=_make_dt, reverse=True)
    except Exception:
        hist_sorted = hist

    dlg = ui.dialog()
    with dlg:
        # centralizar conteúdo do histórico em lista com largura limitada
        with ui.row().classes("w-full justify-center"):
            with ui.column().classes("w-full max-w-4xl"):
                # título removido pelo usuário: não exibir label de cabeçalho
                for h in hist_sorted:
                    usuario = sanitize_text(h.get("NomeUsuario") or "-")
                    texto = sanitize_text(limpar_rtf(h.get("TextoIteracao") or ""))

                    def _format_dt(d, t):
                        # tenta montar um datetime a partir de DataIteracao (data) e HoraIteracao (hora)
                        # lida com casos em que HoraIteracao vem como
                        # '1900-01-01 12:50:52' e DataIteracao como
                        # '2025-10-17 00:00:00'
                        try:
                            # parse da parte de data
                            date_part = None
                            if isinstance(d, datetime):
                                date_part = d
                            else:
                                s = str(d) if d is not None else ""
                                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y"):
                                    try:
                                        date_part = datetime.strptime(s, fmt)
                                        break
                                    except Exception:
                                        continue
                            if date_part is None:
                                date_part = datetime.min

                            # parse da parte de hora — aceitar tanto 'HH:MM:SS' quanto
                            # um datetime completo com data (ex.: 1900-01-01 12:50:52)
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

                            # construir datetime final: usar a data de date_part
                            # e a hora de time_part quando disponível
                            if time_part:
                                combined = datetime.combine(date_part.date(), time_part)
                            else:
                                combined = date_part

                            # retornar no formato pedido (YYYY-MM-DD HH:MM:SS)
                            return combined.strftime("%Y-%m-%d %H:%M:%S")
                        except Exception:
                            return f"{sanitize_text(d)} {sanitize_text(t)}"

                    data_str = _format_dt(h.get("DataIteracao"), h.get("HoraIteracao"))

                    # cartão por iteração com labels em negrito
                    with ui.card().classes("mb-2 p-3 w-full"):
                        ui.markdown(f"**Data/Hora:** {data_str}  \n\n **Usuário:** {usuario}")
                        # descrição em markdown (texto limpo)
                        ui.markdown(texto)

                        # botão Imagem (apenas se houver imagem extraível no TextoIteracao)
                        rtf_content = h.get("TextoIteracao") or ""
                        img_exists = False
                        try:
                            cached = get_image_flag_for_content(rtf_content)
                            key = _image_cache_key(rtf_content)
                            if cached is None:
                                ib, imime = extract_first_image_from_rtf(rtf_content)
                                img_exists = bool(ib and imime)
                                set_image_flag_for_content(rtf_content, img_exists)
                            else:
                                img_exists = bool(cached)
                        except Exception as e:
                            img_exists = False

                        if img_exists:

                            def _open_history_image(_=None, rtf=rtf_content):
                                try:
                                    key = _image_cache_key(rtf)
                                    cached_now = get_image_flag_for_content(rtf)
                                except Exception:
                                    pass
                                try:
                                    img_b, mime = extract_first_image_from_rtf(rtf)
                                except Exception as e:
                                    img_b, mime = None, None
                                dlg = ui.dialog()
                                dlg.classes("w-full max-w-6xl")
                                with dlg:
                                    if img_b and mime:
                                        key = _image_cache_key(rtf)
                                        # debug: log expected on-disk path before trying to save
                                        try:
                                            ext = _ext_for_mime(mime)
                                            expected_path = _temp_image_path_for_key(key, ext)
                                            msg = (
                                                f"[DEBUG] history will write temp image path={expected_path} "
                                                f"exists_before={expected_path.exists()} ext={ext}"
                                            )
                                            # debug logging removed
                                        except Exception:
                                            pass
                                        url = save_temp_image_and_get_url(key, img_b, mime)
                                        if url:
                                            # debug: log that we are inserting an <img> with this URL
                                            try:
                                                present = temp_image_exists_on_disk(key)
                                                import os

                                                msg = (
                                                    "[DEBUG] creating ui.image: pid="
                                                    f"{os.getpid()} for key={key} url={url} "
                                                    f"present_on_disk={present}"
                                                )
                                                # debug print removed
                                            except Exception:
                                                pass
                                            # Use relative URL to avoid cross-host issues
                                            # so the browser requests the same host/port
                                            rel_url = url  # already starts with '/_temp_img/'
                                            img_html = f'<img src="{rel_url}" style="{IMG_STYLE}">'
                                            ui.html(img_html, sanitize=False)
                                            link_html = (
                                                f'<div style="margin-top:8px;">'
                                                f'<a href="{rel_url}" target="_blank" rel="noopener" '
                                                f'style="color:#ffd700; text-decoration:underline;">'
                                                'Abrir imagem em nova aba</a></div>'
                                            )
                                            ui.html(link_html, sanitize=False)
                                        else:
                                            # fallback para data-uri caso gravação falhe
                                            b64 = base64.b64encode(img_b).decode()
                                            data_img_html = (
                                                f'<img src="data:{mime};base64,{b64}" '
                                                f'style="{IMG_STYLE}">'
                                            )
                                            ui.html(data_img_html, sanitize=False)
                                    else:
                                        ui.label("[Imagem] — não foi possível extrair a imagem").classes(
                                            "text-sm text-gray-600"
                                        )
                                    with ui.row().classes("w-full justify-end gap-2"):
                                        ui.button("Fechar [ESC]", on_click=lambda _=None: dlg.close()).classes(
                                            "secondary"
                                        )
                                dlg.open()

                            ui.button("Imagem", on_click=_open_history_image).classes("secondary")
                # botão fechar centralizado
                with ui.row().classes("w-full justify-center mt-4"):
                    ui.button("Fechar [ESC]", on_click=lambda _: dlg.close()).classes("primary")
        dlg.open()


# ---------- Execução ----------
# A inicialização da UI (show_login/show_kanban + ui.run) fica
# dentro do guard "if __name__ == '__main__'" para evitar que o
# servidor NiceGUI seja iniciado quando este módulo for importado
# por testes ou outras ferramentas.
# ---------- Execução ----------

if __name__ in {"__main__", "__mp_main__"}:
    clean_cache()

    auto = os.getenv("AUTO_KANBAN") == "1"
    if auto:
        logged_user.update({"CodUsuario": 0, "NomeUsuario": "dev"})

    start_app(host=os.getenv("APP_HOST", "0.0.0.0"),
              port=int(os.getenv("APP_PORT", "8888")))
