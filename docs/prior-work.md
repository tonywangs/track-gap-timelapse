# Sources and scope

Reviewed 2026-10-13. This project makes no claim of inventing GPX viewing, offline
file loading, track replay, or linear interpolation.

- [TopoGrafix GPX 1.1 schema documentation](https://www.topografix.com/gpx/1/1/)
  defines WGS84 coordinates, optional point times, multiple track segments, and
  extension containers. Segment boundaries explicitly represent discontinuity.
  This informed the strict subset and the rule against bridging segments. The
  application does not claim full schema validation.
- [mpetazzoni/leaflet-gpx](https://github.com/mpetazzoni/leaflet-gpx) is an existing
  GPX display plugin for Leaflet. Its documented track drawing and marker options
  establish that rendering GPX tracks is an existing capability. Track / Gap uses
  a local coordinate plot and does not incorporate Leaflet or its map assets.
- [makinacorpus/Leaflet.FileLayer](https://github.com/makinacorpus/Leaflet.FileLayer)
  documents local file loading for GPX and other geographic formats. Local-file
  workflows already exist; this project's scope is synchronized gap-aware replay,
  a conservative input contract, deterministic exports, and independent tests.

These were documentation/implementation-interface reviews, not benchmark
comparisons or audits of the other projects. Their code was not copied or
executed. The synthetic fixtures and implementation here are self-contained.
