import unittest,struct,subprocess,os,tempfile
from pathlib import Path
from playlist_fixtures import chart

class PlaylistFixtures(unittest.TestCase):
    def test_short_fallback_has_a_valid_tap_in_every_format(self):
        with tempfile.TemporaryDirectory() as td:
            for version in [2,3,4]:
                p=Path(td)/'SHORT.RBG';b=chart('SHORT',version,18);p.write_bytes(b)
                self.assertEqual(struct.unpack_from('<H',b,10)[0],1)
                q=subprocess.run([os.environ['RAVE_LOADER_EXE'],str(p)],capture_output=True,text=True)
                self.assertEqual(q.returncode,0,q.stdout+q.stderr)

    def test_hit_and_miss_fixture_uses_twenty_two_original_taps(self):
        self.assertEqual(struct.unpack_from('<H',chart('LONG'),10)[0],22)
