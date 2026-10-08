"""Portable host QA; CI uses its existing GCC, local Windows uses existing Watcom."""
import argparse,subprocess,tempfile,os,sys,json,hashlib,re,unittest
from pathlib import Path
root=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--cc',default='gcc');args=p.parse_args()
manifest=json.loads((root/'SOURCE-PROVENANCE.json').read_text())
for name,sha in manifest['pins'].items():
 assert hashlib.sha256((root/name).read_bytes()).hexdigest()==sha,name
seen=set()
def closure(path):
 if path in seen:return
 seen.add(path)
 for inc in re.findall(r'^\s*#include\s*"([^"\n]+)"',path.read_text(),re.M):
  target=path.parent/inc.replace('\\','/')
  assert target.is_file(),f'missing include {target}'
  closure(target)
for f in (root/'src').glob('*.C'):closure(f)
with tempfile.TemporaryDirectory(prefix='rave-host-') as tmp:
 for name in ['ownership','edges']:
  out=Path(tmp)/(name+'.exe');source=root/'tests'/(name+'.c')
  if 'wcl386' in args.cc.lower():cmd=[args.cc,'-q','-bt=nt','-fe='+out.name,str(source)]
  else:cmd=[args.cc,'-std=c89','-Wall','-Wextra',str(source),'-o',str(out)]
  subprocess.run(cmd,cwd=tmp,check=True,capture_output=True)
  if name=='edges':subprocess.run([str(out)],check=True)
  else:os.environ['RAVE_CORE_EXE']=str(out)
 sys.path.insert(0,str(root/'tests'))
 suite=unittest.defaultTestLoader.discover(str(root/'tests'),pattern='test_*.py')
 result=unittest.TextTestRunner(verbosity=2).run(suite)
 if not result.wasSuccessful():sys.exit(1)
 # Exact production-core original playback: all hits and reference are identical.
 hit=subprocess.run([os.environ['RAVE_CORE_EXE'],str(root/'runtime/ORIGINAL.RBG'),'hit'],check=True,capture_output=True)
 ref=subprocess.run([os.environ['RAVE_CORE_EXE'],str(root/'runtime/ORIGINAL.RBG'),'ref'],check=True,capture_output=True)
 assert hit.stdout==ref.stdout and len(hit.stdout.splitlines())==256
 miss=subprocess.run([os.environ['RAVE_CORE_EXE'],str(root/'runtime/ORIGINAL.RBG'),'miss'],check=True,capture_output=True)
 assert len(miss.stdout.splitlines())==128
 print('PASS: pinned source/runtime, include closure, synthetic converter/retention tests, original 128-onset full lead and miss ownership')
