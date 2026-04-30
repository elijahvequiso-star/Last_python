import re
from pathlib import Path
path = Path('pev_banking/templates/dashboard.html')
html = path.read_text(encoding='utf8')
m = re.search(r'<script>([\s\S]*)</script>', html)
if not m:
    raise SystemExit('no script tag')
s = m.group(1)
s = re.sub(r'{{[\s\S]*?}}', '0', s)
s = re.sub(r'{%[\s\S]*?%}', '', s)
compile(s, '<string>', 'exec')
print('OK')
