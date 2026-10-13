#!/usr/bin/env python3
"""One reproducible verification entry point. All fixture/output work is temporary."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.prepare_browser import prepare
from tests.fixtures import BASE, sample, write_manifest


def command(args, **kwargs):
    print('+ '+' '.join(map(str,args)),flush=True)
    subprocess.run(list(map(str,args)),check=True,cwd=ROOT,timeout=900,**kwargs)


def measured_cli(app,manifest,output):
    """Measure each CLI in a fresh worker; wait4 rusage is this child only."""
    worker='''import json, os, subprocess, sys, time
start=time.perf_counter()
p=subprocess.Popen(sys.argv[1:],stdout=subprocess.DEVNULL)
_,status,usage=os.wait4(p.pid,0)
p.returncode=os.waitstatus_to_exitcode(status)
print(json.dumps({"seconds":round(time.perf_counter()-start,6),"peak_rss_kib":usage.ru_maxrss,"exit_code":p.returncode}))
raise SystemExit(p.returncode)
'''
    result=subprocess.run([sys.executable,'-c',worker,sys.executable,'-I',str(app),str(manifest),str(output)],capture_output=True,text=True,check=True)
    measurement=json.loads(result.stdout)
    measurement['files']={p.name:{'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(output.iterdir())}
    return measurement


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser',action='store_true',help='also run all Chromium checks; requires separately installed Playwright and Chromium')
    parser.add_argument('--write-results',action='store_true',help='refresh normal reproducibility evidence in results/')
    args=parser.parse_args()
    if args.write_results:
        completed=subprocess.run([sys.executable,'-m','unittest','-v'],cwd=ROOT,capture_output=True,text=True,timeout=900)
        log=completed.stdout+completed.stderr
        (ROOT/'results/tests.log').write_text(log)
        print(log,flush=True)
        completed.check_returncode()
    else:
        command([sys.executable,'-m','unittest','-v'])
    command(['node','--check','track_gap/player.js'])
    with tempfile.TemporaryDirectory(prefix='track-gap-verify-') as temp:
        root=Path(temp)
        app=root/'track-gap'
        command([sys.executable,'scripts/install.py',app])
        manifest=sample(root/'sample-input')
        # Run installed archive with socket creation forbidden by a Python audit hook.
        # -I isolates this child from source checkout, PYTHONPATH, and user packages.
        audit='''import runpy,sys
app=sys.argv.pop(1)
def deny(event,args):
    if event.startswith("socket.") or event.startswith("urllib."):
        raise RuntimeError("network forbidden during installed example")
sys.addaudithook(deny)
runpy.run_path(app,run_name="__main__")
'''
        subprocess.run([sys.executable,'-I','-c',audit,str(app),str(manifest),str(root/'offline-installed')],cwd=root,check=True)
        measurements={}
        for name,count in [('sample',14),('maximum',20000)]:
            if name=='maximum':
                sources=[ [[(BASE+i*1000,35+((i+shift)%100)*.00001,-110+(i//100)*.00001) for i in range(10000)]] for shift in (0,20)]
                manifest=write_manifest(root/'maximum-input',sources)
            runs=[measured_cli(app,manifest,root/f'{name}-{i}') for i in range(2)]
            assert runs[0]['files']==runs[1]['files'],'nondeterministic output'
            measurements[name]={'timestamped_points':count,'runs':runs,'repeated_output_hashes_match':True}
        report={'python':sys.version,'platform':platform.platform(),'rss_unit':'KiB (Linux wait4 ru_maxrss; CLI process only)','installed_example_network_audit':'passed; socket.* and urllib.* events forbidden','workloads':measurements}
        if args.browser:
            fixtures=root/'browser'
            prepare(fixtures)
            browser_result=root/'browser.json'
            command(['node','tests/browser.cjs',fixtures,browser_result])
            if args.write_results:
                shutil.copyfile(browser_result,ROOT/'results/browser.json')
        if args.write_results:
            (ROOT/'results/measurements.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report,indent=2))
    print('Verification passed'+(' (including Chromium).' if args.browser else ' (Chromium not requested).'))


if __name__=='__main__':main()
