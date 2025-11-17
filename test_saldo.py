from rtf_utils import limpar_rtf
import re

s = r'{\\lang1046\\langfe1046\\f1\\fs20\\cf0 Saldo contratado: 10:00}'
# raw string with double-escaped backslashes so it survives file literal
# but r'' will keep backslashes; here the file contains literal backslashes

txt = limpar_rtf(s)
print("CLEANED>>", txt)

m = re.search(r'\b(\d{1,2}:\d{2})\b', txt)
print("MATCH>>", m.group(1) if m else None)
