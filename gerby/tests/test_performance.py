"""Functional and query-scaling regressions, using isolated databases."""

import contextlib
import json
import re
import runpy
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

with patch("flask_scss.Scss"):
    from gerby.application import app
from gerby.database import (Tag, Part, Proof, Slogan, History, Reference,
                            Dependency, Footnote, Change, Commit, TagStatistic,
                            SearchTag, SearchStatement, Comment, BibliographyEntry,
                            BibliographyField, Citation, db, comments)
from gerby.tools.indexes import ensure_indexes
from gerby.views.methods import reference_key
from gerby.views.tag import combine


class PerformanceTests(unittest.TestCase):
    def setUp(self):
        self.original_book = db.database
        self.original_comments = comments.database
        self.original_testing = app.config["TESTING"]
        db.close()
        comments.close()
        db.init(":memory:", uri=False)
        comments.init(":memory:")
        db.create_tables([Tag, Part, Proof, Slogan, History, Reference,
                          Dependency, Footnote, Change, Commit, TagStatistic,
                          SearchTag, SearchStatement, BibliographyEntry,
                          BibliographyField, Citation])
        comments.create_tables([Comment])
        app.config["TESTING"] = True
        self.client = app.test_client(use_cookies=False)

        self.add_tag("P001", "1", "part", "Part")
        for tag, ref in [("C001", "1"), ("C002", "2"), ("C010", "10")]:
            self.add_tag(tag, ref, "chapter", "Chapter " + ref)
            Part.create(part="P001", chapter=tag)
        self.add_tag("P099", "99", "part", "Unrelated part")
        self.add_tag("C099", "99", "chapter", "Unrelated chapter")
        Part.create(part="P099", chapter="C099")
        self.add_tag("S099", "99.1", "section", "Unrelated section")
        self.add_tag("S001", "1.1", "section", "Section")
        self.add_tag("U001", "1.1.1", "subsection", "Subsection",
                     '<section><article id="L001">Statement</article></section>')
        self.add_tag("S002", "2.1", "section", "Second section")
        self.add_tag("S010", "10.1", "section", "Tenth section")
        self.add_tag("L001", "1.1.1.1", "lemma", "Target", "<p>scheme target</p>")
        Proof.create(tag="L001", number=2, html="<p>Second proof</p>")
        Proof.create(tag="L001", number=1, html="<p>First proof</p>")
        for model, html in [(Slogan, "A slogan"), (History, "A history"),
                            (Reference, "An author's reference")]:
            model.create(tag="L001", html=html)
        for name, value in [("preliminaries", 7), ("chapters", 2),
                            ("sections", 3), ("consequences", 200)]:
            TagStatistic.create(tag="L001", statistic=name, value=value)
        SearchTag.insert(tag="L001", html="scheme target").execute()
        for number in range(1, 201):
            tag = "T%03d" % number
            self.add_tag(tag, "1.1.1.%d" % (number + 1), "lemma", "Result",
                         "<p>scheme result %d</p>" % number)
            Dependency.create(tag=tag, to="L001")
            SearchTag.insert(tag=tag, html="scheme result").execute()
            if number % 2 == 0:
                SearchStatement.insert(tag=tag, html="scheme result").execute()

    def tearDown(self):
        db.close()
        comments.close()
        db.init(self.original_book, uri=False)
        comments.init(self.original_comments)
        app.config["TESTING"] = self.original_testing

    def add_tag(self, tag, ref, kind, name, html="<p>Content</p>"):
        return Tag.create(tag=tag, ref=ref, type=kind, name=name, active=True,
                          label="book-" + kind + "-" + tag, html=html)

    @contextlib.contextmanager
    def count_queries(self):
        counter = [0]

        def counted(original):
            def execute(*args, **kwargs):
                counter[0] += 1
                return original(*args, **kwargs)
            return execute

        with contextlib.ExitStack() as stack:
            for database in [db, comments]:
                stack.enter_context(patch.object(database, "execute_sql",
                                                counted(database.execute_sql)))
            yield counter

    def test_index_order_and_bounded_queries(self):
        with self.count_queries() as initial:
            response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertLess(body.index('href="/tag/C002"'), body.index('href="/tag/C010"'))
        for number in range(11, 51):
            tag = "C%03d" % number
            self.add_tag(tag, str(number), "chapter", "Another chapter")
            Part.create(part="P001", chapter=tag)
        with self.count_queries() as expanded:
            self.client.get("/")
        self.assertEqual(initial[0], expanded[0])
        self.assertLessEqual(expanded[0], 10)

    def test_structure_contains_only_part_descendants(self):
        with self.count_queries() as counter:
            response = self.client.get("/data/tag/P001/structure")
        data = json.loads(response.get_data())
        self.assertEqual([child["tag"] for child in data["children"]],
                         ["C001", "C002", "C010"])
        results = data["children"][0]["children"][0]["children"][0]["children"]
        self.assertEqual(results[0]["tag"], "L001")
        self.assertEqual(results[-1]["tag"], "T200")
        self.assertNotIn("S099", response.get_data(as_text=True))
        self.assertLessEqual(counter[0], 3)

    def test_part_structure_handles_duplicate_links_and_appendix_case(self):
        self.add_tag("C00A", "A", "chapter", "Appendix")
        self.add_tag("S00A", "A.1", "section", "Appendix section")
        self.add_tag("S00B", "a.1", "section", "Another appendix")
        Part.create(part="P001", chapter="C00A")
        Part.create(part="P001", chapter="C00A")
        data = json.loads(self.client.get("/data/tag/P001/structure").get_data())
        appendices = [child for child in data["children"] if child["tag"] == "C00A"]
        self.assertEqual(len(appendices), 1)
        self.assertEqual([child["tag"] for child in appendices[0]["children"]], ["S00A"])

    def test_navigation_without_parts(self):
        Part.drop_table()
        Tag.delete().where(Tag.type == "part").execute()
        body = self.client.get("/").get_data(as_text=True)
        self.assertLess(body.index('href="/tag/C002"'), body.index('href="/tag/C010"'))
        response = self.client.get("/tag/L001")
        self.assertEqual(response.status_code, 200)

    def test_section_badges_and_ordered_proofs(self):
        body = self.client.get("/tag/U001").get_data(as_text=True)
        for text in ["A slogan", "A history", "An author's reference"]:
            self.assertIn(text, body)
        body = self.client.get("/tag/L001").get_data(as_text=True)
        self.assertLess(body.index("First proof"), body.index("Second proof"))

    def test_breadcrumb_parent_comments_and_active_filter(self):
        for tag, active in [("P001", True), ("C001", True), ("S001", True),
                            ("S001", False)]:
            Comment.create(tag=tag, author="Reader", comment="Parent comment", active=active)
        body = self.client.get("/tag/L001/comments").get_data(as_text=True)
        self.assertIn("1 comment(s) on Chapter", body)
        self.assertIn("1 comment(s) on Section", body)
        self.assertIn("1 comment(s) on Part", body)
        self.assertNotIn("2 comment(s)", body)

    def test_reference_key_matches_legacy_numeric_and_appendix_order(self):
        refs = ["10.2", "2", "1.0.1", "1", "2.10", "2.2", "A", "A.2", "B", "2.A"]
        tags = [Tag(tag=str(i), ref=ref) for i, ref in enumerate(refs)]
        self.assertEqual([tag.ref for tag in sorted(tags)],
                         [tag.ref for tag in sorted(tags, key=lambda tag: reference_key(tag.ref))])

    def test_tree_handles_zero_components_and_duplicate_parents(self):
        tags = [Tag(tag=tag, ref=ref) for tag, ref in
                [("C001", "1"), ("C002", "1"), ("L001", "1.0.1"),
                 ("S001", "1.2"), ("T001", "1.2.1"), ("X001", "9.9")]]
        tree = combine(tags)
        self.assertEqual([tag.tag for tag in tree], ["C001", "C002"])
        for parent in tree:
            self.assertEqual([child.tag for child in parent.children], ["L001", "S001"])
            self.assertEqual(parent.children[1].children[0].tag, "T001")

    def test_index_upgrade_is_idempotent_and_used_for_navigation(self):
        # Emulate an older imported database, then apply the upgrade twice.
        for index in ["tag_ref", "tag_ref_prefix", "tag_type_ref"]:
            db.execute_sql('DROP INDEX "' + index + '"')
        before = list(Tag.select().order_by(Tag.tag).tuples())
        ensure_indexes()
        ensure_indexes()
        self.assertEqual(before, list(Tag.select().order_by(Tag.tag).tuples()))
        for sql, params, index in [
            ("SELECT tag FROM tag WHERE ref=?", ("1.1",), "tag_ref"),
            ("SELECT tag FROM tag WHERE ref LIKE ?", ("1.%",), "tag_ref_prefix"),
            ("SELECT tag FROM tag WHERE type=? AND ref IN (?,?)",
             ("section", "1.1", "2.1"), "tag_type_ref"),
            ("SELECT type,COUNT(*) FROM tag GROUP BY type", (),
             "COVERING INDEX tag_type_ref"),
        ]:
            plan = db.execute_sql("EXPLAIN QUERY PLAN " + sql, params).fetchall()
            self.assertIn(index, str(plan))

    def test_routes_work_without_navigation_indexes(self):
        paths = ["/", "/tag/S001", "/tag/U001", "/tag/L001", "/tag/L001/statistics",
                 "/data/tag/P001/structure", "/search?query=scheme&perpage=50",
                 "/search?query=scheme&radius=statements"]
        indexed = {path: self.client.get(path).get_data() for path in paths}
        for index in ["tag_ref", "tag_ref_prefix", "tag_type_ref"]:
            db.execute_sql('DROP INDEX "' + index + '"')
        for path in paths:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_data(), indexed[path])

    def test_kerodon_equation_breadcrumbs_and_part_neighbour_types(self):
        from gerby.views.methods import getBreadcrumb
        from gerby.views.tag import getNeighbours
        for kind in ["equation", "eqnarray", "item"]:
            tag = Tag(tag="E001", type=kind, ref="1.1.1.2")
            self.assertEqual(getBreadcrumb(tag), [tag])
        self.add_tag("P002", "1.2", "partlemma", "Part lemma")
        self.add_tag("P003", "1.3", "parttheorem", "Part theorem")
        left, right, up = getNeighbours(Tag(tag="P004", type="partlemma", ref="1.1"))
        self.assertEqual(right.type, "lemma")

    def test_part_toc_preserves_kerodon_heading_selection(self):
        from gerby.views.methods import getPartTags
        self.add_tag("U002", "10.1.1", "subsection", "Subsection")
        rows = getPartTags(Tag.get_by_id("P001"), headings_only=True)
        # Legacy bare-prefix selection includes chapter 10 under prefix 1 too.
        self.assertEqual(sum(row.tag == "C010" for row in rows), 2)
        copies = [row for row in rows if row.tag == "C010"]
        self.assertIsNot(copies[0], copies[1])
        self.assertTrue(all(row.type in ["chapter", "section", "subsection"] for row in rows))


class BenchmarkTests(unittest.TestCase):
    def test_snapshot_preserves_all_templates(self):
        root = Path(__file__).resolve().parents[2]
        snapshot_code = runpy.run_path(
            str(Path(__file__).with_name("benchmark_comparison.py")))["snapshot_code"]
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary)
            snapshot_code(root, destination)
            for source in (root / "gerby/templates").rglob("*"):
                if source.is_file():
                    with self.subTest(template=source.name):
                        self.assertEqual(source.read_bytes(),
                                         (destination / source.relative_to(root)).read_bytes())


if __name__ == "__main__":
    unittest.main()
