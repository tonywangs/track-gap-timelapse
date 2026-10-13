"""Conservative GPX subset, provenance, and deterministic timeline model."""
from __future__ import annotations

import bisect
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
from datetime import datetime, timezone
from xml.parsers import expat

NS = "http://www.topografix.com/GPX/1/1"
MAX_FILES = 16
MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024
MAX_POINTS = 20_000
MAX_ELEMENTS = 200_000
MAX_SPAN_MS = 31 * 86400 * 1000
MAX_MANIFEST_BYTES = 64 * 1024
TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?(?:Z|[+-]\d{2}:\d{2})\Z")
DECIMAL = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)\Z")


class InputError(ValueError):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"


def read_regular(path, limit):
    """Open nonblocking so a FIFO cannot stall validation. Follow local symlinks."""
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise InputError("input must be a regular local file")
        if info.st_size > limit:
            raise InputError(f"input exceeds {limit} bytes")
        data = stream.read(limit + 1)
        if len(data) > limit:
            raise InputError(f"input exceeds {limit} bytes")
        return data


def timestamp(value):
    if not TIME.fullmatch(value):
        raise InputError("time requires an explicit timezone and at most millisecond precision")
    # datetime accepts offsets that GPX/xsd:dateTime does not.
    if value[-1] != "Z":
        hh, mm = map(int, value[-5:].split(":"))
        if hh > 14 or mm > 59 or (hh == 14 and mm):
            raise InputError("timezone offset exceeds ±14:00")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (ValueError, OverflowError) as exc:
        raise InputError("invalid calendar time") from exc
    if not 1970 <= dt.year <= 2100:
        raise InputError("UTC time must be in years 1970 through 2100")
    delta = dt - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return delta.days * 86400000 + delta.seconds * 1000 + delta.microseconds // 1000


def utc(t):
    return datetime.fromtimestamp(t / 1000, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_gpx(data, source, budget):
    """Streaming Expat parser. Never resolves external resources or retains metadata."""
    parser = expat.ParserCreate(namespace_separator="|")
    stack = []
    points, diagnostics = [], []
    current = None
    time_text = []
    trk = seg = point_index = run = elements = 0
    last_t = None
    break_reason = "segment"
    ignored = 0

    def fail(message):
        raise InputError(f"source {source}, line {parser.CurrentLineNumber}, column {parser.CurrentColumnNumber}: {message}")

    def start(name, attrs):
        nonlocal trk, seg, point_index, run, current, elements, ignored, break_reason
        elements += 1
        if elements > MAX_ELEMENTS or len(stack) >= 32:
            fail("XML element/depth limit exceeded")
        stack.append(name)
        path = [f"{NS}|{x}" for x in ("gpx", "trk", "trkseg", "trkpt")]
        if len(stack) == 1:
            if name != path[0] or attrs.get("version") != "1.1" or not attrs.get("creator"):
                fail("requires GPX 1.1 namespace, version, and creator")
        elif stack == path[:2]:
            trk += 1
        elif stack == path[:3]:
            seg += 1
            point_index = 0
            run += 1
            break_reason = "segment"
        elif stack == path:
            point_index += 1
            budget[0] += 1
            if budget[0] > MAX_POINTS:
                fail("point-count limit exceeded")
            coords = []
            for key, limit in (("lat", 75), ("lon", 180)):
                value = attrs.get(key, "")
                if len(value) > 40 or not DECIMAL.fullmatch(value):
                    fail(f"invalid {key} decimal")
                num = float(value)
                if not math.isfinite(num) or abs(num) > limit or (key == "lon" and num == 180):
                    fail(f"unsupported {key}: latitude must be within ±75; longitude in [-180,180)")
                coords.append(num)
            current = {"lat": coords[0], "lon": coords[1], "run": run,
                       "location": {"line": parser.CurrentLineNumber, "column": parser.CurrentColumnNumber,
                                    "track": trk, "segment": seg, "point": point_index}, "times": 0}
        elif stack == path + [f"{NS}|time"]:
            current["times"] += 1
            time_text.clear()
        elif len(stack) > 5 and stack[:5] == path + [f"{NS}|time"]:
            fail("time must contain text only")
        elif name in (f"{NS}|trk", f"{NS}|trkseg", f"{NS}|trkpt", f"{NS}|time"):
            # GPX metadata/time is allowed but has no playback meaning.
            if not any(x.endswith("|extensions") or x.endswith("|metadata") or x.endswith("|wpt") or x.endswith("|rte") for x in stack[:-1]):
                fail("misplaced structural GPX element")
        if len(stack) > 1 and stack != path[:len(stack)] and stack != path + [f"{NS}|time"]:
            ignored += 1

    def text(value):
        if stack == [f"{NS}|{x}" for x in ("gpx", "trk", "trkseg", "trkpt", "time")]:
            time_text.append(value)
            if sum(map(len, time_text)) > 64:
                fail("time text too long")

    def end(name):
        nonlocal current, last_t, run, break_reason
        path = [f"{NS}|{x}" for x in ("gpx", "trk", "trkseg", "trkpt")]
        if stack == path + [f"{NS}|time"]:
            try:
                current["t"] = timestamp("".join(time_text).strip())
            except InputError as exc:
                fail(str(exc))
        elif stack == path:
            if current.pop("times") > 1:
                fail("duplicate time elements")
            if "t" not in current:
                diagnostics.append({"code": "missing-time", "location": current["location"]})
                run += 1
                break_reason = "missing-time"
            else:
                if last_t is not None and current["t"] <= last_t:
                    fail("timestamps must strictly increase in source order; duplicates and overlaps rejected")
                current["run"] = run
                current["break_before"] = break_reason
                points.append(current)
                last_t = current["t"]
                break_reason = "segment"
            current = None
        stack.pop()

    def forbidden(*args):
        fail("DTDs, entities, and processing instructions are unsupported")

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = text
    parser.StartDoctypeDeclHandler = forbidden
    parser.EntityDeclHandler = forbidden
    parser.ExternalEntityRefHandler = forbidden
    parser.ProcessingInstructionHandler = forbidden
    try:
        # Chunking bounds cancellation latency even for large inputs.
        for offset in range(0, len(data), 65536):
            parser.Parse(data[offset:offset + 65536], False)
        parser.Parse(b"", True)
    except expat.ExpatError as exc:
        fail(f"malformed XML ({exc.code})")
    if not points:
        fail("no timestamped track points")
    return points, diagnostics, ignored


def load(manifest_path, max_gap_ms=60000):
    if type(max_gap_ms) is not int or not 1 <= max_gap_ms <= 86400000:
        raise InputError("max gap must be 1..86400000 milliseconds")
    manifest_path = Path(manifest_path)
    raw = read_regular(manifest_path, MAX_MANIFEST_BYTES)
    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise InputError("duplicate manifest key")
            out[key] = value
        return out
    try:
        manifest = json.loads(raw, object_pairs_hook=unique)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise InputError("invalid JSON manifest") from exc
    if not isinstance(manifest, dict) or set(manifest) != {"version", "synthetic", "tracks"} or type(manifest["version"]) is not int or manifest["version"] != 1 or manifest["synthetic"] is not True:
        raise InputError("manifest requires version:1, synthetic:true, and tracks only")
    entries = manifest["tracks"]
    if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_FILES:
        raise InputError(f"manifest requires 1..{MAX_FILES} tracks")
    aliases, paths, tracks = set(), set(), []
    total = 0
    budget = [0]
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict) or set(entry) != {"alias", "file"}:
            raise InputError("each track requires alias and file only")
        alias, filename = entry["alias"], entry["file"]
        if not isinstance(alias, str) or not 1 <= len(alias) <= 48 or not alias.isprintable() or alias.strip() != alias or alias in aliases:
            raise InputError("aliases must be unique, printable, trimmed, and 1..48 characters")
        if not isinstance(filename, str) or not filename or len(filename) > 1024 or "://" in filename or "\0" in filename:
            raise InputError("file must name a local path")
        path = (manifest_path.parent / filename).resolve()
        if path in paths:
            raise InputError("duplicate source path")
        paths.add(path)
        aliases.add(alias)
        data = read_regular(path, MAX_FILE_BYTES)
        total += len(data)
        if total > MAX_TOTAL_BYTES:
            raise InputError("total input byte limit exceeded")
        points, diagnostics, ignored = parse_gpx(data, i, budget)
        gaps = []
        for a, b in zip(points, points[1:]):
            reason = b["break_before"] if a["run"] != b["run"] else "max-gap" if b["t"] - a["t"] > max_gap_ms else None
            if reason:
                gaps.append({"start": a["t"], "end": b["t"], "reason": reason})
        tracks.append({"id": i, "alias": alias, "source": {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)},
                       "points": points, "gaps": gaps, "diagnostics": diagnostics, "ignored_elements": ignored})
    all_points = [p for tr in tracks for p in tr["points"]]
    start, end = min(p["t"] for p in all_points), max(p["t"] for p in all_points)
    if end - start > MAX_SPAN_MS:
        raise InputError("timeline exceeds 31 days")
    west, east = min(p["lon"] for p in all_points), max(p["lon"] for p in all_points)
    south, north = min(p["lat"] for p in all_points), max(p["lat"] for p in all_points)
    if east - west > 180:
        raise InputError("antimeridian-spanning inputs unsupported")
    if east - west > 10 or north - south > 10:
        raise InputError("coordinate extent exceeds 10 degrees")
    return {"format": "track-gap-timeline", "version": 1, "synthetic": True, "max_gap_ms": max_gap_ms,
            "manifest_sha256": hashlib.sha256(raw).hexdigest(), "start": start, "end": end,
            "bounds": {"west": west, "east": east, "south": south, "north": north},
            "projection": "local-equirectangular", "tracks": tracks}


def position(track, t, max_gap_ms):
    points = track["points"]
    index = bisect.bisect_left(points, t, key=lambda p: p["t"])
    if index < len(points) and points[index]["t"] == t:
        p = points[index]
        return {"status": "observed", "lat": p["lat"], "lon": p["lon"], "reason": None}
    if index == 0 or index == len(points):
        return {"status": "unknown", "lat": None, "lon": None, "reason": "outside-observations"}
    a, b = points[index - 1], points[index]
    reason = b["break_before"] if a["run"] != b["run"] else "max-gap" if b["t"] - a["t"] > max_gap_ms else None
    if reason:
        return {"status": "unknown", "lat": None, "lon": None, "reason": reason}
    fraction = (t - a["t"]) / (b["t"] - a["t"])
    return {"status": "interpolated", "lat": a["lat"] + fraction * (b["lat"] - a["lat"]),
            "lon": a["lon"] + fraction * (b["lon"] - a["lon"]), "reason": None}
