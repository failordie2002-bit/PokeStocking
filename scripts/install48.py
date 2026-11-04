from pathlib import Path
import re
p=Path('index.html')
if not p.exists():raise SystemExit('index.html missing; refusing to replace site')
s=p.read_text(encoding='utf-8')
# Keep the legacy script; its workflow may reinstall it.
s=re.sub(r'<script\s+defer\s+src="assets/insights48\.js(?:\?[^\"]*)?"\s*></script>','',s)
if '</body>' not in s.lower():raise SystemExit('No closing body tag')
at=s.lower().rfind('</body>')
s=s[:at]+'<script defer src="assets/insights48.js?v=48"></script>\n'+s[at:]
p.write_text(s,encoding='utf-8')
