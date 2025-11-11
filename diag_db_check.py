from authentication import get_db_connection, ODBC_DRIVER, DB_SERVER, DB_NAME
import pyodbc
import json

def saf(v):
    try:
        if v is None:
            return None
        if isinstance(v, bytes):
            return v.decode('utf-8','replace')
        return str(v)
    except Exception:
        try:
            return repr(v)
        except:
            return '<UNPRINTABLE>'


def main():
    # Tentativa 1: usar get_db_connection (padrão UTF-8)
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('SELECT TOP 1 1')
    except Exception:
        # Se falhar por decode, criar conexão com decodificação em latin-1 para inspecionar
        conn_str = (
            "DRIVER={%s};SERVER=%s;DATABASE=%s;Trusted_Connection=yes;" % (ODBC_DRIVER, DB_SERVER, DB_NAME)
        )
        conn = pyodbc.connect(conn_str, autocommit=False)
        # tentar latin-1 para evitar UnicodeDecodeError
        conn.setdecoding(pyodbc.SQL_CHAR, encoding='latin-1')
        conn.setdecoding(pyodbc.SQL_WCHAR, encoding='latin-1')
        conn.setdecoding(pyodbc.SQL_WMETADATA, encoding='latin-1')
        conn.setencoding(encoding='latin-1')
        cur = conn.cursor()

    sql1 = 'SELECT TOP 20 NumAtendimento, AssuntoAtendimento, Situacao, CodCliente, DataAlteracao FROM CNSAtendimento ORDER BY NumAtendimento DESC'
    cur.execute(sql1)
    try:
        fetched = cur.fetchall()
    except UnicodeDecodeError:
        # refazer com conexão latin-1
        conn.close()
        conn_str = ("DRIVER={%s};SERVER=%s;DATABASE=%s;Trusted_Connection=yes;" % (ODBC_DRIVER, DB_SERVER, DB_NAME))
        conn = pyodbc.connect(conn_str, autocommit=False)
        conn.setdecoding(pyodbc.SQL_CHAR, encoding='latin-1')
        conn.setdecoding(pyodbc.SQL_WCHAR, encoding='latin-1')
        conn.setdecoding(pyodbc.SQL_WMETADATA, encoding='latin-1')
        conn.setencoding(encoding='latin-1')
        cur = conn.cursor()
        cur.execute(sql1)
        fetched = cur.fetchall()

    rows = []
    for r in fetched:
        row_conv = []
        for x in r:
            try:
                row_conv.append(saf(x))
            except Exception:
                try:
                    row_conv.append(repr(x))
                except:
                    row_conv.append('<UNPRINTABLE>')
        rows.append(tuple(row_conv))
    print('TOP20:')
    print(json.dumps(rows, ensure_ascii=False, indent=2))

    sql2 = 'SELECT AssuntoAtendimento, COUNT(*) FROM CNSAtendimento GROUP BY AssuntoAtendimento ORDER BY COUNT(*) DESC'
    cur.execute(sql2)
    try:
        fetched2 = cur.fetchall()
    except UnicodeDecodeError:
        # se isso ocorrer, reconectar com latin-1 e reexecutar
        conn.close()
        conn_str = ("DRIVER={%s};SERVER=%s;DATABASE=%s;Trusted_Connection=yes;" % (ODBC_DRIVER, DB_SERVER, DB_NAME))
        conn = pyodbc.connect(conn_str, autocommit=False)
        conn.setdecoding(pyodbc.SQL_CHAR, encoding='latin-1')
        conn.setdecoding(pyodbc.SQL_WCHAR, encoding='latin-1')
        conn.setdecoding(pyodbc.SQL_WMETADATA, encoding='latin-1')
        conn.setencoding(encoding='latin-1')
        cur = conn.cursor()
        cur.execute(sql2)
        fetched2 = cur.fetchall()

    rows2 = []
    for r in fetched2:
        row_conv = []
        for x in r:
            try:
                row_conv.append(saf(x))
            except Exception:
                try:
                    row_conv.append(repr(x))
                except:
                    row_conv.append('<UNPRINTABLE>')
        rows2.append(tuple(row_conv))
    print('\nASSUNTOS DISTINCT:')
    print(json.dumps(rows2, ensure_ascii=False, indent=2))

    cur.close()
    conn.close()

if __name__ == '__main__':
    main()
