import unittest

from backend.app.services.field_anchors import sync_field_anchors


def page_html(page: int, inner: str) -> str:
    return (
        f'<div class="pdf-page-shell" id="page-{page}" data-page="{page}">'
        f'<section class="pdf-page" data-page="{page}" style="width:595px;height:842px">'
        f"{inner}</section></div>"
    )


def anchor(name: str, kind: str = "text", style: str = "left:10px;top:20px;width:100px;height:20px") -> str:
    return (
        f'<a href="#{name}" class="pdf-field" id="{name}" data-name="{name}" '
        f'data-type="{kind}" style="{style}" title="{name}"></a>'
    )


class TestSyncFieldAnchors(unittest.TestCase):
    def field(self, name: str, **overrides) -> dict:
        base = {
            "name": name, "label": name.upper(), "type": "text",
            "page": 1, "x": 10, "y": 20, "width": 100, "height": 20,
        }
        base.update(overrides)
        return base

    def test_removes_orphan_anchors_of_deleted_fields(self):
        html = page_html(1, anchor("nome") + anchor("campo_neural_25") + '<span class="pdf-text">x</span>')
        result = sync_field_anchors(html, [self.field("nome")])
        self.assertNotIn("campo_neural_25", result)
        self.assertIn('data-name="nome"', result)
        self.assertIn('<span class="pdf-text">x</span>', result)

    def test_regenerates_anchor_geometry_from_fields(self):
        html = page_html(1, anchor("nome"))
        result = sync_field_anchors(html, [self.field("nome", x=55.5, y=70, width=120, height=18)])
        self.assertIn("left:55.5px;top:70px;width:120px;height:18px", result)
        self.assertEqual(result.count('data-name="nome"'), 1)

    def test_adds_anchor_for_new_field_on_right_page(self):
        html = page_html(1, anchor("nome")) + page_html(2, "")
        result = sync_field_anchors(html, [self.field("nome"), self.field("novo", page=2)])
        page_two = result.split('data-page="2"', 1)[1]
        self.assertIn('data-name="novo"', page_two)
        self.assertNotIn('data-name="novo"', result.split('data-page="2"', 1)[0])

    def test_skips_field_on_unknown_page(self):
        html = page_html(1, "")
        result = sync_field_anchors(html, [self.field("fantasma", page=9)])
        self.assertNotIn("fantasma", result)

    def test_escapes_html_in_labels(self):
        html = page_html(1, "")
        result = sync_field_anchors(html, [self.field("nome", label='A "B" <C>')])
        self.assertIn("A &quot;B&quot; &lt;C&gt;", result)
        self.assertNotIn("<C>", result)

    def test_empty_html_is_unchanged(self):
        self.assertEqual(sync_field_anchors("", [self.field("nome")]), "")


if __name__ == "__main__":
    unittest.main()
