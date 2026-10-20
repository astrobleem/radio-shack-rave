"""Fetch only the exact public sound source/license files pinned by this release."""
from pathlib import Path,PurePosixPath
import hashlib,io,json,re,urllib.request,zipfile
ROOT=Path(__file__).resolve().parents[1]
def main():
 for name,pinfile in [('libtandy','LIBTANDY.PIN.json'),('libwintandy','LIBWINTANDY-PREPARER.PIN.json')]:
  pin=json.loads((ROOT/pinfile).read_text());repo=pin['repository'];revision=pin['revision']
  if repo!='astrobleem/'+name or not re.fullmatch('[0-9a-f]{40}',revision):raise ValueError('invalid public dependency identity')
  target=ROOT/'deps'/name;missing=[]
  for rel,digest in pin['files'].items():
   path=PurePosixPath(rel)
   if path.is_absolute() or '..' in path.parts:raise ValueError('unsafe dependency path')
   output=target.joinpath(*path.parts)
   if output.exists():
    if hashlib.sha256(output.read_bytes()).hexdigest()!=digest:raise ValueError('local dependency was modified: '+str(output))
   else:missing.append(rel)
  if missing:
   url=f'https://github.com/{repo}/archive/{revision}.zip'
   request=urllib.request.Request(url,headers={'User-Agent':'Rave-pinned-sound-fetcher'})
   with urllib.request.urlopen(request,timeout=60) as response:data=response.read(100_000_001)
   if len(data)>100_000_000:raise ValueError('dependency archive exceeds size bound')
   with zipfile.ZipFile(io.BytesIO(data)) as archive:
    prefix=name+'-'+revision+'/'
    checked={rel:archive.read(prefix+rel) for rel in missing}
    for rel,contents in checked.items():
     if hashlib.sha256(contents).hexdigest()!=pin['files'][rel]:raise ValueError('public source pin mismatch: '+rel)
    for rel,contents in checked.items():
     output=target/rel;output.parent.mkdir(parents=True,exist_ok=True);output.write_bytes(contents)
  target.mkdir(parents=True,exist_ok=True)
  (target/'SOURCE-FETCH.json').write_text(json.dumps({'repository':repo,'revision':revision,'files':pin['files']},indent=2)+'\n')
  print(name,revision,'verified',len(pin['files']),'public source/license files')
if __name__=='__main__':main()
