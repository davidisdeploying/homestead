import hashlib, sqlite3, tempfile, unittest, zipfile
from contextlib import contextmanager
from pathlib import Path
import xml.etree.ElementTree as ET

from reader_library import (ReaderUnavailable, clone_range, create_schema, find_boundary,
                            inner_html, reader_asset, reader_section, validate_zip_names)


@contextmanager
def fixture_db(path):
    """Commit and close. `with sqlite3.connect(...)` commits but does not close."""
    conn = sqlite3.connect(path)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


XHTML = b'''<html xmlns="http://www.w3.org/1999/xhtml"><body>
<nav><p>Split Two Real Opening</p></nav><h1>Combined chapter</h1>
<p>Split one genuine opening paragraph with enough unique words to identify it.</p>
<figure><img src="images/figure.jpg" alt="Inspection diagram" onerror="bad()"/><figcaption>Authentic inspection figure</figcaption></figure>
<script>alert(1)</script><form><input value="x"/></form><iframe src="https://bad.example"></iframe>
<p onclick="bad()" style="position:fixed">Split Two Real Opening paragraph with enough unique words to identify it.</p>
<p>Second part only.</p><a href="https://bad.example">external</a></body></html>'''

class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.epub = self.root / "source.epub"
        with zipfile.ZipFile(self.epub, "w") as out:
            out.writestr("OPS/chapter.xhtml", XHTML)
            out.writestr("OPS/images/figure.jpg", b"\xff\xd8\xfffixture")
        self.digest = hashlib.sha256(self.epub.read_bytes()).hexdigest()
        self.db = self.root / "reader.sqlite3"
        with fixture_db(self.db) as conn:
            create_schema(conn)

    def tearDown(self): self.tmp.cleanup()

    def _insert(self, stable="book:001", epub_hash=None, epub_path=None, html=None, fmt="epub"):
        with fixture_db(self.db) as conn:
            conn.execute("INSERT INTO section_mappings VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                stable,"book","Part","Book",fmt,"# Part\n\nFallback body",epub_hash or self.digest,
                str(epub_path or self.epub),"OPS/chapter.xhtml","OPS/chapter.xhtml#path=1",None,
                html or '<div><img src="/api/learning/sections/book%3A001/assets/0123456789abcdef0123456789abcdef" alt="Inspection diagram"><figcaption>Authentic inspection figure</figcaption></div>',None,"now"))
            conn.execute("INSERT INTO reader_assets VALUES(?,?,?,?)", (stable,"0123456789abcdef0123456789abcdef","OPS/images/figure.jpg","image/jpeg"))

    def test_exact_split_boundary_skips_duplicate_toc_heading(self):
        root = ET.fromstring(XHTML); body = next(x for x in root.iter() if x.tag.endswith("body"))
        content = "# Part Two\n\nSplit Two Real Opening paragraph with enough unique words to identify it."
        boundary = find_boundary(body, content)
        self.assertEqual("p", boundary.tag.rsplit("}",1)[-1]); self.assertIn("paragraph", "".join(boundary.itertext()))
        prior = find_boundary(body, "# Part One\n\nSplit one genuine opening paragraph with enough unique words to identify it.")
        cloned, _ = clone_range(body,"OPS/chapter.xhtml","book:001",{"OPS/chapter.xhtml","OPS/images/figure.jpg"},prior,boundary)
        rendered = inner_html(cloned)
        self.assertIn("Split one genuine", rendered); self.assertNotIn("Second part only", rendered)

    def test_authentic_image_caption_and_sanitizer(self):
        root=ET.fromstring(XHTML); body=next(x for x in root.iter() if x.tag.endswith("body"))
        cloned, assets=clone_range(body,"OPS/chapter.xhtml","book:001",{"OPS/chapter.xhtml","OPS/images/figure.jpg"},body)
        rendered=inner_html(cloned)
        self.assertIn("Authentic inspection figure", rendered); self.assertIn('alt="Inspection diagram"', rendered)
        self.assertNotIn("script", rendered); self.assertNotIn("onerror", rendered); self.assertNotIn("onclick", rendered)
        self.assertNotIn("style=", rendered); self.assertNotIn("iframe", rendered); self.assertNotIn("form", rendered)
        self.assertNotIn("https://bad.example", rendered); self.assertEqual(1, len(assets))

    def test_asset_allowlist_and_hash(self):
        self._insert()
        data,mime=reader_asset("book:001","0123456789abcdef0123456789abcdef",self.db,self.root)
        self.assertTrue(data.startswith(b"\xff\xd8\xff")); self.assertEqual("image/jpeg",mime)
        with self.assertRaises(ReaderUnavailable): reader_asset("book:001","f"*32,self.db,self.root)

    def test_zip_traversal_rejected(self):
        with self.assertRaises(ReaderUnavailable): validate_zip_names(["../escape.jpg"])
        bad=self.root/"bad.epub"
        with zipfile.ZipFile(bad,"w") as out: out.writestr("../escape.jpg",b"bad")
        self._insert("book:bad", hashlib.sha256(bad.read_bytes()).hexdigest(), bad)
        result=reader_section("book:bad",self.db,self.root)
        self.assertEqual("markdown",result["reader_format"])

    def test_hash_mismatch_and_missing_epub_fallback(self):
        self._insert("book:hash", "0"*64)
        self.assertEqual("markdown", reader_section("book:hash",self.db,self.root)["reader_format"])
        missing=self.root/"missing.epub"; self._insert("book:missing",self.digest,missing)
        self.assertEqual("markdown", reader_section("book:missing",self.db,self.root)["reader_format"])

if __name__ == "__main__": unittest.main()
