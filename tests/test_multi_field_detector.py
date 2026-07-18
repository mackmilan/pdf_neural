from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

from backend.app.services.pdf import MultiFieldDetector, merge_field_detections


class FakeFieldDetector:
    def __init__(self, detections):
        self.detections = detections
        self.rendered_args = []

    def detect(self, _pdf_path):
        return self.detections

    def detect_rendered(self, rendered, pages):
        self.rendered_args.append((rendered, pages))
        return self.detections


class MultiFieldDetectorTest(unittest.TestCase):
    def test_merge_field_detections_keeps_highest_confidence_duplicate(self):
        detections = [
            {"page": 1, "x": 10, "y": 20, "width": 100, "height": 20, "confidence": 0.7},
            {"page": 1, "x": 12, "y": 21, "width": 98, "height": 20, "confidence": 0.9},
            {"page": 1, "x": 250, "y": 20, "width": 80, "height": 20, "confidence": 0.6},
        ]

        merged = merge_field_detections(detections)

        self.assertEqual(2, len(merged))
        self.assertIn(0.9, {item["confidence"] for item in merged})
        self.assertIn(250, {item["x"] for item in merged})

    def test_multi_field_detector_tags_model_and_merges_results(self):
        general = FakeFieldDetector([
            {"page": 1, "x": 10, "y": 20, "width": 100, "height": 20, "confidence": 0.7},
        ])
        mongo = FakeFieldDetector([
            {"page": 1, "x": 12, "y": 21, "width": 98, "height": 20, "confidence": 0.9},
            {"page": 2, "x": 30, "y": 40, "width": 60, "height": 20, "confidence": 0.8},
        ])
        detector = MultiFieldDetector([
            ("general", general),
            ("mongo", mongo),
        ])
        rendered = [Path("page-1.png")]
        pages = [object()]
        pdf = MagicMock()
        pdf.pages = pages
        pdf.__enter__.return_value = pdf

        with patch("backend.app.services.pdf.render_pdf", return_value=rendered) as render_pdf, patch("backend.app.services.pdf.pdfplumber.open", return_value=pdf):
            detections = detector.detect(Path("document.pdf"))

        self.assertEqual(2, len(detections))
        self.assertEqual("mongo", detections[0]["model"])
        self.assertEqual(2, detections[1]["page"])
        render_pdf.assert_called_once()
        self.assertEqual([(rendered, pages)], general.rendered_args)
        self.assertEqual([(rendered, pages)], mongo.rendered_args)


if __name__ == "__main__":
    unittest.main()
