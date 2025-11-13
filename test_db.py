import pyodbc

# Database configuration
ODBC_DRIVER = "ODBC Driver 17 for SQL Server"
DB_SERVER = "CEOSOFT-SERV2"
DB_NAME = "BDCEOSOFTWARE"


def test_connection():
    try:
        conn_str = f"DRIVER={{{ODBC_DRIVER}}};" f"SERVER={DB_SERVER};" f"DATABASE={DB_NAME};" "Trusted_Connection=yes;"

        print(f"Tentando conectar ao banco de dados: {DB_SERVER}.{DB_NAME}")
        conn = pyodbc.connect(conn_str, autocommit=False)
        print("Conexão bem-sucedida!")

        # Verificar se a tabela Usuarios existe
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT TABLE_NAME
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_NAME = 'Usuarios'
        """
        )

        if not cursor.fetchone():
            print("ERRO: A tabela 'Usuarios' não foi encontrada no banco de dados.")
            return

        # Verificar usuários na tabela
        print("\nLista de usuários na tabela Usuarios:")
        cursor.execute(
            """
            SELECT TOP 10 CodUsuario, NomeUsuario, Senha
            FROM Usuarios WITH (NOLOCK)
        """
        )

        for row in cursor.fetchall():
            print(f"Usuário: {row.NomeUsuario}, Senha: {row.Senha}")

        # Verificar o usuário Alex especificamente
        print("\nVerificando usuário 'Alex':")
        cursor.execute(
            """
            SELECT CodUsuario, NomeUsuario, Senha
            FROM Usuarios WITH (NOLOCK)
            WHERE NomeUsuario = 'Alex'
        """
        )

        user = cursor.fetchone()
        if user:
            print(f"Usuário encontrado: {user.NomeUsuario}, Senha: {user.Senha}")
            print(f"A senha digitada é igual à senha no banco? {'Sim' if user.Senha == 'ajm2l2' else 'Não'}")
        else:
            print("Usuário 'Alex' não encontrado na tabela Usuarios.")

    except Exception as e:
        print(f"ERRO ao conectar ao banco de dados: {str(e)}")
        import traceback

        traceback.print_exc()
    finally:
        if "conn" in locals():
            conn.close()


if __name__ == "__main__":
    test_connection()
