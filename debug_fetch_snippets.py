from authentication import get_db_connection
from rtf_utils import limpar_rtf

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


def sanitize_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray)):
        try:
            s = value.decode('utf-8')
        except Exception:
            s = value.decode('utf-8', errors='replace')
    else:
        s = str(value)
    cleaned = ''.join(ch for ch in s if not (0xD800 <= ord(ch) <= 0xDFFF))
    return cleaned


def main(limit=10):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(SQL_ATENDIMENTOS_IMPLANTACAO)
    cols = [c[0] for c in cur.description]
    rows = cur.fetchmany(limit)
    print(f"Fetched {len(rows)} rows (showing up to {limit})")
    for r in rows:
        row = dict(zip(cols, r))
        num = row.get('NumAtendimento')
        cliente = sanitize_text(row.get('NomeCliente'))
        assunto = sanitize_text(row.get('AssuntoAtendimento'))
        texto_raw = row.get('TextoIteracao') or ''
        texto = limpar_rtf(texto_raw)
        snippet = (texto[:300] + '...') if len(texto) > 300 else texto
        snippet = sanitize_text(snippet)
        print('-' * 80)
        print(f"Num: {num} | Cliente: {cliente} | Assunto: {assunto}")
        print("Snippet:")
        print(snippet)

    cur.close()
    conn.close()


if __name__ == '__main__':
    main(10)
