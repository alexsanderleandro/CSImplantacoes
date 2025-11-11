from authentication import get_db_connection

conn = get_db_connection()
cur = conn.cursor()
cur.execute("SELECT COLUMN_NAME, ORDINAL_POSITION, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='CnsRDM' ORDER BY ORDINAL_POSITION")
cols = cur.fetchall()
print('CnsRDM columns (name, position, type):')
for c in cols:
    print(c)
cur.close()
conn.close()
