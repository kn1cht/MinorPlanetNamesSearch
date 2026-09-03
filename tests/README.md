# Tests

This directory contains unit tests and test fixtures for the `mpnames` package.

## MPC Data Attribution

Some test files contain short excerpts from
[IAU Minor Planet Center (MPC)](https://www.minorplanetcenter.net/) public data,
used as representative samples to verify parser and classifier behaviour.

### Fixture files (`fixtures/`)

| File | MPC Source |
|---|---|
| `fixtures/mpnames_sample.html` | https://www.minorplanetcenter.net/iau/lists/MPNames.html |
| `fixtures/mpcorb_sample.dat` | https://www.minorplanetcenter.net/iau/MPCORB.html |
| `fixtures/numbered_mps_sample.txt` | https://www.minorplanetcenter.net/iau/lists/NumberedMPs.txt |
| `fixtures/identifier_sample.json` | https://data.minorplanetcenter.net/api/query-identifier |

### Inline citation text (`test_classifier.py`, etc.)

Short citation strings embedded directly in test source files
(e.g. for (3037) Alku, (6247) Amanogawa, (12349) Akebonozou, and others)
are quoted from the MPC database search:
https://www.minorplanetcenter.net/db_search/
