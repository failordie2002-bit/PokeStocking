from pathlib import Path
from datetime import datetime, timezone, timedelta
import json

def records(path):
 try:
  blob=json.loads(Path(path).read_text(encoding='utf-8'))
  return blob.get('signals',[]) if isinstance(blob.get('signals',[]),list) else []
 except (OSError,ValueError,TypeError):return []

fresh=datetime.now(timezone.utc)-timedelta(days=45)
rows={}
for path in ['data/rumor_signals_46.json','data/public_signal_archive_47.json']:
 for x in records(path):
  if not isinstance(x,dict) or not x.get('id'):continue
  try:
   date=datetime.fromisoformat(x['published_utc'].replace('Z','+00:00'))
   if date.tzinfo is None: date=date.replace(tzinfo=timezone.utc)
   if date<fresh:continue
  except (ValueError,KeyError,TypeError):continue
  if not x.get('status','').startswith('UNVERIFIED'):continue
  rows[x['id']]=x
output=sorted(rows.values(),key=lambda x:x.get('published_utc',''),reverse=True)[:500]
obj={'generated_utc':datetime.now(timezone.utc).isoformat(),
     'availability':'NOT VERIFIED','coverage':'Partial public-source reports, not verified store inventory',
     'signals':output}
Path('data/rumor_signals_46.json').write_text(json.dumps(obj,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
print('Merged into existing Script 46 section:',len(output),'unverified mentions')
