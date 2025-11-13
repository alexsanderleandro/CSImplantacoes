from authentication import get_db_connection

NUM_ATENDIMENTO = 1110438
NUM_RDM_BASE = "1110316"

conn = get_db_connection()
cur = conn.cursor()

print(f"Checking CnsRDM rows for NumAtendimento = {NUM_ATENDIMENTO}")
try:
    cur.execute("SELECT TOP 50 * FROM CnsRDM WITH (NOLOCK) WHERE NumAtendimento = ?", (NUM_ATENDIMENTO,))
    rows = cur.fetchall()
    cols = [c[0] for c in cur.description] if cur.description else []
    # keep message shorter to avoid long-line linter errors
    print(f"Found {len(rows)} rows by NumAtendimento.")
    print("Columns:", cols)
    for r in rows:
        print(r)
except Exception as e:
    print("Error querying by NumAtendimento:", e)

print(f"\nChecking CnsRDM rows where any text-like column contains '{NUM_RDM_BASE}' (best-effort)")
# Try some flexible searches on common columns
cands = ["IdRdm", "NumRdm", "NumAtendimento", "Descricao"]
for col in cands:
    try:
        sql = f"SELECT TOP 20 * FROM CnsRDM WITH (NOLOCK) WHERE {col} LIKE ?"
        cur.execute(sql, (f"%{NUM_RDM_BASE}%",))
        rows = cur.fetchall()
        if rows:
            print(f"Matches on column {col}: {len(rows)}")
            for r in rows:
                print(r)
        else:
            print(f"No matches on column {col}")
    except Exception as e:
        print(f"Skipping column {col}: {e}")

# Show a general sample of recent RDMs
try:
    cur.execute(
        (
            "SELECT TOP 20 IdRdm, NumRdm, NumAtendimento, Descricao, RegInclusao "
            "FROM CnsRDM WITH (NOLOCK) ORDER BY RegInclusao DESC"
        )
    )
    rows = cur.fetchall()
    print("\nRecent RDMs sample:")
    for r in rows:
        print(r)
except Exception as e:
    print("Error fetching sample:", e)

cur.close()
conn.close()
