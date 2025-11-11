from authentication import get_db_connection
import binascii

conn = get_db_connection()
cur = conn.cursor()

print('Executando diagnóstico de AssuntoAtendimento...')

q1 = "SELECT AssuntoAtendimento, COUNT(*) as cnt FROM CNSAtendimento GROUP BY AssuntoAtendimento ORDER BY cnt DESC"
q2 = "SELECT TOP 200 NumAtendimento, AssuntoAtendimento, RegInclusao FROM CNSAtendimento WHERE AssuntoAtendimento LIKE '%Implant%' ORDER BY RegInclusao DESC"
q3 = "SELECT COUNT(*) FROM CNSAtendimento WHERE AssuntoAtendimento = 'Implantação'"
q4 = "SELECT COUNT(*) FROM CNSAtendimento WHERE LTRIM(RTRIM(AssuntoAtendimento)) = 'Implantação'"
q5 = "SELECT TOP 50 NumAtendimento, AssuntoAtendimento, CONVERT(varbinary(max), AssuntoAtendimento) as bytes FROM CNSAtendimento WHERE AssuntoAtendimento LIKE '%Implant%'"

try:
    print('\nQuery 1: distinct AssuntoAtendimento (top 50)')
    try:
        cur.execute(q1)
        rows = cur.fetchmany(50)
    except UnicodeDecodeError:
        # fallback: reabrir conexão com latin-1
        import pyodbc
        try:
            cur.close()
            conn.close()
        except:
            pass
        conn_str = (f"DRIVER={{{get_db_connection.__globals__['ODBC_DRIVER']}}};SERVER={get_db_connection.__globals__['DB_SERVER']};DATABASE={get_db_connection.__globals__['DB_NAME']};Trusted_Connection=yes;")
        conn = pyodbc.connect(conn_str, autocommit=False)
        conn.setdecoding(pyodbc.SQL_CHAR, encoding='latin-1')
        conn.setdecoding(pyodbc.SQL_WCHAR, encoding='latin-1')
        conn.setdecoding(pyodbc.SQL_WMETADATA, encoding='latin-1')
        conn.setencoding(encoding='latin-1')
        cur = conn.cursor()
        cur.execute(q1)
        rows = cur.fetchmany(50)

    for val, cnt in rows:
        print(f"{cnt:6d} | {repr(val)}")

    print('\nQuery 3/4: counts for exact equality and trimmed equality')
    cur.execute(q3)
    print('count exact =', cur.fetchone()[0])
    cur.execute(q4)
    print('count trimmed =', cur.fetchone()[0])

    print('\nQuery 2: top 200 rows matching LIKE %%Implant%% (show NumAtendimento, repr(Assunto), RegInclusao)')
    cur.execute(q2)
    rows = cur.fetchall()
    for num, assunto, reg in rows[:200]:
        print(f"{num} | {repr(assunto)} | {reg}")

    print('\nQuery 5: show varbinary of Assunto for first 50 matching rows')
    cur.execute(q5)
    for num, assunto, b in cur.fetchall():
        # b may be bytes
        print(f"{num} | {repr(assunto)} | {binascii.hexlify(b).decode() if b is not None else None}")

except Exception as e:
    import traceback
    print('Erro durante diagnóstico:', e)
    traceback.print_exc()
finally:
    try:
        cur.close()
        conn.close()
    except:
        pass
