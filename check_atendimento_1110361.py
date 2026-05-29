"""
Diagnóstico: verifica todos os desdobramentos do atendimento 1110361
e seus CodClassificacaoAtendimento, para identificar por que aparece
na coluna "Aguardando RDM" (código 50).
"""
from authentication import get_db_connection

NUM = 1110361

conn = get_db_connection()
cur = conn.cursor()

print(f"\n{'='*70}")
print(f"  Atendimento #{NUM} — todos os desdobramentos")
print(f"{'='*70}")

cur.execute("""
    SELECT
        A.NumAtendimento,
        A.Desdobramento,
        A.AssuntoAtendimento,
        A.Situacao,
        A.CodClassificacaoAtendimento,
        CA.DescClassificacaoAtendimento,
        C.NomeCliente,
        U.NomeUsuario
    FROM CNSAtendimento A WITH (NOLOCK)
    LEFT JOIN CnsClientes C WITH (NOLOCK)
        ON A.CodCliente = C.CodCliente AND A.CodEmpresa = C.CodEmpresa
    LEFT JOIN Usuarios U WITH (NOLOCK)
        ON A.CodUsuario = U.CodUsuario
    LEFT JOIN ClassificacaoAtendimento CA WITH (NOLOCK)
        ON A.CodClassificacaoAtendimento = CA.CodClassificacaoAtendimento
    WHERE A.NumAtendimento = ?
    ORDER BY A.Desdobramento
""", NUM)

rows = cur.fetchall()
if not rows:
    print("  Nenhum registro encontrado.")
else:
    for r in rows:
        num, desdobr, assunto, situacao, cod_class, desc_class, cliente, usuario = r
        marcador = " ◄ CÓDIGO 50 (Aguardando RDM)!" if cod_class == 50 else ""
        print(f"\n  NumAtendimento : {num}")
        print(f"  Desdobramento  : {desdobr}")
        print(f"  AssuntoAtend.  : {assunto}")
        print(f"  Situacao       : {situacao}  (0=aberto, 1=fechado)")
        print(f"  CodClassif.    : {cod_class}  — {desc_class}{marcador}")
        print(f"  Cliente        : {cliente}")
        print(f"  Responsável    : {usuario}")

cur.close()
conn.close()
print(f"\n{'='*70}\n")
