import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import fetch_midi_list as f
class FetchMidiList(unittest.TestCase):
 def test_pairs_need_safe_name_and_http_url(self):
  self.assertEqual(f.parse_pair('tune=https://example.org/a.mid'),('tune','https://example.org/a.mid'))
  for bad in ('noequals','=https://x/a.mid','../evil=https://x/a.mid','a b=https://x/a.mid','tune=file:///etc/passwd','tune=ftp://x/a.mid'):
   with self.subTest(bad=bad):
    with self.assertRaises(ValueError):f.parse_pair(bad)
 def test_payload_must_be_midi_and_bounded(self):
  self.assertEqual(f.check_midi(b'MThd'+b'\0'*10,100),b'MThd'+b'\0'*10)
  with self.assertRaisesRegex(ValueError,'MThd'):f.check_midi(b'<html>',100)
  with self.assertRaisesRegex(ValueError,'limit'):f.check_midi(b'MThd'+b'\0'*200,100)
 def test_defaults_are_named_http_pairs(self):
  names=[n for n,_ in f.DEFAULTS]
  self.assertEqual(len(names),len(set(names)))
  for n,u in f.DEFAULTS:f.parse_pair(f'{n}={u}')
 def test_page_html_resolves_to_direct_midi_link(self):
  html='<a class="x" href="/uploads/16633.mid" download="Stayin.mid">Download</a>'
  self.assertEqual(f.midi_link_from_html(html,'https://bitmidi.com/bee-gees-stayin-alive-mid'),'https://bitmidi.com/uploads/16633.mid')
  self.assertIsNone(f.midi_link_from_html('<p>nothing</p>','https://x.org/'))
  self.assertEqual(f.resolve_midi_url('https://x.org/a/b.MID'),'https://x.org/a/b.MID')
 def test_unknown_only_name_and_bad_pair_exit_nonzero(self):
  self.assertEqual(f.main(['--list-only','--only','nope']),2)
  self.assertEqual(f.main(['bad']),2)
if __name__=='__main__':unittest.main()
