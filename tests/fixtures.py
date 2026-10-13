"""Synthetic generator + independent linear-scan oracle (no production imports)."""
from datetime import datetime, timezone, timedelta
from fractions import Fraction
import json
from pathlib import Path
import random

BASE = 1735732800000  # 2025-01-01T12:00:00Z
NS = 'http://www.topografix.com/GPX/1/1'


def stamp(t, offset=0):
    return datetime.fromtimestamp(t/1000, timezone(timedelta(minutes=offset))).isoformat(timespec='milliseconds')


def gpx(segments, offset=0, extra=''):
    chunks = [f'<gpx xmlns="{NS}" version="1.1" creator="synthetic-test">', extra, '<trk>']
    for segment in segments:
        chunks.append('<trkseg>')
        for p in segment:
            chunks.append(f'<trkpt lat="{p[1]}" lon="{p[2]}">')
            if p[0] is not None:
                chunks.append(f'<time>{stamp(p[0], offset)}</time>')
            chunks.append('</trkpt>')
        chunks.append('</trkseg>')
    return '\n'.join(chunks + ['</trk></gpx>'])


def write_manifest(root, sources, aliases=None, offsets=None):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    entries=[]
    for i, segments in enumerate(sources):
        name=f'track-{i}.gpx'
        (root/name).write_text(gpx(segments, (offsets or [0]*len(sources))[i]), encoding='utf-8')
        entries.append({'alias': (aliases or [f'Walker {j+1}' for j in range(len(sources))])[i], 'file':name})
    (root/'manifest.json').write_text(json.dumps({'version':1,'synthetic':True,'tracks':entries}, indent=2)+'\n')
    return root/'manifest.json'


def oracle(segments, time, gap):
    """Linear scan over original records; exact rational interpolation."""
    before=None
    boundary='segment'
    for segment in segments:
        boundary='segment'
        for t, lat, lon in segment:
            if t is None:
                boundary='missing-time'
                continue
            if t==time:
                return {'status':'observed','lat':lat,'lon':lon,'reason':None}
            if t>time:
                if before is None:
                    return {'status':'unknown','lat':None,'lon':None,'reason':'outside-observations'}
                a, alat, alon=before
                reason=boundary or ('max-gap' if t-a>gap else None)
                if reason:
                    return {'status':'unknown','lat':None,'lon':None,'reason':reason}
                f=Fraction(time-a,t-a)
                return {'status':'interpolated','lat':float(Fraction(str(alat))*(1-f)+Fraction(str(lat))*f),
                        'lon':float(Fraction(str(alon))*(1-f)+Fraction(str(lon))*f),'reason':None}
            before=(t,lat,lon)
            boundary=None
    return {'status':'unknown','lat':None,'lon':None,'reason':'outside-observations'}


def case(seed):
    rng=random.Random(seed)
    gap=rng.choice([1000,10000,30000,60000])
    tracks=[]
    for track in range(1+seed%4):
        segments=[]
        t=BASE+rng.choice([0,0,1000,5000])
        lat,lon=round(35+rng.random()/10,6),round(-110+rng.random()/10,6)
        for segment in range(2+seed%2):
            records=[]
            for point in range(8):
                t+=rng.choice([1,100,999,gap,gap+1,2*gap])
                if point%3:
                    lat=round(lat+rng.uniform(-.001,.001),6)
                    lon=round(lon+rng.uniform(-.001,.001),6)
                records.append((None if point==4 else t,lat,lon))
            segments.append(records)
            t+=rng.choice([1,100,gap*2])
        tracks.append(segments)
    times=set()
    for segments in tracks:
        ps=[p for seg in segments for p in seg if p[0] is not None]
        times.update(p[0] for p in ps)
        times.update((a[0]+b[0])//2 for a,b in zip(ps,ps[1:]))
        times.update([ps[0][0]-1,ps[-1][0]+1])
    return tracks,gap,sorted(times)


def sample(root):
    # Completely invented coordinates; no person's path is represented.
    tracks=[[
        [(BASE,35,-110),(BASE+10000,35.001,-109.999),(BASE+30000,35.002,-109.998),
         (None,35.003,-109.997),(BASE+50000,35.004,-109.996),(BASE+60000,35.004,-109.996)],
        [(BASE+80000,35.003,-109.995),(BASE+90000,35.002,-109.994),(BASE+180000,35.001,-109.993)]
    ],[
        [(BASE+5000,35.005,-109.997),(BASE+20000,35.004,-109.996),(BASE+35000,35.003,-109.995),
         (BASE+50000,35.002,-109.994),(BASE+65000,35.001,-109.993),(BASE+80000,35,-109.992)]
    ]]
    return write_manifest(root,tracks,['Cedar (synthetic)','Amber (synthetic)'],[0,330])


if __name__=='__main__':
    import sys
    sample(Path(sys.argv[1]))
