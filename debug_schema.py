from authentication import get_db_connection

QUERIES = [
    ("Total atendimentos", "SELECT COUNT(1) FROM CNSAtendimento"),
    ("Distinct assuntos (top 50)", "SELECT DISTINCT TOP 50 AssuntoAtendimento FROM CNSAtendimento"),
    (
        "Sample 20 rows (NumAtendimento, AssuntoAtendimento, Situacao)",
        "SELECT TOP 20 NumAtendimento, AssuntoAtendimento, Situacao FROM CNSAtendimento ORDER BY NumAtendimento DESC",
    ),
]


def main():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        for title, q in QUERIES:
            print("\n---", title, "---")
            try:
                cur.execute(q)
                rows = cur.fetchall()
                for r in rows:
                    print(r)
            except Exception as e:
                print("Erro na query:", e)
        cur.close()
        conn.close()
    except Exception as e:
        print("Erro geral:", e)


if __name__ == "__main__":
    main()
