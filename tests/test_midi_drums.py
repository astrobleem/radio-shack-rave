"""Synthetic only: timing/velocity/noise reductions and actual payload roundtrip."""
import copy,json,sys,tempfile,unittest,wave
from fractions import Fraction as F
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import midi_to_mml as m
import midi_arrangement as a
import rave_workbench as w
import fetch_midi_list as fetch
from import_score import convert
from mml import CLOCK,rounded,ScoreError
from test_midi_to_mml import smf,midi_from_original

def fixture():
    data=smf([(0,[(i*96,i*96+96,60+i%4) for i in range(16)]),
              (1,[(0,768,48),(768,1536,50)]),
              (9,[(96,120,36),(96,120,38),(96,120,42),(192,216,38),(288,312,46)])])
    s=m.read_smf(data)
    return s,m.arrange(s,['1.1:top','2.2:bottom'],title='DRUM TEST',check=True)

class MidiDrums(unittest.TestCase):
    def test_reader_retains_channel10_onsets_and_velocities(self):
        s,r=fixture();drums=s[1][3]['attacks']
        self.assertEqual([(d['tick'],d['pitch'],d['velocity']) for d in drums],
                         [(96,36,90),(96,38,90),(96,42,90),(192,38,90),(288,46,90)])
        self.assertEqual(len(r['arrangement']['drums']),5)

    def test_delivered_binary_roundtrip_and_priority(self):
        _,r=fixture();blob,rep,_=a.convert_arrangement(r['arrangement']);report=json.loads(rep);score=a.decode_score(blob)
        self.assertEqual(score['version'],5);self.assertEqual(len(score['drums']),3)
        self.assertEqual(score['drums'][0],(rounded(F(1,2)*CLOCK),0,4))
        self.assertEqual(report['drums']['source_hits'],5)
        self.assertEqual(len(report['drums']['same_tick_collisions']),2)
        for hit,i in zip(score['drums'],report['drums']['kept_source_indices']):
            d=report['drums']['events'][i]
            self.assertEqual(hit,(d['native_tick'],a.DRUM_KINDS.index(d['kind']),d['attenuation']))
        self.assertTrue(all(abs(F(d['quantization_seconds']))<=F(1,2)/CLOCK for d in report['drums']['events']))

    def test_velocity_quantization_tie_break_and_source_preserved(self):
        _,r=fixture();side=r['arrangement'];side['drums']=[dict(tick=96,key=38,velocity=v,track=3) for v in (1,127,80)]
        blob,rep,_=a.convert_arrangement(side);j=json.loads(rep)
        self.assertEqual([e['velocity'] for e in j['drums']['events']],[1,127,80])
        self.assertEqual(a.decode_score(blob)['drums'],[(rounded(F(1,2)*CLOCK),1,0)])
        self.assertEqual(j['drums']['kept_source_indices'],[1])

    def test_exact_tempo_mapping_and_excerpt_origin(self):
        _,r=fixture();side=r['arrangement'];side['tempos']=[[0,500000],[384,1000000]]
        side['drums']=[dict(tick=480,key=36,velocity=100,track=3)]
        blob,rep,ev=a.convert_arrangement(side)
        self.assertEqual(json.loads(rep)['drums']['events'][0]['source_seconds'],'3')
        self.assertEqual(a.decode_score(blob)['drums'][0][0],rounded(3*CLOCK))
        self.assertEqual(a.clock_seconds(480,96,side['tempos']),3)
        self.assertEqual(a.clock_seconds(96,96,[[192,1000000]]),F(1,2))
        self.assertEqual(a.clock_seconds(480,96,side['tempos'])-a.clock_seconds(384,96,side['tempos']),1)

    def test_explicit_tempo_override_preserves_measured_ledger(self):
        _,r=fixture();side=r['arrangement'];side['tempos']=[[0,500000],[384,1000000]];side['tempo_override']=120
        side['drums']=[dict(tick=480,key=36,velocity=100,track=3)]
        _,rep,_=a.convert_arrangement(side);d=json.loads(rep)['drums']['events'][0]
        self.assertEqual(d['source_seconds'],'3');self.assertEqual(d['playback_seconds'],'5/2')

    def test_noninteger_tempo_preserved_in_actual_file(self):
        _,r=fixture();side=r['arrangement'];side['tempos']=[[0,465116]]
        _,rep,_=a.convert_arrangement(side)
        self.assertEqual(F(json.loads(rep)['seconds']),F(465116*16,1000000))

    def test_boundary_drum_is_retained_with_audited_tail(self):
        _,r=fixture();side=r['arrangement'];side['drums']=[dict(tick=1535,key=36,velocity=100,track=3)]
        blob,rep,_=a.convert_arrangement(side);j=json.loads(rep);s=a.decode_score(blob)
        self.assertEqual(len(s['drums']),1);self.assertLess(s['drums'][0][0],s['total'])
        self.assertEqual(j['native_tail_extension_ticks'],1);self.assertEqual(s['states'][-1][0],s['total'])

    def test_negative_drum_fields_and_unmapped_keys(self):
        _,r=fixture()
        for field,value in [('tick',-1),('tick',1536),('velocity',0),('velocity',128),('velocity','90'),
                            ('key',34),('key',128),('track',256),('track',True)]:
            side=copy.deepcopy(r['arrangement']);side['drums'][0][field]=value
            with self.subTest(field=field,value=value),self.assertRaises(ScoreError):a.convert_arrangement(side)
        for tempos in ([[0,0]],[[0,500000],[0,600000]],[[100,500000],[0,500000]]):
            side=copy.deepcopy(r['arrangement']);side['tempos']=tempos
            with self.assertRaises(ScoreError):a.convert_arrangement(side)

    def test_tone_selection_cannot_consume_percussion(self):
        s,_=fixture()
        with self.assertRaisesRegex(m.MidiError,'channel 10'):m.arrange(s,['3.10:top'])

    def test_original_tone_only_native_file_stays_exact(self):
        data,original=midi_from_original();s=m.read_smf(data)
        r=m.arrange(s,['1:top','2:bottom','3:top'],title='CIRCUIT AFTER HOURS')
        got=a.convert_arrangement(r['arrangement'])[0]
        want=convert(original,lead='1',parts=[1,2,3],difficulty='normal',title='CIRCUIT AFTER HOURS')[0]
        self.assertEqual(got,want)

    def test_sidecar_reimport_and_saved_drums_are_exact(self):
        _,r=fixture()
        with tempfile.TemporaryDirectory() as d:
            mml,rbg=w.save_outputs(r,d,'DRUM_TEST')
            delivered=json.loads(mml.with_suffix('.arrangement.json').read_text())
            self.assertEqual(a.convert_arrangement(delivered)[0],rbg.read_bytes())
            self.assertEqual(len(delivered['drums']),5)

    def test_actual_native_noise_is_present_in_preview(self):
        _,r=fixture()
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'drums.wav';w.render_wav(r,p,rate=8000,max_seconds=10)
            with wave.open(str(p),'rb') as f:with_drums=f.readframes(f.getnframes())
            tone=copy.deepcopy(r);tone['arrangement']['drums']=[];w.render_wav(tone,p,rate=8000,max_seconds=10)
            with wave.open(str(p),'rb') as f:without=f.readframes(f.getnframes())
            self.assertNotEqual(with_drums,without)

    def test_native_payload_mutations_rejected(self):
        _,r=fixture();blob=a.convert_arrangement(r['arrangement'])[0]
        for bad in (blob[:-1],blob+b'X',blob[:3],b'BAD!'+blob[4:]):
            with self.assertRaises(ScoreError):a.decode_score(bad)
        changed=bytearray(blob);changed[-2]=7
        with self.assertRaises(ScoreError):a.decode_score(changed)

    def test_downloader_invalid_data_cannot_replace_good_file(self):
        with tempfile.TemporaryDirectory() as d:
            target=Path(d)/'tune'/'tune.mid';target.parent.mkdir();original=smf([(0,[(0,96,60)])]);target.write_bytes(original)
            with patch.object(fetch,'resolve_midi_url',return_value='https://example.org/tune.mid'),patch.object(fetch,'download',side_effect=ValueError('bad MIDI')):
                with self.assertRaises(ValueError):fetch.fetch_one('tune','https://example.org/tune.mid',d,1024,force=True)
            self.assertEqual(target.read_bytes(),original)
        for name in ['CON','nul','LPT1']:
            with self.assertRaises(ValueError):fetch.parse_pair(name+'=https://example.org/tune.mid')

    def test_unsupported_meter_changes_are_explicit(self):
        s,_=fixture();s[3].append((384,3,4))
        with self.assertRaisesRegex(m.MidiError,'meter changes'):m.arrange(s,['1:top'])

if __name__=='__main__':unittest.main()
