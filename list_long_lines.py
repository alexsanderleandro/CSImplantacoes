p = 'C:/Users/alex/Documents/Python/CSImplantações/main.py'
with open(p, encoding='utf-8') as f:
    for i, l in enumerate(f, start=1):
        s = l.rstrip('\n')
        if len(s) > 120:
            print(i, len(s), s)
