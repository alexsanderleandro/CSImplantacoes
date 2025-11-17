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


    return conn


def verify_user(username: str, password: str) -> dict:
    """
    Verifica credenciais contra a tabela Usuarios.
    Retorna dicionário do usuário (ex.: {'CodUsuario':..., 'NomeUsuario':...}) em caso de sucesso,
    ou None se falhar.
    """
    print(f"Tentando autenticar usuário: {username}")
    try:
        print(f"Conectando ao banco de dados: {DB_SERVER}.{DB_NAME}")
        conn = get_db_connection()
        cur = conn.cursor()

        # Chama a stored procedure que valida usuário/senha no banco (retorna 1 se válido)
        try:
            print(f"Executando stored procedure csspValidaSenha para: {username}")
            cur.execute("EXEC dbo.csspValidaSenha ?, ?", username, password)
            res = cur.fetchone()
        except Exception as e:
            print(f"Erro ao executar csspValidaSenha: {e}")
            res = None

        if not res or not (isinstance(res, (list, tuple)) and len(res) > 0 and res[0] != 1 and res[0] != True):
            # res[0] == 1 or True indicates valid; handle truthy cases
            pass

        # Interpret result: consider success when res and res[0] == 1 or res[0] is True
        success = bool(res and (res[0] == 1 or res[0] is True))

        if not success:
            print("Usuário ou senha inválidos (csspValidaSenha)")
            return None

        # Se válido, buscar informações do usuário
        try:
            cur.execute("SELECT CodUsuario, NomeUsuario FROM Usuarios WITH (NOLOCK) WHERE NomeUsuario = ?", (username,))
            row = cur.fetchone()
            if not row:
                print(f"Usuário válido mas registro ausente em Usuarios: {username}")
                return {"CodUsuario": 0, "NomeUsuario": username}

            nome_usuario = str(row[1]) if row[1] is not None else ""
            nome_usuario = nome_usuario.encode("utf-8", errors="ignore").decode("utf-8")
            user_data = {"CodUsuario": int(row[0]) if row[0] is not None else 0, "NomeUsuario": nome_usuario}
            print(f"Autenticação bem-sucedida para: {user_data}")
            return user_data
        except Exception as e:
            print(f"Erro ao buscar dados do usuário após validação: {e}")
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
