"""Pixel-preservation and photo/marker binding checks for the standalone POC."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageCms, ImageOps

import poc


class PhotoPocTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="gpio-photo-poc-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "viewer.html").write_text(
            '<script type="application/json">__POC_DATA__</script>', encoding="utf-8"
        )
        template_patch = patch.object(poc, "HERE", self.root)
        template_patch.start()
        self.addCleanup(template_patch.stop)

        # Small lossless gradient, with an actual 90-degree EXIF orientation.
        # The long side exceeds the default crop so source subregions differ.
        image = Image.new("RGB", (480, 288))
        image.putdata([(x % 256, y % 256, (x + y) % 256)
                       for y in range(image.height) for x in range(image.width)])
        exif = Image.Exif()
        exif[274] = 6
        self.photo = self.root / "測試照片.png"
        image.save(self.photo, exif=exif)
        with Image.open(self.photo) as source:
            self.expected = ImageOps.exif_transpose(source).convert("RGB")

    def test_generated_raw_and_crops_preserve_original_pixels(self):
        out = self.root / "pixel-output"
        result = poc.generate([self.photo], out, demo=True)
        view = result["images"][0]
        self.assertEqual((view["width"], view["height"]), (288, 480))
        with Image.open(out / "raw-1.png") as raw:
            self.assertEqual(raw.size, self.expected.size)
            self.assertEqual(raw.tobytes(), self.expected.tobytes())
        self.assertEqual(view["decoded_pixels_sha256"],
                         hashlib.sha256(self.expected.tobytes()).hexdigest())
        for crop in view["crops"]:
            with self.subTest(crop=crop["region_id"]):
                expected_crop = self.expected.crop(crop["box"])
                with Image.open(out / crop["path"]) as actual:
                    self.assertEqual(actual.size, expected_crop.size)
                    self.assertEqual(actual.tobytes(), expected_crop.tobytes())
                self.assertFalse(crop["adds_detail"])
        self.assertTrue(any(crop["box"] != [0, 0, 288, 480] for crop in view["crops"]))
        self.assertFalse(result["cloud_called"])

    def test_json_replay_is_bound_to_source_hash_and_oriented_size(self):
        first = self.root / "first"
        original = poc.generate([self.photo], first, demo=True)
        markers_path = first / "markers.json"
        replay = poc.generate([self.photo], self.root / "replay", markers_path=markers_path)
        self.assertEqual(replay["images"][0]["markers"], original["images"][0]["markers"])

        other = self.root / "different.png"
        different = self.expected.copy()
        different.putpixel((0, 0), (255, 255, 255))
        different.save(other)
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            poc.generate([other], self.root / "wrong-photo", markers_path=markers_path)

        mismatched = json.loads(markers_path.read_text(encoding="utf-8"))
        mismatched["images"][0]["width"] += 1
        wrong_size = self.root / "wrong-size.json"
        wrong_size.write_text(json.dumps(mismatched), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "尺寸"):
            poc.generate([self.photo], self.root / "wrong-size", markers_path=wrong_size)

    def test_icc_normalization_preserves_source_and_canonical_crop_pixels(self):
        source_profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
        profile_bytes = source_profile.tobytes()
        tagged = self.root / "帶ICC的照片.png"
        with Image.open(self.photo) as source:
            source.save(tagged, icc_profile=profile_bytes, exif=source.getexif())
        with Image.open(tagged) as source:
            source_pixels = ImageOps.exif_transpose(source).convert("RGB")
            expected = ImageCms.profileToProfile(
                source_pixels,
                ImageCms.ImageCmsProfile(io.BytesIO(source.info["icc_profile"])),
                ImageCms.createProfile("sRGB"),
                outputMode="RGB",
            )

        out = self.root / "icc-output"
        result = poc.generate([tagged], out, demo=True)
        view = result["images"][0]
        self.assertEqual((out / view["source_copy"]).read_bytes(), tagged.read_bytes())
        with Image.open(out / "raw-1.png") as canonical:
            self.assertNotIn("icc_profile", canonical.info)
            self.assertEqual(canonical.size, expected.size)
            self.assertEqual(canonical.tobytes(), expected.tobytes())
        self.assertEqual(view["decoded_pixels_sha256"], hashlib.sha256(expected.tobytes()).hexdigest())
        for crop in view["crops"]:
            with self.subTest(crop=crop["region_id"]):
                with Image.open(out / crop["path"]) as actual:
                    self.assertNotIn("icc_profile", actual.info)
                    self.assertEqual(actual.tobytes(), expected.crop(crop["box"]).tobytes())

    def test_nonfinite_and_out_of_bounds_markers_are_rejected(self):
        valid = dict(id="A", x=12, y=18, physical_pin=None, reviewed=False)
        for field, value in [("x", float("nan")), ("y", float("inf")),
                             ("x", float("-inf")), ("x", -0.01), ("y", -1),
                             ("x", 288), ("y", 480), ("x", True)]:
            with self.subTest(field=field, value=value):
                with self.assertRaises(ValueError):
                    poc.validate_markers([{**valid, field: value}], self.expected.size)

    def test_candidate_pins_require_integer_and_review_requires_pin(self):
        valid = dict(id="A", x=12, y=18, physical_pin=None, reviewed=False)
        for pin in [2.5, 2.0, "2", True, float("nan"), float("inf"), 0, 41]:
            with self.subTest(pin=pin):
                with self.assertRaises(ValueError):
                    poc.validate_markers([{**valid, "physical_pin": pin}], self.expected.size)
        with self.assertRaises(ValueError):
            poc.validate_markers([{**valid, "reviewed": True}], self.expected.size)
        accepted = poc.validate_markers([{**valid, "physical_pin": 2}], self.expected.size)
        self.assertEqual(accepted[0]["physical_pin"], 2)
        self.assertFalse(accepted[0]["reviewed"])

    def test_corner_crops_keep_full_window_without_crossing_bounds(self):
        for size in [(701, 503), (17, 11)]:
            width, height = size
            for point in [(0, 0), (width - .001, 0),
                          (0, height - .001), (width - .001, height - .001)]:
                with self.subTest(size=size, point=point):
                    left, top, right, bottom = poc.crop_box(size, point)
                    self.assertGreaterEqual(left, 0)
                    self.assertGreaterEqual(top, 0)
                    self.assertLessEqual(right, width)
                    self.assertLessEqual(bottom, height)
                    self.assertEqual((right - left, bottom - top),
                                     (min(420, width), min(420, height)))

    def test_all_demo_regions_leave_pin_identity_unconfirmed(self):
        for number in (0, 1):
            markers = poc.validate_markers(poc.demo_markers((3840, 2880), number), (3840, 2880))
            self.assertEqual(len(markers), 3)
            for marker in markers:
                self.assertIsNone(marker["physical_pin"])
                self.assertFalse(marker["reviewed"])
                self.assertEqual(marker["source"], "demo_seed")

    def test_cloud_observation_is_preserved_separately_from_local_pixels(self):
        observation = dict(wire_color="green", visibility="clear", wire_roi=dict(
            x_min=11, y_min=15, x_max=21, y_max=25), evidence="Visible colored insulation",
            model="test-model", effort="low")
        cloud_marker = dict(id="P1-01", x=12, y=18, physical_pin=None, reviewed=False,
                            source="cloud_vision_joint", cloud_observation=observation)
        accepted = poc.validate_markers([cloud_marker], self.expected.size)
        self.assertEqual(accepted[0]["cloud_observation"], observation)
        imported = dict(version=1, cloud_run=dict(model="test-model", effort="low", one_request=True),
                        images=[dict(sha256=hashlib.sha256(self.photo.read_bytes()).hexdigest(),
                                     width=288, height=480, markers=[cloud_marker])])
        marker_file = self.root / "cloud.json"
        marker_file.write_text(json.dumps(imported), encoding="utf-8")
        generated = poc.generate([self.photo], self.root / "cloud-replay", markers_path=marker_file)
        marker = generated["images"][0]["markers"][0]
        self.assertEqual(marker["cloud_observation"], observation)
        self.assertIn("sample_color", marker)
        self.assertIsNone(marker["physical_pin"])
        self.assertFalse(marker["reviewed"])
        self.assertEqual(generated["images"][0]["annotation_method"], "cloud_vision_joint")
        self.assertTrue(generated["cloud_called"])

    def test_invalid_cloud_region_or_color_is_rejected(self):
        valid = dict(wire_color="green", visibility="clear", wire_roi=dict(
            x_min=11, y_min=15, x_max=21, y_max=25), evidence="Visible insulation",
            model="test-model", effort="low")
        for changes in [dict(wire_color="invented"), dict(visibility="certain"), dict(evidence=""),
                        dict(wire_roi=dict(x_min=11, y_min=15, x_max=288, y_max=25)),
                        dict(wire_roi=dict(x_min=21, y_min=15, x_max=11, y_max=25)),
                        dict(wire_roi=dict(x_min=float("nan"), y_min=15, x_max=21, y_max=25))]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                poc.validate_cloud_observation({**valid, **changes}, self.expected.size)
        marker = dict(id="P1-01", x=12, y=18, physical_pin=None, reviewed=False,
                      source="cloud_vision_joint")
        with self.assertRaises(ValueError):
            poc.validate_markers([marker], self.expected.size)


if __name__ == "__main__":
    unittest.main()
