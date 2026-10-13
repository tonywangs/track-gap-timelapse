#!/usr/bin/env python3
"""Generate bounded browser fixtures and oracle answers, never public location data."""
import argparse
from fractions import Fraction
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from track_gap.__main__ import build
from tests.fixtures import BASE, case, oracle, sample, write_manifest


def prepare(root):
    root=Path(root)
    root.mkdir(parents=True,exist_ok=True)
    manifest=sample(root/'sample-input')
    build(manifest,root/'sample')
    records=[]
    for seed in range(320):
        sources,gap,times=case(seed)
        manifest=write_manifest(root/'inputs',sources,offsets=[[-720,-330,0,345][i] for i in range(len(sources))])
        out=root/f'case-{seed:03}'
        build(manifest,out,gap)
        minimum=min(p[0] for s in sources for seg in s for p in seg if p[0] is not None)
        maximum=max(p[0] for s in sources for seg in s for p in seg if p[0] is not None)
        queries=[{'time':t,'positions':[dict(id=i,**oracle(source,t,gap)) for i,source in enumerate(sources)]} for t in times if minimum<=t<=maximum]
        paths=[]
        for source in sources:
            observations=[p for segment in source for p in segment if p[0] is not None]
            vertices=[]
            for index,p in enumerate(observations):
                connect=index>0 and oracle(source,Fraction(observations[index-1][0]+p[0],2),gap)['status']=='interpolated'
                vertices.append({'command':'L' if connect else 'M','lat':p[1],'lon':p[2]})
            paths.append(vertices)
        records.append({'seed':seed,'html':str(out.resolve()/'timelapse.html'),'queries':queries,'paths':paths})
    (root/'oracles.json').write_text(json.dumps(records,separators=(',',':'))+'\n')
    # Limit workload: 20,000 observations. Two participants with simultaneous data.
    sources=[ [[(BASE+i*1000,35+((i+shift)%100)*.00001,-110+(i//100)*.00001) for i in range(10000)]] for shift in (0,20)]
    manifest=write_manifest(root/'large-input',sources)
    build(manifest,root/'large')
    hostile=write_manifest(root/'hostile-input',[[[(BASE,35,-110),(BASE+10000,35.01,-110.01)]]],['</script><img src=x onerror=alert(1)>'])
    build(hostile,root/'hostile')
    one=write_manifest(root/'single-input',[[[(BASE,35,-110)]]])
    build(one,root/'single')
    print(json.dumps({'cases':320,'root':str(root.resolve())}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    prepare(parser.parse_args().directory)
