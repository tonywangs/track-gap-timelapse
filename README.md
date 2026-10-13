# Track / Gap

An offline GPX timelapse builder that makes missing evidence visible. Generate a
self-contained player from explicitly listed, synthetic tracks; compare participants
at the same UTC instant; export the normalized timeline or the selected frame.

**Filled marker = observation. Ring = interpolation. No marker = unknown.**
Dashed connections are possible interpolations, never a recorded route.

## Run the complete example

Requires Python 3.10+ on Linux or macOS. No runtime packages, account, basemap,
server, or network connection is needed. Inputs in `examples/` are invented;
they do not describe a person's movements.

```sh
python3 -m track_gap examples/manifest.json /tmp/my-track-replay --max-gap-ms 60000
```

Open `/tmp/my-track-replay/timelapse.html` locally in Chromium. Select participants,
play or pause, change speed, drag the time slider, or enter an exact UTC timestamp.
Use Previous / Next observation to jump directly to measurements. The observation
table has 50 rows per page and a page-number control. All records remain reachable.

The output directory must not exist. It contains:

- `timelapse.html`: standalone player, with all scripts/styles/data embedded and a restrictive content security policy.
- `timeline.json`: deterministic, versioned observations, gaps, diagnostics, and source hashes.
- `SHA256SUMS`: SHA-256 checksums of the two artifacts.

“Download timeline JSON” exports every participant, regardless of the current
filter. “Download selected frame SVG” exports the exact current time and selected
participants, including machine-readable positions and unknown reasons. Exports
are deterministic for the same input and selection. JSON downloaded from HTML uses
HTML-safe escapes; parsed values match the CLI JSON, but hostile text can make its
bytes differ. SVG is a static coordinate plot, not a video or basemap.

## Install offline

This creates an isolated executable zipapp, using only Python's standard library:

```sh
python3 scripts/install.py /tmp/track-gap
cd /tmp
./track-gap /absolute/path/to/examples/manifest.json /tmp/installed-replay
```

The destination must be new, its parent must exist, and Python 3.10+ must remain
available on `PATH`. Source checkout and package managers are unnecessary after
installation. `python3 /tmp/track-gap ...` also works. Remove that one executable
to uninstall. Windows is not supported by the signal-based runtime guard.

## Input manifest

```json
{
  "version": 1,
  "synthetic": true,
  "tracks": [
    {"alias": "Cedar (synthetic)", "file": "track-0.gpx"},
    {"alias": "Amber (synthetic)", "file": "track-1.gpx"}
  ]
}
```

Paths resolve relative to the manifest, including explicitly named absolute local
paths. No directory scanning, URLs, linked resources, or personal accounts are
used. Each file becomes one participant; its GPX tracks and segments remain
separate continuity runs. Aliases are unique and limited to 48 printable characters.
The `synthetic: true` declaration is mandatory for this milestone; it is an author's
assertion, not an automatic determination of whether data is real.

See [the frozen input and output contract](docs/format.md) for exact timestamp,
missing-data, projection, resource-limit, and provenance rules.

## Verify

One command runs the standard-library tests, 320 seeded independent reference
cases, an isolated installed example with network calls forbidden, and repeated
CLI measurements at the 20,000-point limit:

```sh
python3 scripts/verify.py
```

Node.js 18+ is needed for the JavaScript syntax check. For the full Chromium
workflow, install the **verification-only** tools once while online (no paid service):

```sh
npm --cache /tmp/track-gap-npm-cache install --prefix /tmp/track-gap-tools playwright@1.61.1
PLAYWRIGHT_BROWSERS_PATH=/tmp/track-gap-browsers node /tmp/track-gap-tools/node_modules/playwright/cli.js install chromium
TRACK_GAP_PLAYWRIGHT=/tmp/track-gap-tools/node_modules/playwright PLAYWRIGHT_BROWSERS_PATH=/tmp/track-gap-browsers python3 scripts/verify.py --browser
```

After installation, verification runs offline. It creates temporary fixtures,
blocks external browser requests, compares browser positions and SVG values with
a separate rational-arithmetic oracle, exercises downloads and controls, and
visits every observation page. Some Linux distributions require Chromium system
libraries to be installed by the system administrator. No runtime browser library
is bundled into the output. `--write-results` refreshes the reproducibility data
in `results/`; ordinary verification leaves the source tree unchanged.

See [validation and measured results](docs/validation.md) and
[prior work](docs/prior-work.md).

## Limits and consent

Interpolation assumes linear latitude/longitude change. It does not establish
route, actual location between observations, GPS accuracy, or distance traveled.
The local equirectangular plot is limited to latitude ±75° and an overall extent
of 10° on either axis; antimeridian-spanning inputs are rejected. It is not a
navigation tool. Coordinate tables remain the authoritative numerical display.

This milestone uses only reproducible synthetic fixtures. Synthetic tests do not
establish provider compatibility. Human usability, assistive-technology behavior,
macOS execution, and browsers other than the recorded Chromium version have not
been validated. Before using or extending this software for real location data,
obtain the participating people's informed consent for recording, processing,
and sharing. Aliases do not anonymize coordinates. HTML, JSON, and SVG may contain
all selected coordinates and should be handled accordingly.
