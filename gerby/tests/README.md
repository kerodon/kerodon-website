Tests
=====

The script `find_tex_errors.py` runs a headless browser through all tags
corresponding to sections and looks for MathJax errors. When TeX errors are
found, they are reported in console by a print statement. The tag at which this
error is found is given, together with the offending LaTeX code.

To run this script:

  1. Install `selenium`, via `pip install selenium`. See the
  [docs](https://selenium-python.readthedocs.io/) for more detail.
  2. Install `geckodriver` to run the Firefox webdriver. Obtain the binary
  [here](https://github.com/mozilla/geckodriver/releases), and put it somewhere
  where your `PATH` variable can find.
  3. Change the parameters `database` and `url` in `find_tex_errors.py` as
  needed.
  4. Run your Flask app.
  5. Run `python find_tex_errors.py`.

Server performance
------------------

Run the functional and query-scaling regressions from the repository root:

```sh
.venv/bin/python -m unittest gerby.tests.test_performance -v
```

The tests use isolated in-memory databases. They cover Kerodon's subsection
cutoff, numeric ordering, parts, duplicate references, equations without
breadcrumbs, proof order, parent comments, bibliography neighbours and citations,
history dates, search pagination and radius, and large match sets. They also
check idempotent index upgrades and operation without the optional indexes.

To upgrade an existing book without reimporting it:

```sh
.venv/bin/python -m gerby.tools.indexes
```

The importer creates these indexes automatically. Application startup and
requests do not write schema changes.

To compare a change with the current working tree, save a source snapshot
before editing, then run the comparison after editing:

```sh
.venv/bin/python gerby/tests/benchmark_comparison.py \
  --snapshot /tmp/kerodon-before
# Edit the source, then:
.venv/bin/python gerby/tests/benchmark_comparison.py \
  --before-root /tmp/kerodon-before --output-dir /tmp/kerodon-comparison
```

The comparison includes uncommitted edits in the baseline. It uses identical
private database copies, read-only request connections, and empty and populated
comment fixtures. The baseline book has the navigation indexes removed; use
`--same-indexes` to compare application changes with both books indexed.
Requests alternate version order across warmed blocks; a separate comparison
measures first requests in fresh processes. `--cases` accepts a saved JSON
manifest for focused comparisons.

These are Flask server timings, including SQL and templates. Network, browser
rendering, and SCSS compilation are excluded. Citation dates are frozen for
response comparisons. The runner verifies body hashes, statuses, content types,
redirects, cookies, SQL counts, and identical book contents. Existing request
failures are reported separately; changed failures and changed responses fail
the comparison. Timing samples, p95s, process memory measurements, and summaries
are saved outside the repository.


Measured results (2026-10-30)
----------------------------

The local Kerodon book contained 8,189 tags and 174 bibliography entries.
The baseline was the working tree before the performance changes, including
its existing local edits. Four alternating blocks, each with one warm-up and
five measured rounds, provided 20 warm samples per request. First requests
used three fresh-process samples on a representative subset.

The original timing run covered 538 request cases, with 524 successful matching
responses. Thirteen pre-existing failures were excluded: seven
Markdown-extension errors, three missing-parent statistics errors, and three
graph-initialization errors. One further exclusion was a benchmark mistake:
source snapshots omitted the existing XML feed template. The snapshot tool
now includes XML, and a focused before/after rerun verified that the empty feed
works with identical output. A populated feed still hits the Markdown error.
The timings below retain the original 524-case successful corpus; the focused
feed rerun is recorded in the adjacent `rss-correction` results directory.
The application changes introduced no failures. No timed request had
both a slowdown greater than 10% and an increase greater than 0.5 ms in either
its median or p95.

The sum of per-request warm medians fell from 5,790.4 ms to
1,343.1 ms (76.8% less server time). SQL queries per corpus pass
fell from 12,353 to 4,203. First-request time fell by
50.8%. These are corpus comparisons, not traffic-weighted production estimates.

Times below are medians of the per-request medians in each group:

| Request group | Before | After |
| --- | ---: | ---: |
| Chapter | 8.12 ms | 1.99 ms |
| Section | 7.83 ms | 1.46 ms |
| Subsection | 7.98 ms | 1.80 ms |
| Statement | 6.52 ms | 1.12 ms |
| Tag statistics | 8.40 ms | 1.28 ms |
| Bibliography entry | 14.11 ms | 3.58 ms |
| Search | 71.13 ms | 13.47 ms |
| Structure API | 6.25 ms | 2.84 ms |

Gerby's bibliography batching, navigation indexes, metadata-only navigation,
key-based reference sorting, tree construction, bulk dependency/statistics
queries, and search pagination were adapted to Kerodon. Existing part TOC
prefix selection and equation breadcrumb behavior were preserved.

Additional retained improvements were tuple-based bibliography field loading,
skipping unused heading HTML in search, and an index-covered `COUNT(*)` for
site statistics. The direct incoming-reference count experiment had no
consistent overall benefit on this dataset and was removed. The statistics
count adjustment fixed a regression caused by the new composite index.

The final raw measurements and source/database fingerprints are in
`/private/tmp/kerodon-performance-20261030/final/summary.json`. The baseline
source snapshot and pre-upgrade database backup are in the parent directory.
Generated measurements are intentionally kept outside Git.
