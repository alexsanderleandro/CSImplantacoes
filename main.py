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
from version import APP_NAME, APP_VERSION

# estilo reutilizável para imagens exibidas em diálogos (mantém linhas curtas)
IMG_STYLE = "max-width:100%;max-height:60vh;object-fit:contain;display:block;"

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

# arquivo de log leve para mensagens de debug relacionadas a imagens temporárias.
IMAGE_DEBUG_LOG = IMAGE_CACHE_DIR / "temp_img_debug.log"


def _append_image_debug(msg: str):
    """Append a timestamped debug line to IMAGE_DEBUG_LOG. Non-fatal on error."""
    try:
        ts = datetime.utcnow().isoformat() + "Z"
        with open(IMAGE_DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(f"{ts} {msg}\n")
    except Exception:
        # best-effort logging only
        pass


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
                        print(
                            f"[DEBUG] temp_image_endpoint: pid={os.getpid()} serving from disk path={p} "
                            f"key={key} mime={mime_guess} bytes={len(data)}"
                        )
                        try:
                            _append_image_debug(
                                f"[DEBUG] temp_image_endpoint: pid={os.getpid()} serving from disk path={p} key={key} mime={mime_guess} bytes={len(data)}"
                            )
                        except Exception:
                            pass
                        return Response(content=data, media_type=mime_guess)
                    except Exception:
                        continue
        except Exception as e:
            print(f"[DEBUG] temp_image_endpoint disk lookup error for key={key}: {e}")
            try:
                _append_image_debug(f"[DEBUG] temp_image_endpoint disk lookup error for key={key}: {e}")
            except Exception:
                pass

        # If not found on disk, return 404. We intentionally removed the
        # process-local in-memory fallback because the app no longer relies on
        # per-process memory cache for temp images.
        print(f"[DEBUG] temp_image_endpoint: no entry on disk for key={key}")
        try:
            _append_image_debug(f"[DEBUG] temp_image_endpoint: no entry on disk for key={key}")
        except Exception:
            pass
        raise HTTPException(status_code=404)
    except HTTPException:
        raise
    except Exception as e:
        print(f"[DEBUG] temp_image_endpoint error for key={key}: {e}")
        try:
            _append_image_debug(f"[DEBUG] temp_image_endpoint error for key={key}: {e}")
        except Exception:
            pass
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
            print(
                f"[DEBUG] saved temp image to disk path={p} pid={os.getpid()} "
                f"mime={mime} bytes={len(processed_bytes)}"
            )
            try:
                _append_image_debug(
                    f"[DEBUG] saved temp image to disk path={p} pid={os.getpid()} mime={mime} bytes={len(processed_bytes)}"
                )
            except Exception:
                pass
        except Exception as e:
            print(f"[DEBUG] failed to persist temp image to disk for key={key}: {e}")
            try:
                _append_image_debug(f"[DEBUG] failed to persist temp image to disk for key={key}: {e}")
            except Exception:
                pass
            return None
        return f"/_temp_img/{key}"
    except Exception as e:
        print(f"[DEBUG] unexpected error saving temp image for key={key}: {e}")
        try:
            _append_image_debug(f"[DEBUG] unexpected error saving temp image for key={key}: {e}")
        except Exception:
            pass
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
        # remover flags e arquivos de cache no diretório principal
        for fname in os.listdir(CACHE_DIR):
            full = os.path.join(CACHE_DIR, fname)
            try:
                # ignorar subdiretórios (p.ex. tmp/) nesta passagem
                if not os.path.isfile(full):
                    continue
                mtime = os.path.getmtime(full)
                age = now - mtime
                if age > ttl_seconds:
                    try:
                        os.remove(full)
                        removed += 1
                    except Exception:
                        pass
            except Exception:
                continue

        # também limpar imagens temporárias salvas em cache_images/tmp/
        try:
            tmp_dir = os.path.join(CACHE_DIR, TEMP_IMAGE_SUBDIR)
            if os.path.isdir(tmp_dir):
                for tf in os.listdir(tmp_dir):
                    tfull = os.path.join(tmp_dir, tf)
                    try:
                        if not os.path.isfile(tfull):
                            continue
                        mtime = os.path.getmtime(tfull)
                        age = now - mtime
                        if age > ttl_seconds:
                            try:
                                os.remove(tfull)
                                removed += 1
                            except Exception:
                                pass
                    except Exception:
                        continue
        except Exception:
            pass
        if removed:
            print(f"[DEBUG] clean_cache: removed {removed} expired items from cache")
        return removed
    except Exception as e:
        print(f"[DEBUG] clean_cache error: {e}")
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
                            print(f"[DEBUG] clean_cache: removed empty dir {full}")
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
                    print(f"[DEBUG] periodic clean_cache error: {e}")
        except Exception as e:
            print(f"[DEBUG] cache cleaner thread exiting: {e}")

    t = threading.Thread(target=_worker, name="cache-cleaner", daemon=True)
    t.start()
    print(f"[DEBUG] Started cache cleaner thread with interval {interval} hour(s)")


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

    # montar rota estática para servir imagens temporárias
    # registrar endpoint dinâmico para servir imagens em memória: /_temp_img/{key}
    try:
        app.add_api_route("/_temp_img/{key}", temp_image_endpoint, methods=["GET"])
        print("[DEBUG] Registered dynamic /_temp_img/{key} endpoint (in-memory)")
    except Exception as e:
        print(f"[DEBUG] Failed to register dynamic temp image endpoint: {e}")

    # criar contêiner raiz e footer
    root = ui.element("div").classes("w-full p-4")
    footer = ui.footer()
    footer.add_slot("info", f"<span>{APP_NAME} — v{APP_VERSION}</span>")

    # iniciar limpeza periódica do cache
    try:
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
                print(f"[DEBUG] TEST_NUM_ATENDIMENTO={na} detected: attempting to pre-populate temp image on disk")
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
                                print(msg)
                                try:
                                    _append_image_debug(msg)
                                except Exception:
                                    pass
                            except Exception:
                                pass
                            url = save_temp_image_and_get_url(key, img_b, mime)
                            set_image_flag_for_content(rtf, True)
                            print(
                                f"[DEBUG] TEST populate: saved temp image key={key} url={url} "
                                f"mime={mime} bytes={len(img_b)}"
                            )
                        else:
                            print("[DEBUG] TEST populate: no image extracted from latest iteration")
                    except Exception as e:
                        print(f"[DEBUG] TEST populate: extract error: {e}")
                else:
                    print(f"[DEBUG] TEST populate: no latest iteration found for {na}")
            except Exception as e:
                print(f"[DEBUG] TEST populate error: {e}")
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

    with root:
        # cabeçalho: título + contador de cards (à esquerda) e botão Logout (canto direito)
        cards_data = fetch_kanban_cards()
        # debug console log to help verify how many rows were fetched for the Kanban
        print(f"[DEBUG] show_kanban: {len(cards_data)} cards loaded")
        with ui.row().classes("w-full items-start mb-2 justify-between"):
            with ui.column().classes("items-start"):
                ui.label(
                    f"🗂️ {sanitize_text(APP_NAME)} — "
                    f"{sanitize_text(logged_user.get('NomeUsuario', ''))}"
                ).classes("text-2xl font-bold")
                ui.label(f"{len(cards_data)} cards carregados").classes("text-sm text-gray-500")

            # botão de logout posicionado à direita do cabeçalho
            # botões de utilitários: Limpar cache e Atualizar cards
            def _do_clean_cache(_=None):
                # abrir diálogo de confirmação antes de limpar o cache
                dlg = ui.dialog()
                with dlg:
                    ui.markdown("## Confirmar limpeza do cache")
                    ui.label(
                        "Deseja realmente remover arquivos de cache expirados? Esta ação não pode ser desfeita."
                    ).classes("text-sm text-gray-700")
                    with ui.row().classes("w-full justify-end gap-2 mt-4"):

                        def _confirm(_=None):
                            try:
                                removed = clean_cache()
                                if removed:
                                    ui.notify(f"Cache limpo: {removed} arquivo(s) removidos", color="positive")
                                else:
                                    ui.notify("Cache limpo: nenhum arquivo expirado encontrado", color="info")
                            except Exception as e:
                                ui.notify(f"Erro ao limpar cache: {e}", color="negative")
                            finally:
                                dlg.close()

                        ui.button("Confirmar", on_click=_confirm).classes("primary")
                        ui.button("Cancelar", on_click=lambda _=None: dlg.close()).classes("secondary")

                dlg.open()

            def _do_refresh(_=None):
                try:
                    new_cards = fetch_kanban_cards()
                    # construir mapeamento novo por coluna (por enquanto todas vão para start_col como antes)
                    new_column_cards = {name: [] for (name, _, _) in COLUMNS}
                    for r in new_cards:
                        new_column_cards[start_col].append(r)

                    # calcular diffs por coluna (compare por NumAtendimento)
                    changed_cols = []
                    total_added = 0
                    total_removed = 0
                    for col_name in new_column_cards.keys():
                        old_ids = {c.get("NumAtendimento") for c in (column_cards.get(col_name) or [])}
                        new_ids = {c.get("NumAtendimento") for c in (new_column_cards.get(col_name) or [])}
                        added = new_ids - old_ids
                        removed = old_ids - new_ids
                        if added or removed:
                            # substituir a lista local e marcar a coluna para atualização
                            column_cards[col_name] = [c for c in (new_column_cards.get(col_name) or [])]
                            changed_cols.append(col_name)
                            total_added += len(added)
                            total_removed += len(removed)

                    if changed_cols:
                        # atualizar apenas as colunas que mudaram
                        render_board(cols_to_update=changed_cols)
                    else:
                        # nada mudou, garantir que o UI esteja consistente
                        ui.notify("Nenhuma alteração detectada nos cards.", color="info")
                        return

                    ui.notify(
                        f"Atualização concluída: {len(new_cards)} cards (+{total_added}/-{total_removed})",
                        color="positive",
                    )
                except Exception as e:
                    ui.notify(f"Erro ao atualizar cards: {e}", color="negative")

            ui.button("Limpar cache", on_click=_do_clean_cache).classes("secondary")
            ui.button("Atualizar cards", on_click=_do_refresh).classes("secondary")
            ui.button("Logout", on_click=lambda _: show_login()).classes("secondary")

    # board responsivo: permite overflow-x em telas pequenas e distribui colunas em telas maiores
    with root:
        board = ui.row().classes("w-full gap-4 items-start").style("overflow-x: auto;")
    # Colocar todos os cards inicialmente na coluna "A iniciar"
    for row in cards_data:
        column_cards[start_col].append(row)

    def render_board(cols_to_update=None):
        """Renderiza colunas. Se cols_to_update for None, renderiza todas; caso contrário
        apenas atualiza as colunas listadas (nomes).
        """

        def _format_datetime(value):
            if value is None:
                return "-"
            if isinstance(value, datetime):
                return value.strftime("%Y-%m-%d %H:%M:%S")
            try:
                s = value.decode(errors="ignore") if isinstance(value, (bytes, bytearray)) else str(value)
                for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y"):
                    try:
                        dt = datetime.strptime(s, fmt)
                        return dt.strftime("%Y-%m-%d %H:%M:%S")
                    except Exception:
                        continue
                return sanitize_text(s)
            except Exception:
                return sanitize_text(str(value))

        def _days_open_for_card(card_item):
            try:
                av = card_item.get("Abertura")
                if av is None:
                    return -1
                if isinstance(av, datetime):
                    dt = av
                else:
                    s = av.decode(errors="ignore") if isinstance(av, (bytes, bytearray)) else str(av)
                    dt = None
                    for fmt in (
                        "%Y-%m-%d %H:%M:%S.%f",
                        "%Y-%m-%d %H:%M:%S",
                        "%Y-%m-%d",
                        "%d/%m/%Y %H:%M:%S",
                        "%d/%m/%Y",
                    ):
                        try:
                            dt = datetime.strptime(s, fmt)
                            break
                        except Exception:
                            continue
                if not dt:
                    return -1
                return (datetime.now() - dt).days
            except Exception:
                return -1

        # criar colunas (header + container) na primeira chamada
        if not column_containers:
            board.clear()
            with board:
                for col_name, bg_color, _ in COLUMNS:
                    with ui.column().classes("basis-0 flex-1").style("min-width: 12rem;"):
                        ui.label(col_name).classes("text-md font-semibold p-2 rounded w-full text-center").style(
                            f"background:{bg_color};"
                        )
                        cards_container = ui.column().classes("p-2")
                        column_containers[col_name] = cards_container

        cols = [c[0] for c in COLUMNS] if cols_to_update is None else cols_to_update
        for col_name in cols:
            cards_container = column_containers.get(col_name)
            if cards_container is None:
                continue
            try:
                cards_container.clear()
            except Exception:
                pass

            try:
                # ordenar e renderizar os cards da coluna
                cards_to_render = sorted(column_cards.get(col_name, []) or [], key=_days_open_for_card, reverse=True)
            except Exception:
                cards_to_render = column_cards.get(col_name, []) or []

            for card in cards_to_render:
                num = card.get("NumAtendimento")
                cliente = sanitize_text(card.get("NomeCliente") or "-")
                ultima = _format_datetime(card.get("UltimaIteracao"))
                texto_raw = card.get("TextoIteracao") or ""

                with cards_container:
                    with ui.card().classes("mb-3 shadow-sm").style(
                        f"border-left:4px solid {COLUMN_MAP.get(col_name, {}).get('color', '#ffffff')};"
                    ):
                        # header: cliente + id
                        with ui.row().classes("items-center justify-between w-full"):
                            ui.label(cliente).classes("font-semibold text-lg")
                            with ui.row().classes("items-center"):
                                ui.label(f"#{num}").classes("text-sm text-gray-600 ml-2")

                        # Abertura (dias em aberto) e Próximo contato
                        abertura_val = card.get("Abertura")
                        dt_abertura = None
                        try:
                            if isinstance(abertura_val, datetime):
                                dt_abertura = abertura_val
                            else:
                                s = (
                                    abertura_val.decode(errors="ignore")
                                    if isinstance(abertura_val, (bytes, bytearray))
                                    else str(abertura_val)
                                )
                                for fmt in (
                                    "%Y-%m-%d %H:%M:%S.%f",
                                    "%Y-%m-%d %H:%M:%S",
                                    "%Y-%m-%d",
                                    "%d/%m/%Y %H:%M:%S",
                                    "%d/%m/%Y",
                                ):
                                    try:
                                        dt_abertura = datetime.strptime(s, fmt)
                                        break
                                    except Exception:
                                        continue
                        except Exception:
                            dt_abertura = None

                        days_open = None
                        try:
                            if dt_abertura:
                                days_open = (datetime.now() - dt_abertura).days
                        except Exception:
                            days_open = None

                        if days_open is not None:
                            try:
                                color_class = "text-blue-600" if int(days_open) <= 120 else "text-red-600"
                            except Exception:
                                color_class = "text-red-600"
                            lbl = ui.label(f"Aberto há {days_open} dias").classes(
                                f"text-sm font-bold {color_class} ml-0"
                            )
                            try:
                                if dt_abertura:
                                    ui.tooltip(lbl, f"Data de abertura: {dt_abertura.strftime('%d/%m/%Y')}")
                            except Exception:
                                pass

                        # Próximo contato
                        prox_val = card.get("DataProxContato")
                        dt_prox = None
                        try:
                            if isinstance(prox_val, datetime):
                                dt_prox = prox_val
                            else:
                                s = (
                                    prox_val.decode(errors="ignore")
                                    if isinstance(prox_val, (bytes, bytearray))
                                    else str(prox_val)
                                )
                                for fmt in (
                                    "%Y-%m-%d %H:%M:%S.%f",
                                    "%Y-%m-%d %H:%M:%S",
                                    "%Y-%m-%d",
                                    "%d/%m/%Y %H:%M:%S",
                                    "%d/%m/%Y",
                                ):
                                    try:
                                        dt_prox = datetime.strptime(s, fmt)
                                        break
                                    except Exception:
                                        continue
                        except Exception:
                            dt_prox = None

                        if dt_prox:
                            try:
                                prox_date_str = dt_prox.strftime("%d/%m/%Y")
                            except Exception:
                                prox_date_str = sanitize_text(str(prox_val))
                        else:
                            prox_date_str = "-"

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

                        # última interação e snippet
                        texto = limpar_rtf(texto_raw)
                        snippet = (texto[:250] + "...") if len(texto) > 250 else texto
                        snippet = sanitize_text(snippet)
                        ui.label(f"Última interação: {ultima}").classes("text-xs text-gray-500 mb-1")
                        if snippet:
                            ui.label(snippet).classes("text-sm text-gray-700 mb-2")

                        with ui.row().classes("items-center gap-2"):
                            latest = fetch_latest_iteration(num)
                            analyst = sanitize_text((latest.get("NomeUsuario") if latest else None) or "-")
                            ui.label(f"Analista: {analyst}").classes("text-sm text-gray-600")
                            ui.button("Histórico", on_click=lambda _, n=num: show_history_dialog(n)).classes("primary")

                            # RDMs dialog
                            def _show_rdms_local(_, n=num):
                                rdms = fetch_rdms(n)
                                dlg = ui.dialog()
                                dlg.classes("w-full max-w-6xl")
                                with dlg:
                                    if not rdms:
                                        ui.label("Nenhuma RDM encontrada").classes("text-sm text-gray-500")
                                    else:
                                        with ui.row().classes("w-full justify-center"):
                                            with ui.column().classes("w-full max-w-4xl").style(
                                                "overflow:auto; max-height:60vh;padding-right:8px;"
                                            ):
                                                for r in rdms:
                                                    with ui.card().classes("mb-2 p-3 w-full"):
                                                        numrdm = sanitize_text(r.get("IdRdm") or "")
                                                        desdob_raw = r.get("Desdobramento")
                                                        desdob = (
                                                            sanitize_text(desdob_raw) if desdob_raw is not None else ""
                                                        )
                                                        tipordm = sanitize_text(r.get("NomeTipoRDM") or "")
                                                        situ = sanitize_text(r.get("SituacaoRDM") or "")
                                                        reg = r.get("RegInclusao")
                                                        data_str = _format_datetime(reg)
                                                        desc = sanitize_text(r.get("Descricao") or "")
                                                        md = (
                                                            f"**Nº:** {numrdm} / {desdob}\n\n"
                                                            f"**Tipo de RDM:** {tipordm}\n\n"
                                                            f"**Situação:** {situ}\n\n"
                                                            f"**Abertura:** {data_str}\n\n"
                                                            f"**Descrição:** {desc}"
                                                        )
                                                        ui.markdown(md)
                                    with ui.row().classes("w-full mt-4 justify-center"):
                                        ui.button("Fechar", on_click=lambda _=None: dlg.close()).classes("primary")
                                dlg.open()

                            ui.button("RDMs", on_click=_show_rdms_local).classes("secondary")

                            # imagem: verificar se existe imagem antes de habilitar o botão
                            def _open_image_dialog_local(_, rtf=texto_raw):
                                img_bytes, mime = extract_first_image_from_rtf(rtf)
                                dlg = ui.dialog()
                                with dlg:
                                    if img_bytes and mime:
                                        b64 = base64.b64encode(img_bytes).decode()
                                        ui.image(f"data:{mime};base64,{b64}").style(IMG_STYLE)
                                    else:
                                        ui.label("[Imagem] — não foi possível extrair a imagem").classes(
                                            "text-sm text-gray-600"
                                        )
                                    with ui.row().classes("w-full justify-end gap-2"):
                                        ui.button("Fechar", on_click=lambda _=None: dlg.close()).classes("secondary")
                                dlg.open()

                            # detectar rapidamente se há imagem extraível para habilitar o botão
                            img_available = False
                            try:
                                cached = get_image_flag_for_content(texto_raw)
                                key = _image_cache_key(texto_raw)
                                print(f"[DEBUG] card #{num} image cache key={key} cached={cached}")
                                if cached is None:
                                    try_img, try_mime = extract_first_image_from_rtf(texto_raw)
                                    img_available = bool(try_img and try_mime)
                                    # split debug into two prints to avoid long line length
                                    print(f"[DEBUG] card #{num} extract tried -> has_image={img_available}")
                                    print(f"[DEBUG] card #{num} mime={try_mime}")
                                    # gravar no cache booleano
                                    set_image_flag_for_content(texto_raw, img_available)
                                else:
                                    img_available = bool(cached)
                                    print(f"[DEBUG] card #{num} using cached value -> has_image={img_available}")
                            except Exception as e:
                                img_available = False
                                print(f"[DEBUG] card #{num} image detection error: {e}")

                            btn_img = ui.button("Imagem", on_click=_open_image_dialog_local).classes("secondary")
                            if not img_available:
                                # se o cache explicitamente dizer que não há imagem, oferecemos opção de re-testar
                                try:
                                    if cached is False:

                                        def _open_image_dialog_local_retest(_, rtf=texto_raw):
                                            # forçar reextração ignorando o cache; atualizar flag
                                            try:
                                                img_b, mime = extract_first_image_from_rtf(rtf)
                                            except Exception:
                                                img_b, mime = None, None
                                            # atualizar flag conforme resultado
                                            try:
                                                set_image_flag_for_content(rtf, bool(img_b and mime))
                                            except Exception:
                                                pass
                                            dlg = ui.dialog()
                                            with dlg:
                                                if img_b and mime:
                                                    b64 = base64.b64encode(img_b).decode()
                                                    ui.image(f"data:{mime};base64,{b64}").style(IMG_STYLE)
                                                else:
                                                    ui.label("[Imagem] — não foi possível extrair a imagem").classes(
                                                        "text-sm text-gray-600"
                                                    )
                                                with ui.row().classes("w-full justify-end gap-2"):
                                                    ui.button("Fechar", on_click=lambda _=None: dlg.close()).classes(
                                                        "secondary"
                                                    )
                                            dlg.open()

                                        ui.button("Re-testar imagem", on_click=_open_image_dialog_local_retest).classes(
                                            "secondary"
                                        )
                                        ui.tooltip(
                                            btn_img,
                                            (
                                                "Cache indica ausência de imagem — clique em "
                                                "Re-testar imagem para forçar reextração"
                                            ),
                                        )
                                        # marcar o botão principal como desabilitado visualmente
                                        try:
                                            btn_img.props("disabled", True)
                                        except Exception:
                                            pass
                                    else:
                                        # sem cache explícito e sem imagem encontrada: desabilitar botão
                                        btn_img.props("disabled", True)
                                        ui.tooltip(btn_img, "Nenhuma imagem detectada neste texto")
                                except Exception:
                                    # fallback: apenas esconder o botão se props falhar
                                    try:
                                        btn_img.visible = False
                                    except Exception:
                                        pass

                            # mover
                            options = [name for (name, _, _) in COLUMNS]
                            sel = ui.select(options, value=col_name).classes("w-full")

                            def do_move(_, c=card, select_widget=sel):
                                dest = select_widget.value
                                if dest == col_name:
                                    ui.notify("O card já está nessa coluna", color="warning")
                                    return
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
                                print(f"[DEBUG] history image cache key={key} cached={cached}")
                                if cached is None:
                                    ib, imime = extract_first_image_from_rtf(rtf_content)
                                    img_exists = bool(ib and imime)
                                    print(f"[DEBUG] history extract tried -> has_image={img_exists} mime={imime}")
                                    set_image_flag_for_content(rtf_content, img_exists)
                                else:
                                    img_exists = bool(cached)
                                    print(f"[DEBUG] history using cached value -> has_image={img_exists}")
                            except Exception as e:
                                img_exists = False
                                print(f"[DEBUG] history image detection error: {e}")

                            if img_exists:

                                def _open_history_image(_=None, rtf=rtf_content):
                                    try:
                                        key = _image_cache_key(rtf)
                                        cached_now = get_image_flag_for_content(rtf)
                                        print(f"[DEBUG] history click image key={key} cached={cached_now}")
                                    except Exception:
                                        pass
                                    try:
                                        img_b, mime = extract_first_image_from_rtf(rtf)
                                        print(
                                            "[DEBUG] history click extract -> has_image="
                                            f"{bool(img_b and mime)} mime={mime} bytes_len={len(img_b) if img_b else 0}"
                                        )
                                    except Exception as e:
                                        print(f"[DEBUG] history click extract error: {e}")
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
                                                print(msg)
                                                try:
                                                    _append_image_debug(msg)
                                                except Exception:
                                                    pass
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
                                                    print(msg)
                                                except Exception:
                                                    pass
                                                # Use relative URL to avoid cross-host issues
                                                # so the browser requests the same host/port
                                                rel_url = url  # already starts with '/_temp_img/'
                                                img_html = f'<img src="{rel_url}" style="{IMG_STYLE}">'
                                                ui.html(img_html, sanitize=False)
                                                link_html = (
                                                    f'<div style="margin-top:8px;">'
                                                    f'<a href="{rel_url}" target="_blank" rel="noopener">'
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
                                            ui.button("Fechar", on_click=lambda _=None: dlg.close()).classes(
                                                "secondary"
                                            )
                                    dlg.open()

                                ui.button("Imagem", on_click=_open_history_image).classes("secondary")
                            else:
                                # se o cache indicou ausência, permitir re-teste manual
                                try:
                                    if cached is False:

                                        def _open_history_image_retest(_=None, rtf=rtf_content):
                                            try:
                                                key = _image_cache_key(rtf)
                                                print(f"[DEBUG] history re-test image key={key}")
                                            except Exception:
                                                pass

                                            try:
                                                img_b, mime = extract_first_image_from_rtf(rtf)
                                                # split debug output into two prints to avoid long source lines
                                                print("[DEBUG] history re-test -> has_image=", bool(img_b and mime))
                                                print(f"mime={mime} bytes_len={len(img_b) if img_b else 0}")
                                            except Exception as e:
                                                print(f"[DEBUG] history re-test extract error: {e}")
                                                img_b, mime = None, None
                                            try:
                                                set_image_flag_for_content(rtf, bool(img_b and mime))
                                            except Exception:
                                                pass
                                            dlg = ui.dialog()
                                            dlg.classes("w-full max-w-6xl")
                                            with dlg:
                                                if img_b and mime:
                                                    key = _image_cache_key(rtf)
                                                    # debug: log expected on-disk path before trying to save (retest)
                                                    try:
                                                        ext = _ext_for_mime(mime)
                                                        expected_path = _temp_image_path_for_key(key, ext)
                                                        msg = (
                                                            f"[DEBUG] history re-test will write temp image path={expected_path} "
                                                            f"exists_before={expected_path.exists()} ext={ext}"
                                                        )
                                                        print(msg)
                                                        try:
                                                            _append_image_debug(msg)
                                                        except Exception:
                                                            pass
                                                    except Exception:
                                                        pass
                                                    url = save_temp_image_and_get_url(key, img_b, mime)
                                                    if url:
                                                        try:
                                                            present = temp_image_exists_on_disk(key)
                                                            import os

                                                            pre = "[DEBUG] creating ui.image (retest): pid="
                                                            mid = f"{os.getpid()} for key={key} url={url} "
                                                            post = f"present_on_disk={present}"
                                                            print(pre + mid + post)
                                                        except Exception:
                                                            pass
                                                        # Use relative URL to avoid cross-host issues
                                                        rel_url = url
                                                        img_html = f'<img src="{rel_url}" style="{IMG_STYLE}">'
                                                        ui.html(img_html, sanitize=False)
                                                        link_html = (
                                                            '<div style="margin-top:8px;">'
                                                            f'<a href="{rel_url}" target="_blank" rel="noopener">'
                                                            'Abrir imagem em nova aba</a></div>'
                                                        )
                                                        ui.html(link_html, sanitize=False)
                                            dlg.open()

                                        ui.button("Re-testar imagem", on_click=_open_history_image_retest).classes(
                                            "secondary"
                                        )
                                        ui.tooltip(
                                            None,
                                            (
                                                "Cache indica ausência de imagem — clique em "
                                                "Re-testar imagem para forçar reextração"
                                            ),
                                        )
                                except Exception:
                                    pass
                    # botão fechar centralizado
                    with ui.row().classes("w-full justify-center mt-4"):
                        ui.button("Fechar", on_click=lambda _: dlg.close()).classes("primary")
        dlg.open()

    render_board()


# ---------- Execução ----------
# A inicialização da UI (show_login/show_kanban + ui.run) fica
# dentro do guard "if __name__ == '__main__'" para evitar que o
# servidor NiceGUI seja iniciado quando este módulo for importado
# por testes ou outras ferramentas.
if __name__ in {"__main__", "__mp_main__"}:
    # limpar cache de imagens expiradas antes de iniciar a UI
    clean_cache()

    # Em modo normal, inicializamos a UI via start_app().
    # Se AUTO_KANBAN=1 queremos pular o login e abrir direto o Kanban (útil para debug).
    auto = os.getenv("AUTO_KANBAN") == "1"
    if auto:
        logged_user.update({"CodUsuario": 0, "NomeUsuario": "dev"})

    # start_app fará start_periodic_cache_clean internamente
    # porta e host permanecem como antes
    start_app(host=os.getenv("APP_HOST", "0.0.0.0"), port=int(os.getenv("APP_PORT", "8888")))
