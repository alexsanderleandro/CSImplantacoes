from authentication import get_db_connection

num = 1110438
conn = get_db_connection()
cur = conn.cursor()
cur.execute(
    (
        "SELECT NumRDM AS IdRdm, NumAtendimento, DescricaoRDM AS Descricao, RegInclusao "
        "FROM CnsRDM WITH (NOLOCK) WHERE NumAtendimento = ? "
        "ORDER BY RegInclusao DESC"
    ),
    (num,),
)
rows = cur.fetchall()
print("Found", len(rows), "RDM(s) for atendimento", num)
for r in rows:
    print(r)
cur.close()
conn.close()
