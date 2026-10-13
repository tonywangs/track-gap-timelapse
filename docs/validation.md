# Reproducible validation

The checked-in fixtures contain only invented coordinates. No GPX provider exports,
accounts, people, devices, or location services were used. The validation below
establishes behavior for this bounded synthetic workload, not provider compatibility
or real-world accuracy.

Run the complete suite after installing the verification-only tools as described
in the README:

```sh
TRACK_GAP_PLAYWRIGHT=/tmp/track-gap-tools/node_modules/playwright PLAYWRIGHT_BROWSERS_PATH=/tmp/track-gap-browsers python3 scripts/verify.py --browser
```

The command uses temporary directories and leaves the source tree unchanged.
Append `--write-results` to regenerate the evidence files. No downloads occur
during this command. Tool installation is a separate, online preparation step.

## Independence and coverage

`tests/fixtures.py` builds 320 deterministic cases using Python `random.Random`
seeds 0–319. Each has 1–4 participants, multiple segments, irregular timestamps,
timezone offsets, stationary pairs, missing times, and intervals exactly at or
above the configured gap threshold. A second 320 seeded variants must reject
identical or conflicting duplicate timestamps. Additional fixed tests cover
single observations, malformed XML, invalid dates, boundary behavior, source
hashes, and unsupported geographic extents.

The reference operates on the **original generated records**, before GPX parsing
or normalization. It linearly scans records and uses `fractions.Fraction` for
interpolation. It imports no production code. Production Python and JavaScript
use binary search over normalized observations and floating-point interpolation.
This structural difference helps catch normalization, continuity, and search
errors; agreement is not a mathematical proof and shared conceptual mistakes
remain possible.

For accepted seeded cases, tests compare normalized timestamps and coordinates
with the originals, then compare Python positions at observation times, interval
midpoints, and just outside each participant's observations. Chromium exercises
fixed times inside the combined timeline, including times outside individual
participants' observations. Outside the combined timeline, UI seeking is clamped;
Python's reference comparison also checks these outside instants.

Every thirteenth browser query also parses the generated SVG as XML. It checks
metadata, visible table values, timestamped captions, circle presence/status, and
projected circle coordinates against independently computed values. One SVG per
seed additionally checks **every path command and vertex** against source-record
continuity decisions, including half-millisecond reference midpoints where needed.
The test confirms that no connecting command crosses an unsupported interval.
Repeated frame serialization must be byte-identical. Browser JSON and SVG downloads
are real download events with inspected file contents, not merely clicked buttons.

The browser suite also exercises play/pause, speed changes, direct seeking,
invalid calendar input, slider arrow/Home keys, keyboard checkbox activation,
participant filtering, empty selection, observation jumps, singleton controls,
and a 360px viewport. A maximum-sized workload visits all 400 observation pages;
20,000 distinct participant/time records must be reachable while at most 50
observation rows remain mounted. A maximum-sized SVG download is parsed too.

Browser contexts are set offline and intercept all requests: local `file:` loads
are permitted, all other requests are counted and aborted. The HTML also contains
a restrictive CSP, including `connect-src 'none'`. The installed-CLI example runs
from outside the checkout under Python `-I`, with an audit hook rejecting
`socket.*` and `urllib.*` events. Runtime code uses only standard-library modules
and never constructs a network client. These checks are not a general-purpose
operating-system network sandbox or a browser security audit.

## Failure behavior

The standard-library suite tests DTD/external-entity declarations (including
UTF-16), malformed XML, oversized/deep inputs, hostile aliases, duplicate manifest
keys, regular-file enforcement, invalid bounds, output limits, and collision
handling. Fault injection covers serialization, fsync, and publication failures.
Real signals exercise cancellation before output, during directory ownership
transitions, and after one file has been published. A short real POSIX timer
exercises the same runtime-expiry handler as the 60-second limit. Failure tests
assert that owned output/staging directories are removed and competing outputs
are preserved. SIGKILL, power loss, and an unusable filesystem remain outside
that cleanup guarantee.

During development, the first browser test harness incorrectly aborted local
`file:` navigation and failed before the app loaded. The harness was corrected to
allow local documents while continuing to block external networking. That failed
attempt is not counted as a passing browser test. Review also identified and fixed
an installed-CLI exit-code issue and a cancellation ownership race; regressions
cover both. No negative provider-compatibility result is implied because provider
data was not tested.

## Recorded evidence

- [tests.log](../results/tests.log): actual output from 17 standard-library tests,
  including both 320-case seeded sets and failure-path checks.
- [browser.json](../results/browser.json): exact browser and Playwright versions,
  comparison counts, mounted rows, DOM count, maximum SVG size, workload reachability,
  observed page errors/requests, and elapsed time.
- [measurements.json](../results/measurements.json): actual platform/Python version,
  per-run CLI runtime, peak child-process RSS, output byte counts, and SHA-256 hashes.

The CLI measurements use an isolated installed archive in a fresh subprocess.
Linux `wait4` reports that CLI process's peak RSS in KiB, not the verifier or browser
process tree. Time includes process launch, parsing, serialization, filesystem
writes/fsync, and exit. Two runs are recorded for the 14-observation example and
the 20,000-observation bound. All output hashes must match across the pair. Fixture
generation and browser checks are outside the measured CLI interval. Runtime and
RSS vary with machine load and filesystem behavior; this is a bounded smoke
measurement, not a statistically powered benchmark.

The browser result records 320 accepted cases, 26,972 queried instants, 83,059
position comparisons, and 2,205 SVG frame comparisons. The large workload keeps
50 observation rows mounted, reaches all 20,000 observations, and uses 477 DOM
elements at the measured final page. Exact runtimes and output hashes are in the
machine-readable evidence rather than treated as stable performance promises.

## Remaining limits

No human usability study, screen-reader audit, other-browser test, macOS run,
provider compatibility study, geodesic error study, or real-location experiment
was performed. Low-powered devices may struggle with all observations held in
memory or drawn on a canvas. The strict input policy intentionally rejects some
otherwise valid GPX 1.1 files. Dashed interpolation is an assumption even when
reference arithmetic and browser output agree exactly. There are no map tiles,
terrain context, distance/speed inference, or video encoding.
