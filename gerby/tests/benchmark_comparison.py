"""Compare working-tree code with a saved snapshot using private databases.

Before editing:
  .venv/bin/python gerby/tests/benchmark_comparison.py --snapshot /tmp/kerodon-before
After editing:
  .venv/bin/python gerby/tests/benchmark_comparison.py \
      --before-root /tmp/kerodon-before --output-dir /tmp/kerodon-comparison

Neither version writes to the configured databases. Asset compilation is disabled.
"""

import argparse
import contextlib
import hashlib
import importlib.metadata
import json
import math
import platform
import random
import resource
import shutil
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode


INDEXES = ["tag_ref", "tag_ref_prefix", "tag_type_ref"]


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + "\n")


def sample(rows, amount):
    if not rows:
        return []
    if amount == 1:
        return [rows[len(rows) // 2]]
    indices = {round(i * (len(rows) - 1) / (amount - 1)) for i in range(amount)}
    return [rows[i] for i in sorted(indices)]


def select_cases(connection):
    cases = {}

    def add(path, group, status=200, fixture="empty"):
        key = fixture + ":" + path
        cases.setdefault(key, {"id": key, "path": path, "group": group,
                               "fixture": fixture, "expected_status": status})

    def tags(sql, amount, parameters=()):
        return [row[0] for row in sample(connection.execute(sql, parameters).fetchall(), amount)]

    for path in ["/", "/statistics", "/bibliography", "/recent-comments", "/recent-comments/2", "/recent-comments.xml"]:
        add(path, "overview")
    for path in ["/about", "/tags", "/search", "/markdown", "/robots.txt"]:
        add(path, "control")
    parts = tags("SELECT part_id FROM part GROUP BY part_id ORDER BY count(*), part_id", 9)
    chapters = tags("SELECT tag FROM tag WHERE type='chapter' ORDER BY tag", 30)
    sections = tags("SELECT tag FROM tag WHERE type='section' ORDER BY length(html), tag", 30)
    subsections = tags("SELECT tag FROM tag WHERE type='subsection' ORDER BY length(html), tag", 50)
    statements = tags("SELECT t.tag FROM tag t LEFT JOIN proof p ON p.tag_id=t.tag "
                      "WHERE t.type='lemma' GROUP BY t.tag ORDER BY "
                      "length(t.html)+coalesce(sum(length(p.html)),0), t.tag", 32)
    for kind in ["definition", "theorem", "proposition", "remark", "remarks", "example",
                 "exercise", "situation", "equation", "eqnarray", "item"]:
        statements += tags("SELECT tag FROM tag WHERE type=? ORDER BY length(html), tag", 12, (kind,))
    for table in ["slogan", "reference", "history"]:
        statements += tags('SELECT tag_id FROM "' + table + '" ORDER BY length(html),tag_id', 12)
    popular = tags("SELECT to_id FROM dependency GROUP BY to_id ORDER BY count(*), to_id", 32)
    statements = list(dict.fromkeys(statements + popular))
    for group, selected in [("part", parts), ("chapter", chapters),
                            ("section", sections), ("subsection", subsections), ("statement", statements)]:
        for tag in selected:
            add("/tag/" + tag, group)
    eligible = tags("SELECT tag FROM tag WHERE type IN "
                    "('lemma','definition','theorem','proposition','remark') ORDER BY length(html),tag", 16)
    for tag in popular + eligible:
        add("/tag/" + tag + "/statistics", "tag statistics")
    for tag in eligible:
        add("/tag/" + tag + "/cite", "citation")
    for tag in parts + sample(chapters, 24) + sample(sections, 12):
        add("/data/tag/" + tag + "/structure", "structure API")
    for tag in sample(sections, 12) + sample(statements, 12):
        for content in ["statement", "full"]:
            add("/data/tag/" + tag + "/content/" + content, "content API")
    for key in tags("SELECT key FROM bibliographyentry ORDER BY key", 24) + tags(
            "SELECT key_id FROM citation GROUP BY key_id ORDER BY count(*), key_id", 12):
        add("/bibliography/" + key, "bibliography entry")

    for query in ["category", "simplicial", "functor", "morphism", "ring*", "algebraic",
                  "ramification", "quasicompact", "quasicoherent", '"quasi-compact"',
                  '"finite presentation"', "scheme AND morphism", "scheme NOT affine",
                  "scheme OR ramification", "tensor NEAR product", "unmatchedbenchmarkterm"]:
        add("/search?" + urlencode({"query": query}), "search")
    for query in ["category", "simplicial", "functor", "morphism"]:
        for options in [{"page": 3}, {"page": 1000}, {"perpage": 50},
                        {"perpage": 100}, {"radius": "statements"}]:
            add("/search?" + urlencode({"query": query, **options}), "search")
    for query in ["simplicial", "cohomology", "ramification"]:
        add("/search?" + urlencode({"query": query, "perpage": "oo"}), "unlimited search")
    for path, status in [("/search?query=%22", 200), ("/search?query=0001", 302),
                         ("/tag/not-a-tag", 200), ("/tag/ZZZZ", 200),
                         ("/bibliography/nonexistent-benchmark-entry", 404)]:
        add(path, "validation", status)

    for path in ["/", "/statistics", "/recent-comments", "/recent-comments/2", "/recent-comments.xml"]:
        add(path, "populated comments", fixture="populated")
    for tag in popular[:16] + eligible[:8]:
        add("/tag/" + tag, "parent comments", fixture="populated")
        add("/tag/" + tag + "/comments", "comment navigation", fixture="populated")
    for tag in eligible[8:12]:
        add("/tag/" + tag, "own comments", fixture="populated")
    for graph in ["topics", "structure", "tree"]:
        add("/data/tag/0001/graph/" + graph, "graph API")
    return list(cases.values()), eligible[8:12], popular[:16] + eligible[:8]


def prepare_comments(book, destination, own_tags, parent_tags):
    connection = sqlite3.connect(destination)
    connection.execute('CREATE TABLE comment (id INTEGER PRIMARY KEY, tag TEXT, author TEXT NOT NULL, '
                       'site TEXT, email TEXT, date DATETIME NOT NULL, comment TEXT, active INTEGER NOT NULL)')
    if own_tags is not None:
        parents = set()
        for tag in parent_tags:
            ref = book.execute("SELECT ref FROM tag WHERE tag=?", (tag,)).fetchone()[0]
            pieces = ref.split(".")
            refs = [".".join(pieces[:i]) for i in range(1, len(pieces))]
            for ref in refs:
                parents.update(row[0] for row in book.execute(
                    "SELECT tag FROM tag WHERE ref=? AND type NOT IN ('item','part')", (ref,)))
            parents.update(row[0] for row in book.execute(
                "SELECT part_id FROM part JOIN tag ON tag.tag=part.chapter_id WHERE tag.ref=?", (pieces[0],)))
        targets = sorted(parents) + own_tags
        rows = []
        for number in range(300):
            rows.append((targets[number % len(targets)], "Benchmark reader", "", "reader@example.invalid",
                         "2024-01-02 12:00:00", "Example **comment** with $x$ and \\ref{00DV}.",
                         int(number % 7 != 0)))
        connection.executemany("INSERT INTO comment(tag,author,site,email,date,comment,active) VALUES (?,?,?,?,?,?,?)", rows)
    connection.commit()
    connection.close()


def data_digest(path):
    digest = hashlib.sha256()
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as connection:
        names = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        for name in names:
            digest.update(name.encode())
            for row in connection.execute('SELECT * FROM "' + name + '" ORDER BY rowid'):
                digest.update(json.dumps(row, ensure_ascii=False,
                                         default=lambda value: {"bytes": value.hex()}).encode())
                digest.update(b"\n")
    return digest.hexdigest()


def snapshot_code(root, destination):
    for path in (root / "gerby").rglob("*"):
        if (path.is_file() and path.suffix in {".py", ".html", ".md", ".txt", ".xml"}
                and "__pycache__" not in path.parts):
            target = destination / path.relative_to(root)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def prepare_snapshots(root, directory, before_root):
    snapshots = {}
    for version, source in [("before", before_root), ("after", root)]:
        destination = directory / version
        destination.mkdir()
        snapshot_code(source, destination)
        # Runtime settings are identical; database paths are rebound by workers.
        shutil.copy2(root / "gerby/configuration.py", destination / "gerby/configuration.py")
        snapshots[version] = destination
    return snapshots


def signature(response):
    body = response.get_data()
    return {"status": response.status_code, "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
            "content_type": response.content_type,
            "location": response.headers.get("Location"),
            "set_cookie": response.headers.getlist("Set-Cookie")}


def worker(config_path):
    config = json.loads(Path(config_path).read_text())
    sys.path.insert(0, config["root"])
    import_start = time.perf_counter()
    # Asset compilation writes CSS and is outside this server/SQL benchmark.
    with patch("flask_scss.Scss"):
        from gerby import application
    from gerby.database import db, comments
    import_ms = (time.perf_counter() - import_start) * 1000
    db.close()
    comments.close()
    db.init(Path(config["book"]).as_uri() + "?mode=ro", uri=True)
    application.app.config["TESTING"] = True
    application.app.logger.disabled = True
    client = application.app.test_client(use_cookies=False)
    fixture = None
    cases = config["cases"]
    records = {case["id"]: {**case, "samples_ms": []} for case in cases}

    def use_fixture(case):
        nonlocal fixture
        if fixture != case["fixture"]:
            comments.close()
            comments.init(Path(config["comments"][case["fixture"]]).as_uri() + "?mode=ro", uri=True)
            fixture = case["fixture"]

    def request_case(case, timed):
        use_fixture(case)
        record = records[case["id"]]
        start = time.perf_counter()
        try:
            response = client.get(case["path"])
            body = response.get_data()
            elapsed_ms = (time.perf_counter() - start) * 1000
            if response.status_code != case["expected_status"]:
                record["error"] = "Expected %d, got %d" % (case["expected_status"], response.status_code)
                return
            current = signature(response)
            if "signature" in record and current != record["signature"]:
                raise RuntimeError("Response changed within run: " + case["id"])
            record["signature"] = current
            if timed:
                record["samples_ms"].append(elapsed_ms)
        except Exception as error:
            record["error"] = type(error).__name__ + ": " + str(error)

    # Freeze citation dates so signatures remain stable between processes.
    import datetime
    class BenchmarkDatetime(datetime.datetime):
        @classmethod
        def utcnow(cls):
            return cls(2026, 1, 2, 12, 0, 0)
    import gerby.views.tag
    gerby.views.tag.datetime = type("Clock", (), {"datetime": BenchmarkDatetime})

    for round_number in range(-config["warmups"], config["rounds"]):
        order = list(cases)
        random.Random(1729 + config["block"] * 100 + round_number).shuffle(order)
        start = time.perf_counter()
        for case in order:
            if "error" not in records[case["id"]]:
                request_case(case, round_number >= 0)
        if not config.get("quiet"):
            print("%s block %d round %d: %.2fs (%d failures)" %
                  (config["version"], config["block"] + 1, round_number + 1,
                   time.perf_counter() - start,
                   sum("error" in record for record in records.values())), flush=True)

    # Instrument a separate pass, including SQL from both databases.
    for case in cases:
        record = records[case["id"]]
        if "error" in record:
            continue
        use_fixture(case)
        counter = [0]

        def counted(original):
            def execute(*args, **kwargs):
                counter[0] += 1
                return original(*args, **kwargs)
            return execute

        with contextlib.ExitStack() as stack:
            for database in [db, comments]:
                stack.enter_context(patch.object(database, "execute_sql", counted(database.execute_sql)))
            client.get(case["path"])
        record["queries"] = counter[0]

    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak_mib = rss / (1024 * 1024 if sys.platform == "darwin" else 1024)
    write_json(config["output"], {"version": config["version"], "block": config["block"],
                                  "import_ms": import_ms, "peak_rss_mib": peak_mib,
                                  "cases": list(records.values())})


def merge_runs(runs):
    cases = {}
    for run in runs:
        for record in run["cases"]:
            key = record["id"]
            if key not in cases:
                cases[key] = {**record, "samples_ms": []}
            combined = cases[key]
            if combined.get("signature") != record.get("signature"):
                raise RuntimeError("Response differs between blocks: " + key)
            if combined.get("error") != record.get("error"):
                raise RuntimeError("Failure differs between blocks: " + key)
            if combined.get("queries") != record.get("queries"):
                raise RuntimeError("SQL count differs between blocks: " + key)
            combined["samples_ms"].extend(record["samples_ms"])
    for record in cases.values():
        values = record["samples_ms"]
        if values:
            record["median_ms"] = statistics.median(values)
            record["p95_ms"] = sorted(values)[math.ceil(.95 * len(values)) - 1]
    return {"cases": list(cases.values()),
            "peak_rss_mib_by_run": [run["peak_rss_mib"] for run in runs]}


def compare(before, after):
    pairs = []
    failures = []
    regressions = []
    p95_flags = []
    for pre, post in zip(before["cases"], after["cases"]):
        if pre["id"] != post["id"]:
            raise RuntimeError("Case order differs")
        if pre.get("error") or post.get("error"):
            if pre.get("error") != post.get("error"):
                raise RuntimeError("Request outcome differs: " + pre["id"])
            failures.append({"id": pre["id"], "before": pre.get("error"), "after": post.get("error")})
            continue
        if pre["signature"] != post["signature"]:
            raise RuntimeError("Pre/post response differs: " + pre["id"])
        ratio = pre["median_ms"] / post["median_ms"]
        pair = {"id": pre["id"], "path": pre["path"], "group": pre["group"],
                "fixture": pre["fixture"], "before_ms": pre["median_ms"],
                "after_ms": post["median_ms"], "before_p95_ms": pre["p95_ms"],
                "after_p95_ms": post["p95_ms"], "speedup": ratio,
                "before_queries": pre["queries"], "after_queries": post["queries"]}
        pairs.append(pair)
        if post["median_ms"] > pre["median_ms"] * 1.1 and post["median_ms"] - pre["median_ms"] > .5:
            regressions.append(pair)
        if post["p95_ms"] > pre["p95_ms"] * 1.1 and post["p95_ms"] - pre["p95_ms"] > .5:
            p95_flags.append(pair)
    groups = []
    for group in sorted({pair["group"] for pair in pairs}):
        selected = [pair for pair in pairs if pair["group"] == group]
        groups.append({"group": group, "cases": len(selected),
                       "before_ms": statistics.median(pair["before_ms"] for pair in selected),
                       "after_ms": statistics.median(pair["after_ms"] for pair in selected),
                       "before_median_page_p95_ms": statistics.median(pair["before_p95_ms"] for pair in selected),
                       "after_median_page_p95_ms": statistics.median(pair["after_p95_ms"] for pair in selected),
                       "before_sum_ms": sum(pair["before_ms"] for pair in selected),
                       "after_sum_ms": sum(pair["after_ms"] for pair in selected)})
    pre_sum = sum(pair["before_ms"] for pair in pairs)
    post_sum = sum(pair["after_ms"] for pair in pairs)
    if not pairs:
        raise RuntimeError("No successful requests to compare")
    return {"successful_cases": len(pairs), "matched_signatures": len(pairs),
            "before_sum_ms": pre_sum, "after_sum_ms": post_sum,
            "reduction_percent": 100 * (1 - post_sum / pre_sum),
            "before_queries": sum(pair["before_queries"] for pair in pairs),
            "after_queries": sum(pair["after_queries"] for pair in pairs),
            "groups": groups, "failures": failures, "regressions": regressions,
            "p95_flags": p95_flags, "pairs": pairs}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path(tempfile.gettempdir()) / "kerodon-comparison")
    parser.add_argument("--before-root", type=Path, help="code snapshot made before editing")
    parser.add_argument("--snapshot", type=Path, help="save current working-tree code and exit")
    parser.add_argument("--same-indexes", action="store_true", help="prepare navigation indexes for both versions")
    parser.add_argument("--cases", type=Path, help="use a saved case manifest instead of selecting the full corpus")
    parser.add_argument("--blocks", type=int, default=4)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--first-request-repeats", type=int, default=5)
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        worker(args.worker)
        return
    if min(args.blocks, args.rounds, args.first_request_repeats) < 1:
        parser.error("run counts must be positive")
    root = Path(__file__).resolve().parents[2]
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if args.snapshot:
        if args.snapshot.exists():
            parser.error("snapshot destination already exists")
        if args.snapshot.resolve().is_relative_to(root):
            parser.error("save snapshots outside the repository")
        snapshot_code(root, args.snapshot.resolve())
        print("Saved working-tree snapshot to " + str(args.snapshot))
        return
    if not args.before_root or not (args.before_root / "gerby/application.py").is_file():
        parser.error("--before-root must point to a code snapshot")
    # Import just the runtime configuration in the parent; app imports only
    # happen inside workers, after selecting the relevant code snapshot.
    config_namespace = {}
    exec((root / "gerby/configuration.py").read_text(), config_namespace)
    source_book = (root / config_namespace["DATABASE"]).resolve()
    script = Path(__file__).resolve()
    with tempfile.TemporaryDirectory(prefix="kerodon-comparison-") as temporary:
        directory = Path(temporary)
        snapshots = prepare_snapshots(root, directory, args.before_root.resolve())
        books = {version: directory / (version + ".sqlite") for version in snapshots}
        with sqlite3.connect(source_book.as_uri() + "?mode=ro", uri=True) as source:
            for version, path in books.items():
                with sqlite3.connect(path) as target:
                    source.backup(target)
                    if version == "before":
                        for index in INDEXES:
                            target.execute('DROP INDEX IF EXISTS "' + index + '"')
        # Prepare private book indexes; never mutate the configured book.
        if (root / "gerby/tools/indexes.py").exists():
            sys.path.insert(0, str(root))
            from gerby.tools.indexes import ensure_indexes
            from gerby.database import db
            for version in (["before", "after"] if args.same_indexes else ["after"]):
                db.init(str(books[version]))
                ensure_indexes()
                db.close()
        digest_before = data_digest(books["before"])
        digest_after = data_digest(books["after"])
        if digest_before != digest_after:
            raise RuntimeError("Book contents differ between snapshots")
        with sqlite3.connect(books["after"]) as book:
            cases, own_tags, parent_tags = select_cases(book)
            if args.cases:
                cases = json.loads(args.cases.read_text())
                if not cases or len({case["id"] for case in cases}) != len(cases):
                    parser.error("case manifest must be nonempty and have unique IDs")
            comment_paths = {name: directory / (name + "-comments.sqlite") for name in ["empty", "populated"]}
            prepare_comments(book, comment_paths["empty"], None, [])
            prepare_comments(book, comment_paths["populated"], own_tags, parent_tags)
        write_json(output / "cases.json", cases)
        print("Selected %d requests; book contents match (%s)" % (len(cases), digest_before[:12]), flush=True)

        def run(version, block, selected, rounds, warmups, label, quiet=False):
            worker_output = (directory if quiet else output) / (label + ".json")
            configuration = {"version": version, "block": block,
                             "root": str(snapshots[version]), "book": str(books[version]),
                             "comments": {name: str(path) for name, path in comment_paths.items()},
                             "cases": selected, "rounds": rounds,
                             "warmups": warmups, "output": str(worker_output), "quiet": quiet}
            config_path = directory / "worker.json"
            write_json(config_path, configuration)
            subprocess.run([sys.executable, str(script), "--worker", str(config_path)], cwd=directory, check=True)
            return json.loads(worker_output.read_text())

        runs = {"before": [], "after": []}
        for block in range(args.blocks):
            order = ["before", "after"] if block % 2 == 0 else ["after", "before"]
            for version in order:
                runs[version].append(run(version, block, cases, args.rounds, 1,
                                         "warm-" + version + "-" + str(block + 1)))
        merged = {version: merge_runs(values) for version, values in runs.items()}
        for version, values in merged.items():
            write_json(output / ("warm-" + version + ".json"), values)
        warm = compare(merged["before"], merged["after"])
        print("Warm comparison: %d signatures match; %.1f%% less time; %d exclusions" %
              (warm["matched_signatures"], warm["reduction_percent"], len(warm["failures"])), flush=True)

        # Fresh interpreter and Flask app for each timed request. OS caches
        # remain warm; this is not a cold-disk or cold-network benchmark.
        first_cases = []
        for group in ["overview", "chapter", "section", "subsection", "statement", "tag statistics",
                      "structure API", "bibliography entry", "search", "unlimited search", "parent comments"]:
            eligible = [case for case in merged["before"]["cases"] if case["group"] == group and "error" not in case]
            first_cases.extend(sample(eligible, 2))
        first_cases = [{key: case[key] for key in ["id", "path", "group", "fixture", "expected_status"]}
                       for case in first_cases]
        fresh_runs = {"before": [], "after": []}
        for repeat in range(args.first_request_repeats):
            combined = {version: {"cases": [], "peak_rss_mib": 0} for version in fresh_runs}
            for number, case in enumerate(first_cases):
                order = ["before", "after"] if (number + repeat) % 2 == 0 else ["after", "before"]
                for version in order:
                    result = run(version, repeat, [case], 1, 0,
                                 "first-tmp", quiet=True)
                    combined[version]["cases"].extend(result["cases"])
                    combined[version]["peak_rss_mib"] = max(combined[version]["peak_rss_mib"], result["peak_rss_mib"])
            for version, values in combined.items():
                fresh_runs[version].append(values)
                write_json(output / ("first-" + version + "-" + str(repeat + 1) + ".json"), values)
            print("Fresh-process requests: repeat %d/%d complete" % (repeat + 1, args.first_request_repeats), flush=True)
        fresh_merged = {version: merge_runs(values) for version, values in fresh_runs.items()}
        for version, values in fresh_merged.items():
            write_json(output / ("first-" + version + ".json"), values)
        first = compare(fresh_merged["before"], fresh_merged["after"])
        code_hashes = {}
        for version, snapshot in snapshots.items():
            digest = hashlib.sha256()
            for path in sorted((snapshot / "gerby").rglob("*")):
                if path.is_file() and path.suffix in {".py", ".html", ".js", ".css"} and "tests" not in path.parts:
                    digest.update(str(path.relative_to(snapshot)).encode())
                    digest.update(path.read_bytes())
            code_hashes[version] = digest.hexdigest()
        summary = {"baseline_root": str(args.before_root.resolve()), "code_sha256": code_hashes,
                   "book_data_sha256": digest_before, "source_book": str(source_book),
                   "python": platform.python_version(), "platform": platform.platform(),
                   "packages": {package: importlib.metadata.version(package) for package in
                                ["Flask", "peewee", "Markdown", "mdx-bleach"]},
                   "warm_blocks": args.blocks, "warm_rounds_per_block": args.rounds,
                   "first_request_repeats": args.first_request_repeats,
                   "selected_cases": len(cases), "warm": warm, "first_request": first,
                   "notes": ["Flask test client, no network or browser timings",
                             "SCSS compilation disabled; citation dates frozen for response comparison",
                             "One warm-up per block; same shuffled route order for both versions",
                             "Alternating pre/post block order; identical read-only book data",
                             "300 synthetic comments, 257 active, in the populated fixture",
                             "First-request samples use fresh processes; OS caches are not flushed",
                             "Signatures include body hash, status, content type, redirect and cookie headers"]}
        write_json(output / "summary.json", summary)
        print("Saved results to " + str(output), flush=True)
        print("Warm: %.1f%% less time; first request: %.1f%% less time" %
              (warm["reduction_percent"], first["reduction_percent"]), flush=True)


if __name__ == "__main__":
    main()
