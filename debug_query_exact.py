import os

import pyodbc

ODBC_DRIVER = os.getenv("MSSQL_ODBC_DRIVER", "ODBC Driver 17 for SQL Server")
DB_SERVER = os.getenv("MSSQL_SERVER", "CEOSOFT-SERV2")
DB_NAME = os.getenv("MSSQL_DATABASE", "BDCEOSOFTWARE")

conn_str = "DRIVER={%s};SERVER=%s;DATABASE=%s;Trusted_Connection=yes;" % (ODBC_DRIVER, DB_SERVER, DB_NAME)
print("[DEBUG] conn_str:", conn_str)

conn = pyodbc.connect(conn_str, autocommit=False)
# set latin-1 to inspect bytes without utf-8 decode errors
conn.setdecoding(pyodbc.SQL_CHAR, encoding="latin-1")
conn.setdecoding(pyodbc.SQL_WCHAR, encoding="latin-1")
conn.setdecoding(pyodbc.SQL_WMETADATA, encoding="latin-1")
conn.setencoding(encoding="latin-1")
cur = conn.cursor()

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
    A.AssuntoAtendimento = N'Implantação'
    AND A.Situacao = 0
ORDER BY C.NomeCliente;
"""

print("Executing exact SQL...")
try:
    cur.execute(SQL)
    rows = cur.fetchall()
    print("Rows count:", len(rows))
    if rows:
        cols = [c[0] for c in cur.description]
        for r in rows[:10]:
            row = list(r)
            # print asunto raw and hex
            asunto = row[1]
            try:
                binval = cur.execute(
                    "SELECT CONVERT(VARBINARY(MAX), AssuntoAtendimento) FROM CNSAtendimento WHERE NumAtendimento = ?",
                    (row[0],),
                ).fetchone()[0]
            except Exception:
                binval = None
            print(dict(zip(cols, row)))
            if binval is not None:
                try:
                    print("Assunto hex:", binval.hex()[:120])
                except Exception:
                    print("Assunto bin:", binval)
except Exception as e:
    print("Error executing SQL:", e)
finally:
    cur.close()
    conn.close()
