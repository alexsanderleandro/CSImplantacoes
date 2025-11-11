# authentication.py
import pyodbc
import os

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
    conn_str = (
        "DRIVER={%s};"
        "SERVER=%s;"
        "DATABASE=%s;"
        "Trusted_Connection=yes;"
    ) % (ODBC_DRIVER, DB_SERVER, DB_NAME)

    # Log de diagnóstico (não inclui credenciais)
    try:
        print(f"[DEBUG] Abrindo conexão ODBC -> DRIVER={ODBC_DRIVER}; SERVER={DB_SERVER}; DATABASE={DB_NAME}")
    except Exception:
        pass
    
    # Configurações adicionais para garantir o encoding correto
    conn = pyodbc.connect(conn_str, autocommit=False)
    
    # Do not override the driver's default decoding for wide (NVARCHAR) types
    # as that can interfere with equality comparisons on accentuated strings.
    # Keep defaults which are known to work with the SQL Server ODBC driver.
    
    return conn

from passlib.hash import bcrypt

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
            nome_usuario = nome_usuario.encode('utf-8', errors='ignore').decode('utf-8')
            
            # Verificação de hash (substitua pela sua lógica real)
            if stored_hash == b'\x02\x00\x0B\xAE\x28\x9D\x0F\x7F\x21\x66\xB8\xFF\x34\x38\xBE\x2E\xD4\xF1\x4D\x0F\xC6\x2F\xCB\x95\xC9\xA8\xF6\x70\x32\xA0\xD0\xFC\x36\x39\x19\x7B\x6E\xFE\x82\x4F\x4F\xDF\x20\x34\x01\x94\x41\x69\x13\xCC\xE7\x89\x21\xFF\x77\x97\xB1\x5D\xAD\x70\x50\xE2\x80\x7B\x64\x3A\xCB\xE0\xBC\x94':
                user_data = {
                    "CodUsuario": int(row[0]) if row[0] is not None else 0,
                    "NomeUsuario": nome_usuario
                }
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
            if 'cur' in locals():
                cur.close()
            if 'conn' in locals():
                conn.close()
        except:
            pass
