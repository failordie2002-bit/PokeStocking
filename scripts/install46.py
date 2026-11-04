from pathlib import Path
p=Path('index.html')
if not p.exists():
    raise SystemExit('index.html absent: refusing to create replacement site')
text=p.read_text(encoding='utf-8')
asset='<script defer src="assets/rumor46.js?v=46repair"></script>'
# Remove earlier broken Script 46 tags without altering other scripts.
import re
text=re.sub(r'<script\s+defer\s+src="assets/rumor46\.js(?:\?[^\"]*)?"\s*></script>','',text)
text=re.sub(r'<link\s+rel="stylesheet"\s+href="assets/rumor46\.css"\s*/?>','',text)
if '</body>' not in text.lower():
    raise SystemExit('Missing body close tag; refusing to modify site')
pos=text.lower().rfind('</body>')
text=text[:pos]+asset+'\n'+text[pos:]
p.write_text(text,encoding='utf-8')
