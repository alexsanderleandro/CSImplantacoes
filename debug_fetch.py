from authentication import get_db_connection

SQL = r"""
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
    A.AssuntoAtendimento = 'Implantação'
ORDER BY C.NomeCliente;
"""


def main():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(SQL)
        cols = [c[0] for c in cur.description]
        rows = cur.fetchall()
        print(f"Total rows: {len(rows)}")
        if rows:
            print("Columns:", cols)
            for i, row in enumerate(rows[:10]):
                # convert bytes to str for TextoIteracao if needed
                row = list(row)
                for j, v in enumerate(row):
                    if isinstance(v, (bytes, bytearray)):
                        try:
                            row[j] = v.decode(errors="ignore")
                        except Exception:
                            row[j] = str(v)
                print(i + 1, dict(zip(cols, row)))
        cur.close()
        conn.close()
    except Exception as e:
        print("Erro ao executar query:", e)


if __name__ == "__main__":
    main()
