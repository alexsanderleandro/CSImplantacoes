import sys

# Configura o encoding para UTF-8 no Windows
if sys.platform.startswith("win"):
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from authentication import get_db_connection
from main import SQL_ULTIMA_ITERACAO


def test_database_connection():
    """
    Testa a conexão com o banco de dados e executa diagnósticos detalhados
    """
    print("\n=== Diagnóstico do Banco de Dados ===")

    try:
        # 1. Testa a conexão básica
        print("\n🔍 Testando conexão com o banco de dados...")
        conn = get_db_connection()
        cur = conn.cursor()
        print("✅ Conexão com o banco de dados estabelecida com sucesso!")

        # 2. Lista as tabelas disponíveis
        print("\n📋 Tabelas disponíveis no banco de dados:")
        cur.execute(
            """
            SELECT TABLE_NAME
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_TYPE = 'BASE TABLE'
            ORDER BY TABLE_NAME
        """
        )

        tables = [row[0] for row in cur.fetchall()]
        print(f"Encontradas {len(tables)} tabelas.")

        # 3. Verifica tabelas específicas que são necessárias
        required_tables = ["CNSAtendimento", "CnsClientes", "AtendimentoIteracao", "CnsRDM"]

        print("\n🔍 Verificando tabelas necessárias:")
        missing_tables = []
        for table in required_tables:
            if table in tables:
                print(f"✅ {table} - Encontrada")
            else:
                print(f"❌ {table} - NÃO ENCONTRADA")
                missing_tables.append(table)

        if missing_tables:
            print(f"\n⚠️  ATENÇÃO: {len(missing_tables)} tabelas necessárias não foram encontradas!")
            return False

        # 4. Conta registros em cada tabela necessária
        print("\n📊 Contagem de registros nas tabelas:")
        for table in required_tables:
            try:
                cur.execute(f"SELECT COUNT(*) FROM {table} WITH (NOLOCK)")
                count = cur.fetchone()[0]
                print(f"{table}: {count} registros")
            except Exception as e:
                print(f"❌ Erro ao contar registros em {table}: {str(e)}")

        # 5. Testa consultas específicas
        print("\n🔍 Testando consultas específicas:")

        # 5.1 Verifica atendimentos de implantação
        try:
            cur.execute(
                """
                SELECT COUNT(*)
                FROM CNSAtendimento WITH (NOLOCK)
                WHERE AssuntoAtendimento = 'Implantação'
                AND Situacao = 0
            """
            )
            count = cur.fetchone()[0]
            print(f"Atendimentos de implantação ativos: {count}")

            if count == 0:
                print("⚠️  Nenhum atendimento de implantação ativo encontrado!")
                print("    Verifique se existem registros com AssuntoAtendimento = 'Implantação' e Situacao = 0")
        except Exception as e:
            print(f"❌ Erro ao consultar atendimentos: {str(e)}")

        # 5.2 Verifica dados de exemplo
        print("\n📝 Exemplo de dados em CNSAtendimento:")
        try:
            cur.execute(
                """
                SELECT TOP 5
                    NumAtendimento,
                    AssuntoAtendimento,
                    Situacao,
                    CodCliente,
                    RegInclusao
                FROM CNSAtendimento WITH (NOLOCK)
                WHERE AssuntoAtendimento LIKE '%Implantação%'
                ORDER BY NumAtendimento DESC
            """
            )

            cols = [column[0] for column in cur.description]
            rows = cur.fetchall()

            if rows:
                print("\nResultados encontrados:")
                for row in rows:
                    print("\n---")
                    for idx, value in enumerate(row):
                        print(f"{cols[idx]}: {value}")
            else:
                print("Nenhum registro encontrado com AssuntoAtendimento contendo 'Implantação'")

        except Exception as e:
            print(f"❌ Erro ao buscar exemplo de dados: {str(e)}")

        # 6. Tenta executar a consulta principal com explicação
        print("\n🔍 Analisando a consulta principal...")
        try:
            # Primeiro, vamos ver o plano de execução para entender o que está acontecendo
            explain_query = f"SET SHOWPLAN_TEXT ON;\n{SQL_ULTIMA_ITERACAO}\nSET SHOWPLAN_TEXT OFF;"

            print("\n📝 Plano de execução da consulta principal:")
            for line in explain_query.split("\n"):
                if line.strip():
                    print(f"  {line}")

            # Executa a consulta principal
            print("\n🔍 Executando a consulta principal...")
            cur.execute(SQL_ULTIMA_ITERACAO)
            rows = cur.fetchall()

            if rows:
                print(f"✅ Consulta retornou {len(rows)} registros")
                print("\n📄 Estrutura dos dados retornados:")
                print("Colunas:", [column[0] for column in cur.description])

                # Mostra os primeiros 3 registros como exemplo
                print("\n📝 Primeiros 3 registros:")
                for i, row in enumerate(rows[:3]):
                    print(f"\n--- Registro {i+1} ---")
                    for idx, value in enumerate(row):
                        col_name = cur.description[idx][0]
                        print(f"{col_name}: {value}")
            else:
                print("ℹ️  A consulta não retornou resultados.")

                # Sugere verificar os dados de origem
                print("\n🔍 Verificando possíveis causas:")

                # Verifica se existem dados nas tabelas relacionadas
                print("\n1. Verificando dados em AtendimentoIteracao...")
                cur.execute("SELECT COUNT(*) FROM AtendimentoIteracao WITH (NOLOCK)")
                iteracoes = cur.fetchone()[0]
                print(f"   - Total de iterações: {iteracoes}")

                print("\n2. Verificando dados em CnsRDM...")
                cur.execute("SELECT COUNT(*) FROM CnsRDM WITH (NOLOCK)")
                rdms = cur.fetchone()[0]
                print(f"   - Total de RDMs: {rdms}")

                # Sugere verificar os critérios de junção
                print(
                    """
💡 Dicas para solução:
1. Verifique se existem registros em CNSAtendimento com AssuntoAtendimento = 'Implantação' e Situacao = 0
2. Verifique se existem registros correspondentes em AtendimentoIteracao
3. Verifique se a condição de junção entre as tabelas está correta
4. Considere simplificar a consulta para isolar o problema
"""
                )

        except Exception as e:
            print(f"❌ Erro ao executar a consulta principal: {str(e)}")
            import traceback

            traceback.print_exc()

        # 7. Fecha a conexão
        cur.close()
        conn.close()

        print("\n✅ Diagnóstico concluído!")
        return True

    except Exception as e:
        print(f"\n❌ Erro durante o diagnóstico: {str(e)}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    test_database_connection()
    input("\nPressione Enter para sair...")
