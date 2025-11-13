import py_compile
import pathlib
import sys
errors = []
for p in pathlib.Path('.').rglob('*.py'):
    try:
        py_compile.compile(str(p), doraise=True)
    except Exception as e:
        errors.append((str(p), e))
for f, e in errors:
    print(f"Syntax error in {f}: {e}")
if errors:
    sys.exit(1)
print('No syntax errors found')
