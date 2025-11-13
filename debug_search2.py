import os

import pyodbc

ODBC_DRIVER = os.getenv("MSSQL_ODBC_DRIVER", "ODBC Driver 17 for SQL Server")
DB_SERVER = os.getenv("MSSQL_SERVER", "CEOSOFT-SERV2")
DB_NAME = os.getenv("MSSQL_DATABASE", "BDCEOSOFTWARE")

conn_str = "DRIVER={%s};SERVER=%s;DATABASE=%s;Trusted_Connection=yes;" % (ODBC_DRIVER, DB_SERVER, DB_NAME)
print("[DEBUG] conn_str:", conn_str)

conn = pyodbc.connect(conn_str, autocommit=False)
# Set decoding to latin-1 to avoid utf-8 decode errors for inspection
conn.setdecoding(pyodbc.SQL_CHAR, encoding="latin-1")
conn.setdecoding(pyodbc.SQL_WCHAR, encoding="latin-1")
conn.setdecoding(pyodbc.SQL_WMETADATA, encoding="latin-1")
conn.setencoding(encoding="latin-1")
cur = conn.cursor()

Q = "SELECT COUNT(1) FROM CNSAtendimento"
cur.execute(Q)
print("Total atendimentos:", cur.fetchone()[0])

Q2 = (
    "SELECT TOP 20 NumAtendimento, AssuntoAtendimento, "
    "CONVERT(VARBINARY(MAX), AssuntoAtendimento) as AssuntoBin "
    "FROM CNSAtendimento ORDER BY NumAtendimento DESC"
)
cur.execute(Q2)
cols = [c[0] for c in cur.description]
rows = cur.fetchall()
print("Fetched sample rows:", len(rows))
for r in rows[:10]:
    num, assunto, assunto_bin = r
    print("Num:", num, "Assunto(raw):", assunto)
    try:
        print("Assunto bin(hex):", assunto_bin.hex()[:80])
    except Exception:
        print("Assunto bin:", assunto_bin)

# try count where assunto like ì
Q3 = (
    "SELECT COUNT(1) FROM CNSAtendimento WHERE AssuntoAtendimento LIKE '%Implant%' "
    "OR AssuntoAtendimento LIKE N'%Implant%' "
    "OR AssuntoAtendimento LIKE '%Implanta%' "
    "OR AssuntoAtendimento LIKE N'%Implanta%'"
)
try:
    cur.execute(Q3)
    print("Count like Implant:", cur.fetchone()[0])
except Exception as e:
    print("Error Q3:", e)

cur.close()
conn.close()
