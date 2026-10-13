import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from track_gap import core
from track_gap.__main__ import build, main, render
from tests.fixtures import BASE, case, gpx, oracle, sample, write_manifest


class Workflow(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.manifest=sample(self.root/'input')

    def tearDown(self):
        self.temp.cleanup()

    def test_sample_deterministic_and_provenance(self):
        hashes=build(self.manifest,self.root/'a')
        self.assertEqual(hashes,build(self.manifest,self.root/'b'))
        data=json.loads((self.root/'a/timeline.json').read_text())
        for i,track in enumerate(data['tracks']):
            source=(self.manifest.parent/f'track-{i}.gpx').read_bytes()
            self.assertEqual(track['source']['sha256'],hashlib.sha256(source).hexdigest())
            self.assertEqual(track['source']['bytes'],len(source))
        self.assertEqual(data['manifest_sha256'],hashlib.sha256(self.manifest.read_bytes()).hexdigest())
        self.assertEqual({g['reason'] for g in data['tracks'][0]['gaps']},{'missing-time','segment','max-gap'})
        self.assertEqual(data['tracks'][0]['diagnostics'][0]['location']['point'],4)

    def test_320_independent_seeded_cases(self):
        for seed in range(320):
            sources,gap,times=case(seed)
            manifest=write_manifest(self.root/'cases',sources,offsets=[[-720,-330,0,345][i] for i in range(len(sources))])
            data=core.load(manifest,gap)
            for i,source in enumerate(sources):
                actual=data['tracks'][i]
                original=[p for seg in source for p in seg if p[0] is not None]
                self.assertEqual([(p['t'],p['lat'],p['lon']) for p in actual['points']],original)
                for t in times:
                    expected=oracle(source,t,gap)
                    observed=core.position(actual,t,gap)
                    self.assertEqual(observed['status'],expected['status'],(seed,i,t))
                    self.assertEqual(observed['reason'],expected['reason'],(seed,i,t))
                    for coordinate in ('lat','lon'):
                        if expected[coordinate] is None:
                            self.assertIsNone(observed[coordinate])
                        else:
                            self.assertAlmostEqual(observed[coordinate],expected[coordinate],places=11)

    def test_320_seeded_duplicate_rejections(self):
        for seed in range(320):
            sources,gap,_=case(seed)
            first=sources[0][0][0]
            second=sources[0][0][1]
            # Alternate identical records and conflicting coordinates at the same time.
            sources[0][0][1]=first if seed%2 else (first[0],second[1]+.001,second[2])
            manifest=write_manifest(self.root/'duplicates',sources)
            with self.assertRaisesRegex(core.InputError,'strictly increase'):
                core.load(manifest,gap)

    def test_cancel_during_directory_ownership_transitions(self):
        original=os.mkdir
        for target in ('staging','output'):
            def interrupted(path,*args,**kwargs):
                original(path,*args,**kwargs)
                name=Path(path).name
                if (target=='staging' and name.startswith('.track-gap-')) or (target=='output' and name=='cancel-ownership'):
                    os.kill(os.getpid(),signal.SIGTERM)
            with patch('track_gap.__main__.os.mkdir',side_effect=interrupted):
                self.assertEqual(main([str(self.manifest),str(self.root/'cancel-ownership')]),2)
            self.assertFalse((self.root/'cancel-ownership').exists())
            self.assertFalse(list(self.root.glob('.track-gap-*')))

    def test_cancel_after_partial_publication(self):
        original=os.replace
        calls=0
        def interrupted(source,destination):
            nonlocal calls
            calls+=1
            if calls==2:
                os.kill(os.getpid(),signal.SIGTERM)
            original(source,destination)
        with patch('track_gap.__main__.os.replace',side_effect=interrupted):
            self.assertEqual(main([str(self.manifest),str(self.root/'partial')]),2)
        self.assertEqual(calls,2)
        self.assertFalse((self.root/'partial').exists())
        self.assertFalse(list(self.root.glob('.track-gap-*')))

    def test_collisions_and_race(self):
        for kind in ('directory','file','symlink'):
            out=self.root/kind
            if kind=='directory':out.mkdir()
            elif kind=='file':out.write_text('keep')
            else:out.symlink_to(self.root/'nonexistent')
            with self.assertRaises(core.InputError):build(self.manifest,out)
            self.assertTrue(out.exists() or out.is_symlink())
        out=self.root/'race'
        real_mkdir=Path.mkdir
        def race(path,*a,**kw):
            if path==out:
                real_mkdir(path)
                (path/'owner').write_text('other process')
            return real_mkdir(path,*a,**kw)
        with patch.object(Path,'mkdir',race), self.assertRaises(FileExistsError):
            build(self.manifest,out)
        self.assertEqual((out/'owner').read_text(),'other process')
        self.assertFalse(list(self.root.glob('.track-gap-*')))

    def test_failure_cleanup(self):
        out=self.root/'out'
        for error in (OSError('disk error'),KeyboardInterrupt(),core.InputError('cancelled')):
            with patch('track_gap.__main__.os.replace',side_effect=error), self.assertRaises(type(error)):
                build(self.manifest,out)
            self.assertFalse(out.exists())
            self.assertFalse(list(self.root.glob('.track-gap-*')))
        with patch('track_gap.__main__.canonical',side_effect=ValueError('serialization failure')), self.assertRaises(ValueError):
            build(self.manifest,out)
        self.assertFalse(out.exists())
        with patch('track_gap.__main__.os.fsync',side_effect=OSError('disk full')), self.assertRaises(OSError):
            build(self.manifest,out)
        self.assertFalse(list(self.root.glob('.track-gap-*')))
        with patch('track_gap.__main__.MAX_OUTPUT_FILE',1), self.assertRaises(core.InputError):
            build(self.manifest,out)
        self.assertFalse(out.exists())

    def test_signal_cancellation_and_timeout(self):
        for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGALRM):
            def interrupted(*args):
                os.kill(os.getpid(),sig)
            with patch('track_gap.__main__.load',side_effect=interrupted):
                self.assertEqual(main([str(self.manifest),str(self.root/'cancel')]),2)
            self.assertFalse((self.root/'cancel').exists())
        def wait_for_alarm(*args):
            signal.pause()
        with patch('track_gap.__main__.RUNTIME_SECONDS',0.01),patch('track_gap.__main__.load',side_effect=wait_for_alarm):
            self.assertEqual(main([str(self.manifest),str(self.root/'timeout')]),2)

    def test_installed_cli_offline(self):
        app=self.root/'track-gap'
        subprocess.run([sys.executable,'scripts/install.py',str(app)],check=True,capture_output=True)
        env={'PATH':os.environ['PATH'],'PYTHONNOUSERSITE':'1'}
        result=subprocess.run([str(app),str(self.manifest),str(self.root/'installed')],cwd=self.root,env=env,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue((self.root/'installed/timelapse.html').exists())
        result=subprocess.run([str(app),str(self.manifest),str(self.root/'installed')],cwd=self.root,env=env,capture_output=True,text=True)
        self.assertEqual(result.returncode,2)

    def test_hostile_alias_is_data(self):
        manifest=json.loads(self.manifest.read_text())
        manifest['tracks'][0]['alias']='</script><img src=x onerror=alert(1)>'
        self.manifest.write_text(json.dumps(manifest))
        data=core.load(self.manifest)
        html=render(data)
        self.assertNotIn(manifest['tracks'][0]['alias'],html)
        self.assertIn('\\u003c/script\\u003e',html)
        self.assertEqual(html.count('<script'),2)


class InputContract(unittest.TestCase):
    def parse(self,value):
        return core.parse_gpx(value.encode() if isinstance(value,str) else value,0,[0])

    def doc(self,points=None):
        return gpx([points or [(BASE,35,-110),(BASE+10000,35.001,-109.999)]])

    def test_bad_xml_and_unsupported(self):
        valid=self.doc()
        bad=[valid[:-10],'<gpx/>',valid.replace('version="1.1"','version="1.0"'),
             valid.replace('creator="synthetic-test"',''),
             '<!DOCTYPE gpx [<!ENTITY x "abc">]>'+valid,
             '<!DOCTYPE gpx SYSTEM "file:///etc/passwd">'+valid,
             '<?fetch http://example.com?>'+valid,
             valid.replace('35.001','NaN'),valid.replace('35.001','1e2'),
             valid.replace('35.001','76'),valid.replace('-109.999','180'),
             valid.replace('<time>','<time><nested/>',1),
             valid.replace('</time>','</time><time>2025-01-01T12:00:00Z</time>',1),
             valid.replace('xmlns="http://www.topografix.com/GPX/1/1"','xmlns="http://example.com"'),
             self.doc([(BASE,35,-110),(BASE,35,-110)]),
             self.doc([(BASE,35,-110),(BASE-1,35,-110)]),
             '<gpx xmlns="http://www.topografix.com/GPX/1/1" version="1.1" creator="x"><trkpt lat="0" lon="0"/></gpx>',
             self.doc().replace('<trk>', '<metadata>'+'<x>'*33+'</x>'*33+'</metadata><trk>')]
        for value in bad:
            with self.subTest(value=value[:100]),self.assertRaises(core.InputError):self.parse(value)
        # UTF-16 encodings cannot bypass DTD rejection.
        with self.assertRaises(core.InputError):self.parse(('<!DOCTYPE gpx>'+valid).encode('utf-16'))

    def test_times(self):
        self.assertEqual(core.timestamp('2025-01-01T17:30:00+05:30'),BASE)
        self.assertEqual(core.timestamp('2025-01-01T06:15:00-05:45'),BASE)
        for value in ('2025-01-01T12:00:00','2025-02-30T12:00:00Z','2025-01-01T12:00:60Z','2025-01-01T12:00:00.0001Z','2025-01-01T12:00:00+14:01','2025-01-01T12:00:00+01:60','1969-12-31T23:59:59Z','2101-01-01T00:00:00Z'):
            with self.subTest(value=value),self.assertRaises(core.InputError):core.timestamp(value)

    def test_missing_time_does_not_bridge(self):
        points,diagnostics,_=self.parse(self.doc([(BASE,35,-110),(None,35,-110),(BASE+1,35,-110)]))
        self.assertNotEqual(points[0]['run'],points[1]['run'])
        self.assertEqual(len(diagnostics),1)
        self.assertEqual(points[1]['break_before'],'missing-time')
        with self.assertRaises(core.InputError):self.parse(gpx([[(None,35,-110)]]))

    def test_threshold_stationary_and_segment_endpoints(self):
        points,_,_=self.parse(gpx([[(BASE,35,-110),(BASE+1000,35,-110)],[(BASE+2000,35,-110)]]))
        tr={'points':points}
        self.assertEqual(core.position(tr,BASE+500,1000)['status'],'interpolated')
        self.assertEqual(core.position(tr,BASE+500,999)['reason'],'max-gap')
        self.assertEqual(core.position(tr,BASE+1500,10000)['reason'],'segment')
        for t in (BASE,BASE+1000,BASE+2000):self.assertEqual(core.position(tr,t,1)['status'],'observed')

    def test_ignored_metadata_extensions_never_imported(self):
        xml=self.doc().replace('<trk>', '<metadata><name>SECRET</name><link href="https://example.com/private"/><time>garbage</time></metadata><extensions><trk xmlns="urn:foreign"><trkpt>SECRET</trkpt></trk></extensions><trk>')
        result=self.parse(xml)
        self.assertNotIn('SECRET',core.canonical(result))
        self.assertGreater(result[2],0)

    def test_work_limits(self):
        with patch.object(core,'MAX_POINTS',1),self.assertRaises(core.InputError):self.parse(self.doc())
        with patch.object(core,'MAX_ELEMENTS',2),self.assertRaises(core.InputError):self.parse(self.doc())
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            manifest=sample(root)
            for setting in ('MAX_FILES','MAX_FILE_BYTES','MAX_TOTAL_BYTES','MAX_MANIFEST_BYTES'):
                with patch.object(core,setting,1),self.assertRaises(core.InputError):core.load(manifest)
            fifo=root/'fifo';os.mkfifo(fifo)
            with self.assertRaises(core.InputError):core.read_regular(fifo,100)
            for points,message in (([(BASE,0,-179),(BASE+1,0,179)],'antimeridian'), ([(BASE,0,0),(BASE+1,11,0)],'extent'), ([(BASE,0,0),(BASE+core.MAX_SPAN_MS+1,0,0)],'31 days')):
                manifest=write_manifest(root,[ [points] ])
                with self.assertRaisesRegex(core.InputError,message):core.load(manifest)

    def test_manifest_contract(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);m=sample(root)
            original=json.loads(m.read_text())
            for value in ([],{},dict(original,version=True),dict(original,synthetic=False),dict(original,tracks=[]),dict(original,extra=1),dict(original,tracks=[{'file':'x','alias':''}]),dict(original,tracks=original['tracks']*2)):
                m.write_text(json.dumps(value))
                with self.assertRaises(core.InputError):core.load(m)
            m.write_text('{"version":1,"version":1}')
            with self.assertRaises(core.InputError):core.load(m)
            m.write_text(json.dumps(original))
            for gap in (0,-1,86400001,True,1.1):
                with self.assertRaises(core.InputError):core.load(m,gap)


if __name__=='__main__':unittest.main()
