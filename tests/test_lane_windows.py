import unittest,sys
from pathlib import Path
from fractions import Fraction as F
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from chart_policy import separate_lane_windows
class LaneWindows(unittest.TestCase):
 def test_same_lane_late_tap_cannot_steal_next_required(self):
  ns=[dict(start=F(t),end=F(t+4),note=64) for t in [0,5,10,15,20]]
  selected=separate_lane_windows(ns,set(range(5)),[(F(0),60)],F(1),int)
  self.assertTrue(selected)
  ticks=sorted(int(ns[i]['start']) for i in selected)
  self.assertTrue(all(b-a>=7 for a,b in zip(ticks,ticks[1:])))
 def test_other_lanes_do_not_needlessly_thin(self):
  ns=[dict(start=F(0),end=F(4),note=64),dict(start=F(5),end=F(9),note=65)]
  self.assertEqual(separate_lane_windows(ns,{0,1},[(F(0),60)],F(1),int),{0,1})
 def test_seven_ticks_are_safe_and_deterministic(self):
  ns=[dict(start=F(t),end=F(t+4),note=64) for t in [0,7,14]]
  for _ in range(3):self.assertEqual(separate_lane_windows(ns,{0,1,2},[(F(0),60)],F(1),int),{0,1,2})
if __name__=='__main__':unittest.main(verbosity=2)
