import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ValidatorTests(unittest.TestCase):
    def test_app_manifest_requires_gpu_queue(self):
        manifest = json.loads((ROOT / "app.json").read_text(encoding="utf-8"))
        attrs = manifest["jobAttributes"]
        self.assertEqual(attrs["execSystemLogicalQueue"], "gpu-a100-small")
        self.assertEqual(manifest["notes"]["queueFilter"], ["gpu-a100-small", "gpu-a100", "gpu-a100-dev"])

    def test_valid_odx_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            sfm = project / "opensfm"
            image = project / "images" / "a.jpg"
            sfm.mkdir(parents=True)
            image.parent.mkdir()
            image.write_bytes(b"fake-image")
            (sfm / "image_list.txt").write_text("../images/a.jpg\n", encoding="utf-8")
            (sfm / "reconstruction.json").write_text(json.dumps([{
                "cameras": {"cam": {"projection_type": "perspective"}},
                "shots": {"a.jpg": {"rotation": [0, 0, 0], "translation": [0, 0, 0], "camera": "cam"}},
                "points": {"p": {"coordinates": [0, 0, 1], "color": [255, 255, 255]}},
            }]), encoding="utf-8")
            result = subprocess.run([
                "python3", str(ROOT / "validate_project.py"), "--project", str(project),
                "--max-images", "10", "--max-bytes", "1000",
            ], check=True, capture_output=True, text=True)
            report = json.loads(result.stdout)
            self.assertEqual(report["image_count"], 1)
            self.assertEqual(report["sparse_point_count"], 1)

    def test_project_rejects_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            sfm = project / "opensfm"
            sfm.mkdir(parents=True)
            (root / "outside.jpg").write_bytes(b"outside")
            (sfm / "image_list.txt").write_text("../../outside.jpg\n", encoding="utf-8")
            (sfm / "reconstruction.json").write_text(json.dumps([{
                "cameras": {"cam": {}}, "shots": {"a": {}}, "points": {"p": {}},
            }]), encoding="utf-8")
            result = subprocess.run([
                "python3", str(ROOT / "validate_project.py"), "--project", str(project),
                "--max-images", "10", "--max-bytes", "1000",
            ], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("outside the project", result.stderr + result.stdout)

    def test_stage_project_materializes_symlink_and_preserves_container_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source_sfm = source / "opensfm"
            image_store = root / "image-store"
            source_sfm.mkdir(parents=True)
            image_store.mkdir()
            (image_store / "a.jpg").write_bytes(b"fake-image")
            (source / "images").symlink_to(image_store, target_is_directory=True)
            (source_sfm / "image_list.txt").write_text(
                "/var/www/data/project/images/a.jpg\n", encoding="utf-8"
            )
            (source_sfm / "reconstruction.json").write_text(json.dumps([{
                "cameras": {"cam": {}},
                "shots": {"a.jpg": {}},
                "points": {"p": {}},
            }]), encoding="utf-8")
            staged = root / "staged"

            subprocess.run([
                "python3", str(ROOT / "stage_project.py"),
                "--source", str(source), "--destination", str(staged),
                "--container-project", "/var/www/data/project",
            ], check=True, capture_output=True, text=True)

            self.assertTrue((staged / "images").is_dir())
            self.assertFalse((staged / "images").is_symlink())
            self.assertEqual(
                (staged / "opensfm" / "image_list.txt").read_text(encoding="utf-8"),
                "/var/www/data/project/images/a.jpg\n",
            )
            subprocess.run([
                "python3", str(ROOT / "validate_project.py"), "--project", str(staged),
                "--container-project", "/var/www/data/project",
                "--max-images", "10", "--max-bytes", "1000",
            ], check=True, capture_output=True, text=True)

    def test_artifact_validators(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ply = root / "scene.ply"
            ply.write_text("ply\nformat ascii 1.0\nelement vertex 1\nproperty float x\nproperty float y\nproperty float z\nend_header\n0 0 0\n", encoding="ascii")
            subprocess.run(["python3", str(ROOT / "validate_artifact.py"), "--format", "ply", "--path", str(ply)], check=True)
            splat = root / "scene.splat"
            splat.write_bytes(b"\0" * 32)
            subprocess.run(["python3", str(ROOT / "validate_artifact.py"), "--format", "splat", "--path", str(splat)], check=True)


if __name__ == "__main__":
    unittest.main()
