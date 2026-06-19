import unittest
import tempfile
from pathlib import Path

from reportlab.pdfgen import canvas

from neural_table_detector import DEFAULT_THRESHOLD, consolidate_detections, mask_components, pdf_color, table_structures


class NeuralTableDetectorTest(unittest.TestCase):
    def test_default_threshold_excludes_low_probability_boundary_bleed(self):
        self.assertEqual(DEFAULT_THRESHOLD, 0.7)

    def test_mask_components_removes_noise_and_returns_confidence(self):
        mask = [[0.0] * 8 for _ in range(8)]
        for y in range(2, 6):
            for x in range(1, 7):
                mask[y][x] = 0.9
        mask[0][0] = 1.0

        boxes = mask_components(mask, threshold=0.5, min_area=4)

        self.assertEqual(len(boxes), 1)
        self.assertEqual(boxes[0]["x"], 1)
        self.assertEqual(boxes[0]["y"], 2)
        self.assertEqual(boxes[0]["width"], 6)
        self.assertAlmostEqual(boxes[0]["confidence"], 0.9)

    def test_extracts_rows_columns_and_original_line_color(self):
        with tempfile.TemporaryDirectory() as temp:
            pdf = Path(temp) / "colored-table.pdf"
            drawing = canvas.Canvas(str(pdf), pagesize=(300, 240))
            drawing.setStrokeColorRGB(.2, .4, .6)
            drawing.rect(30, 40, 240, 160)
            drawing.line(150, 40, 150, 200)
            drawing.line(30, 120, 270, 120)
            drawing.save()

            _, _, tables = table_structures(pdf)[0]

            self.assertEqual(len(tables), 1)
            self.assertEqual(tables[0]["row_count"], 2)
            self.assertEqual(tables[0]["column_count"], 2)
            self.assertEqual({line["color"] for line in tables[0]["lines"]}, {"#336699"})

    def test_pdf_color_supports_gray_rgb_and_cmyk(self):
        self.assertEqual(pdf_color(.5), "#808080")
        self.assertEqual(pdf_color((1, 0, 0)), "#ff0000")

    def test_consolidates_fragments_inside_the_same_vector_table(self):
        common = {"page": 7, "row_count": 7, "column_count": 4, "lines": []}
        detections = [
            {**common, "id": "main", "x": 50, "y": 70, "width": 700, "height": 500,
             "confidence": .84, "structure_source": "vector"},
            {**common, "id": "duplicate", "x": 50, "y": 70, "width": 700, "height": 500,
             "confidence": .78, "structure_source": "vector"},
            {"id": "fragment", "page": 7, "x": 470, "y": 150, "width": 280, "height": 260,
             "confidence": .80, "structure_source": "raster", "row_count": 2, "column_count": 1},
        ]

        consolidated = consolidate_detections(detections)

        self.assertEqual(len(consolidated), 1)
        self.assertEqual(consolidated[0]["id"], "main")


if __name__ == "__main__":
    unittest.main()
