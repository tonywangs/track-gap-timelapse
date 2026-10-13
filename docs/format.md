# Input and output contract · version 1

This is a deliberately restricted playback interpretation of GPX 1.1, **not a full
XSD validator**. The root must have the GPX 1.1 namespace, `version="1.1"`, and a
nonempty `creator`. Only direct `gpx/trk/trkseg/trkpt` children are observations.
Track segments are traversed in document order. The GPX specification's segment
boundary represents lost reception or a receiver being off; it must never be
silently bridged. Schema locations and links are never fetched.

## Time and missing evidence

- A point's latitude and longitude must be finite decimal values. Scientific
  notation is outside this subset. Latitude is restricted to [-75, 75], longitude
  to [-180, 180). Bad coordinates are rejected even on points without a time.
- A direct `time` child must use `YYYY-MM-DDTHH:MM:SS[.sss]Z` or an explicit
  `±HH:MM` offset. One to three fractional digits are accepted. Offsets must be
  within ±14:00. Times normalize exactly to integer Unix milliseconds in UTC.
  UTC years 1970–2100 inclusive are supported. Leap seconds, naive times,
  overprecision, multiple time children, and invalid dates are rejected.
- Timestamped observations must strictly increase throughout each source file,
  including across tracks/segments. Duplicate times (even identical positions),
  reversed observations, and overlapping segments are rejected with source index,
  XML line, and zero-based column. No sorting or deduplication conceals ambiguity.
  Different participants may have simultaneous times.
- A missing `time` discards that point from the replay, records a `missing-time`
  diagnostic, and breaks continuity. A valid time that cannot be parsed is an
  error, not a missing-time diagnostic. Leading/trailing missing-time points
  create diagnostics but no invented interval.
- An exact observation time is always **observed**, including endpoints of gaps.
- An interior time between adjacent observations is **interpolated** only if
  they belong to the same continuity run and their separation is **at most**
  `max_gap_ms`. Linear interpolation is performed independently on latitude
  and longitude. Stationary pairs remain interpolated between observations.
- Otherwise the position is **unknown**, with `lat:null`, `lon:null` and a reason:
  `missing-time`, `segment`, `max-gap`, or `outside-observations`. No last-known
  position is carried forward. Segment/missing-time breaks take priority over
  the gap-duration limit. A new explicit segment supersedes an earlier
  missing-time break. Unknown gap intervals have open endpoints.
- All of a source's timestamped observations may fit in one instant. In this case
  the player disables seeking and playback; the single observation is still
  exportable. A source with no timestamped observations is rejected.

Non-playback GPX metadata, names, links, elevations, routes, waypoints, and extension
subtrees are discarded. Their elements are counted in `ignored_elements`; no
extension affects time, coordinates, or continuity. Misplaced structural GPX
children outside ignored metadata/route/waypoint/extension subtrees are rejected.
The importer does not validate ignored content against the GPX schema. DTDs,
entity declarations, and processing instructions are rejected, including when
encoded as UTF-16. Predefined XML escapes such as `&amp;` remain ordinary text.
No external-entity handler resolves anything.

## Bounds and computation

| Resource | Hard limit |
| --- | --- |
| Manifest | 64 KiB, 1–16 files, exact known fields, no duplicate JSON keys |
| Input GPX | 4 MiB per file, 16 MiB combined |
| Point count | 20,000 total, including points discarded for missing time |
| XML structure | 200,000 elements per file; depth 32 |
| Point coordinate text / time text | 40 characters per coordinate; 64 per time |
| Total UTC span | 31 days, inclusive |
| Maximum interpolation gap setting | 1–86,400,000 ms; default 60,000 ms |
| Geography | Latitude ±75°; ≤10° combined extent per axis; no antimeridian crossing |
| CLI runtime | 60 seconds wall time, enforced by POSIX timer |
| Output | 8 MiB per artifact; 20 MiB combined data artifacts |
| Browser mounted observations | 50; position table at most 16 participants |
| Browser computation | ≤20,000 observations, ≤16 participants; no resampled frame array |
| Browser redraw | At most approximately 15 Hz during playback; pauses when tab hidden |
| Browser downloaded file | 8 MiB |

All file inputs must be regular local files. Symlinks to regular local files are
allowed; duplicate resolved paths are rejected. No recursion, globbing, compressed
input, or network resource loader exists. The byte content actually read is hashed;
a file modified during reading is not promised to be a filesystem snapshot.

Parsing is a bounded streaming Expat pass; source bytes are retained only while
loading one source. Normalized points remain in memory. Browser position queries
use binary search; background drawing is bounded by the point count. Observation
pagination does not truncate data. The player retains all normalized observations
in memory even though it mounts only one page. It does not promise a frame-rate or
memory ceiling on all devices. The CLI has an enforced wall-time limit; other
resource bounds constrain work, not operating-system RSS. Browser navigation and
JavaScript scheduling are controlled by the browser, not a hard watchdog.

Output paths must not exist. Files are first serialized and written to a sibling
staging directory, then a destination directory is reserved with exclusive mkdir.
A collision, even with an empty existing directory or a dangling symlink, fails.
Handled failures/signals remove staging and the destination owned by this build;
they never remove a competing destination. Publication of the three files is not
a single atomic directory transaction: readers must wait for CLI success. SIGKILL,
power loss, or filesystem failures during cleanup can leave temporary or partial
outputs; these are not claimed to be successful builds. No overwrite mode exists.
Parent directories are not created implicitly. Do not let another process modify
a destination while it is being built.

## Normalized JSON

`format:"track-gap-timeline"`, `version:1`, and `synthetic:true` identify the
contract. Top-level fields include UTC-millisecond `start`/`end`, geographic
`bounds`, `projection`, `max_gap_ms`, and the manifest's SHA-256. Each track has:

- zero-based stable `id`, manifest `alias`, source byte count and SHA-256;
- `points` in source order: `t`, `lat`, `lon`, continuity `run`, `break_before`,
  and XML `location` with one-based GPX track/segment/point ordinals and line;
- `gaps`, with open-interval `start`/`end` and `reason`;
- missing-time `diagnostics`, with location; ignored-element count.

`break_before` matters only when the continuity run changes; within a run it is
not evidence of a gap. Full paths, creator, imported names, timestamps of file
modification, and other unnecessary imported metadata are absent. The hashes
identify exact source bytes, not the person or trustworthiness of a file.

CLI JSON uses sorted object keys, compact separators, ASCII escapes, no NaN or
Infinity, and one final LF. Generation uses no current time or randomness. Source
formatting changes hashes and diagnostics even when coordinates remain equal.
HTML embeds safely escaped JSON and a SHA-256-authorized inline player script.
The downloaded JSON has the same values but retains the HTML-safe character
escapes. Existing v1 files do not depend on a future package installation.

## Projection and SVG

This is a local equirectangular coordinate plot, without a basemap. Let φ₀ and λ₀
be the midpoint of the global latitude and longitude bounds, in degrees, and
`c = cos(φ₀ · π/180)`. In the 900×500 plot:

```
s = min(760 / max((east-west)*c, 0.0001),
        340 / max(north-south, 0.0001))
x = 450 + (longitude-λ₀)*c*s
y = 250 - (latitude-φ₀)*s
```

North is up and east is right; scale is uniform in these local angular
coordinates. The small extent floor handles stationary/single-point datasets.
This is not an ellipsoidal or geodesic calculation. Wide extents and polar and
antimeridian cases are rejected rather than wrapped or projected misleadingly.

SVG uses the same fixed global bounds regardless of filtering, preserving context
between frames. It contains the UTC time, coordinate orientation, maximum gap,
legend, selected participants' numerical positions/status/reasons, and XML-escaped
`metadata` JSON (`format:"track-gap-frame"`, `version:1`), including the manifest
and selected source hashes. Unknown positions have
no circle. Dashed paths connect only permitted interpolation intervals. Current
marker coordinates are rounded to six plot-space decimals; metadata retains
numeric coordinate precision. Text coordinates display six decimal degrees;
this is display precision, not a statement of GPS accuracy. Repeated exports at
the same instant with the same selected participants are byte-identical in the
tested browser. SVG byte identity across browser engines is unvalidated.
