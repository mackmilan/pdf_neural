import random
import unittest

from PIL import Image
from unittest.mock import MagicMock

from converter import inferred_fields, textual_segmented_fields
from neural_field_detector import IMAGE_SIZE, augment_date_field, mask_components


class TestDateFieldTraining(unittest.TestCase):
    def test_synthetic_date_field_is_labeled_near_document_end(self):
        image = Image.new("L", (IMAGE_SIZE, IMAGE_SIZE), 255)
        mask = Image.new("L", (IMAGE_SIZE, IMAGE_SIZE), 0)

        augmented, target = augment_date_field(image, mask, random.Random(7))

        bbox = target.getbbox()
        self.assertIsNotNone(bbox)
        self.assertGreaterEqual(bbox[1], int(IMAGE_SIZE * .65))
        self.assertGreater(bbox[2] - bbox[0], IMAGE_SIZE * .15)
        self.assertLess(augmented.getextrema()[0], 100)

    def test_mask_components_keeps_small_date_region(self):
        probabilities = [[0.0] * 32 for _ in range(32)]
        for y in range(25, 27):
            for x in range(10, 20):
                probabilities[y][x] = .9

        components = mask_components(probabilities, threshold=.5, min_area=10)

        self.assertEqual(len(components), 1)
        self.assertEqual(components[0]["width"], 10)

    def test_infers_composite_libreoffice_date_field(self):
        page = MagicMock()
        page.width, page.height = 595.3, 841.89
        page.lines, page.rects = [], []
        page.chars = [
            {"text": "_", "x0": x, "x1": x + 5.5, "bottom": 661.19}
            for x in (235.4, 240.9, 246.4, 269.5, 275.0, 280.5, 369.5, 375.0, 380.5)
        ] + [
            {"text": "d", "x0": 255.0, "x1": 260.0, "bottom": 661.19},
            {"text": "d", "x0": 300.0, "x1": 305.0, "bottom": 661.19},
        ]
        words = [
            {"text": "Data:", "x0": 206.9, "x1": 232.64, "top": 650.19, "bottom": 661.19},
            {"text": "de", "x0": 254.7, "x1": 266.66, "top": 650.19, "bottom": 661.19},
            {"text": "20___", "x0": 358.48, "x1": 386.0, "top": 650.19, "bottom": 661.19},
        ]

        fields = inferred_fields(page, 1, words, [])

        self.assertEqual(len(fields), 3)
        self.assertTrue(all(field.type == "date" for field in fields))
        self.assertAlmostEqual(fields[0].x, 235.4)
        self.assertAlmostEqual(fields[0].width, 16.5)
        self.assertEqual([field.name for field in fields], ["data_dia", "data_mes", "data_ano"])

    def test_splits_slash_date_and_colon_time(self):
        page = MagicMock()
        page.chars = []
        x = 100.0
        for text in "___/___/______":
            page.chars.append({"text": text, "x0": x, "x1": x + 5, "bottom": 350.0})
            x += 5
        x = 100.0
        for text in "___:___":
            page.chars.append({"text": text, "x0": x, "x1": x + 5, "bottom": 375.0})
            x += 5
        words = [
            {"text": "Ponta", "bottom": 350.0},
            {"text": "Grossa,", "bottom": 350.0},
            {"text": "Horário:", "bottom": 375.0},
        ]

        fields = textual_segmented_fields(page, words)

        self.assertEqual([field["type"] for field in fields], ["date", "date", "date", "time", "time"])
        self.assertEqual(
            [field["label"] for field in fields],
            ["Data - dia", "Data - mes", "Data - ano", "Horário - hora", "Horário - minuto"],
        )


if __name__ == "__main__":
    unittest.main()
