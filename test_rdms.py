import pytest
from authentication import get_db_connection
from rtf_utils import limpar_rtf

# Teste rápido/regressão: busca RDMs para o atendimento 1110438 e garante que
# a descrição limpa não contenha marcador RTF ("{\\rtf").

TEST_ATENDIMENTO = 1110438

SQL = """
SELECT NumRDM AS IdRdm, NumAtendimento, DescricaoRDM AS Descricao, RegInclusao
FROM CnsRDM WITH (NOLOCK)
WHERE NumAtendimento = ?
ORDER BY RegInclusao DESC
"""


def test_rdms_descricao_nao_contem_rtf():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(SQL, (TEST_ATENDIMENTO,))
        rows = cur.fetchall()
        # Se não houver RDMs, falhar de forma informativa
        assert rows, f"Nenhuma RDM encontrada para atendimento {TEST_ATENDIMENTO} — verifique os dados de teste"
        for row in rows:
            # Descrição pode vir como bytes ou str
            descricao = row.Descricao if hasattr(row, 'Descricao') else row[2]
            if descricao is None:
                descricao = ''
            # aplicar limpeza RTF (mesma lógica usada na UI)
            cleaned = limpar_rtf(descricao)
            assert "{\\rtf" not in cleaned, f"Descrição ainda contém RTF depois da limpeza: {cleaned[:200]}"
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass
