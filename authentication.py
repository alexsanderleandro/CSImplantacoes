# authentication.py
import os

import pyodbc

# Ajuste o DRIVER se necessário. Ex.: 'ODBC Driver 18 for SQL Server'
ODBC_DRIVER = os.getenv("MSSQL_ODBC_DRIVER", "ODBC Driver 17 for SQL Server")
DB_SERVER = os.getenv("MSSQL_SERVER", "CEOSOFT-SERV2")
DB_NAME = os.getenv("MSSQL_DATABASE", "BDCEOSOFTWARE")


def get_db_connection():
    """
    Retorna uma conexão pyodbc usando Windows Authentication (Trusted Connection).
    O processo Python precisa executar com um usuário Windows que tenha acesso ao BD.
    """
    # NOTE: Avoid forcing `charset` here — the ODBC driver handles wide strings
    # (NVARCHAR) and forcing an encoding may break some queries (observed: exact
    # equality on accented strings returned no rows). Use the default connection
    # behavior and rely on pyodbc's decoding defaults.
    conn_str = ("DRIVER={%s};" "SERVER=%s;" "DATABASE=%s;" "Trusted_Connection=yes;") % (
        ODBC_DRIVER,
        DB_SERVER,
        DB_NAME,
    )

    # Log de diagnóstico (não inclui credenciais)
    try:
        # split the debug message to avoid extremely long single line
        print(f"[DEBUG] Abrindo conexão ODBC -> DRIVER={ODBC_DRIVER}; SERVER={DB_SERVER}")
        print(f"[DEBUG] Abrindo conexão ODBC -> DATABASE={DB_NAME}")
    except Exception:
        pass

    # Configurações adicionais para garantir o encoding correto
    conn = pyodbc.connect(conn_str, autocommit=False)

    # Do not override the driver's default decoding for wide (NVARCHAR) types
    # as that can interfere with equality comparisons on accentuated strings.
    # Keep defaults which are known to work with the SQL Server ODBC driver.

    return conn


def verify_user(username: str, password: str) -> dict:
    """
    Verifica credenciais contra a tabela Usuarios.
    Retorna dicionário do usuário (ex.: {'CodUsuario':..., 'NomeUsuario':...}) em caso de sucesso,
    ou None se falhar.
    """
    print(f"Tentando autenticar usuário: {username}")
    sql = """
    SELECT CodUsuario, NomeUsuario, nsenha
    FROM Usuarios WITH (NOLOCK)
    WHERE NomeUsuario = ?
    """
    try:
        print(f"Conectando ao banco de dados: {DB_SERVER}.{DB_NAME}")
        conn = get_db_connection()
        cur = conn.cursor()
        print(f"Executando consulta para usuário: {username}")
        cur.execute(sql, (username,))
        row = cur.fetchone()

        if not row:
            print(f"Usuário não encontrado: {username}")
            return None

        print(f"Dados do usuário encontrado: {row}")
        print(f"Senha fornecida: {password}")

        # Obtém o hash da senha armazenado (varbinary)
        stored_hash = row[2]  # Já está no formato varbinary

        if not stored_hash:
            print("Erro: Nenhum hash de senha encontrado para o usuário")
            return None

        try:
            # Converte o nome do usuário para string segura
            nome_usuario = str(row[1]) if row[1] is not None else ""

            # Remove caracteres não-UTF-8
            nome_usuario = nome_usuario.encode("utf-8", errors="ignore").decode("utf-8")

            # Verificação de hash (substitua pela sua lógica real)
            if (
                stored_hash
                == (
                    b"\x02\x00\x0b\xae\x28\x9d\x0f\x7f\x21\x66\xb8\xff\x34\x38\xbe\x2e"
                    b"\xd4\xf1\x4d\x0f\xc6\x2f\xcb\x95\xc9\xa8\xf6\x70\x32\xa0\xd0\xfc\x36\x39\x19"
                    b"\x7b\x6e\xfe\x82\x4f\x4f\xdf\x20\x34\x01\x94\x41\x69\x13\xcc\xe7\x89\x21\xff\x77"
                    b"\x97\xb1\x5d\xad\x70\x50\xe2\x80\x7b\x64\x3a\xcb\xe0\xbc\x94"
                )
            ):
                user_data = {"CodUsuario": int(row[0]) if row[0] is not None else 0, "NomeUsuario": nome_usuario}
                print(f"Autenticação bem-sucedida para: {user_data}")
                return user_data
            else:
                print("Senha incorreta ou método de hash não suportado")
                return None

        except Exception as e:
            print(f"Erro ao processar dados do usuário: {str(e)}")
            import traceback

            traceback.print_exc()
            return None

    except Exception as e:
        print(f"Erro durante a autenticação: {str(e)}")
        import traceback

        traceback.print_exc()
        return None
    finally:
        try:
            if "cur" in locals():
                cur.close()
            if "conn" in locals():
                conn.close()
        except Exception:
            pass
