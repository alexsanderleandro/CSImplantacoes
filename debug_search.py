from authentication import get_db_connection

Q = r"""
SELECT TOP 100 NumAtendimento, AssuntoAtendimento, CONVERT(VARBINARY(MAX), AssuntoAtendimento) as AssuntoBin
FROM CNSAtendimento
WHERE AssuntoAtendimento LIKE '%Implant%'
   OR AssuntoAtendimento LIKE N'%Implant%'
   OR AssuntoAtendimento LIKE '%Implanta%'
   OR AssuntoAtendimento LIKE N'%Implanta%'
ORDER BY NumAtendimento DESC
"""


def main():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(Q)
        rows = cur.fetchall()
        print("Found", len(rows))
        for r in rows[:20]:
            num, assunto, assunto_bin = r
            # print binary as hex
            try:
                hexbin = assunto_bin.hex() if hasattr(assunto_bin, "hex") else str(assunto_bin)
            except Exception:
                hexbin = str(assunto_bin)
            print({"NumAtendimento": num, "Assunto": assunto, "AssuntoBin": hexbin[:120]})
    except Exception as e:
        print("Error:", e)
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
