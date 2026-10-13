#!/usr/bin/env python3
"""Create an isolated stdlib-only zipapp. No package manager or network needed."""
import argparse
import os
from pathlib import Path
import shutil
import tempfile
import zipapp


def install(destination):
    destination=Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError('destination already exists')
    with tempfile.TemporaryDirectory(prefix='.track-gap-install-',dir=destination.parent) as temp:
        source_tree=Path(temp)/'source'
        package=source_tree/'track_gap'
        package.mkdir(parents=True)
        source=Path(__file__).resolve().parents[1]/'track_gap'
        for name in ('__init__.py','__main__.py','core.py','player.html','player.js'):
            shutil.copyfile(source/name,package/name)
        (source_tree/'__main__.py').write_text('from track_gap.__main__ import main\nraise SystemExit(main())\n')
        artifact=Path(temp)/'application'
        zipapp.create_archive(source_tree,artifact,interpreter='/usr/bin/env python3')
        artifact.chmod(0o755)
        # Same-filesystem hard link publishes only a complete executable and
        # fails atomically if another process created the destination.
        os.link(artifact,destination)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination',type=Path,help='new executable path in an existing directory')
    args=parser.parse_args()
    try:
        install(args.destination)
    except OSError as exc:
        parser.error(str(exc))
    print(args.destination)
