"""Tests for the Model Service."""

import io
import shutil
import tarfile

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def model_dir(tmp_path):
    import app

    app.MODEL_DIR = tmp_path
    return tmp_path


@pytest.fixture(autouse=True)
def reset_state(model_dir):
    import app

    if model_dir.exists():
        shutil.rmtree(model_dir)
    model_dir.mkdir(parents=True)
    app._cached_hash = None
    yield


@pytest.fixture
def client():
    from app import app

    return TestClient(app)


def make_tar_gz(files: dict[str, bytes]) -> io.BytesIO:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    buf.seek(0)
    return buf


@pytest.fixture
def sample_tar():
    return make_tar_gz({
        "config.json": b'{"model_type": "test"}',
        "model.safetensors": b"\x00" * 1024,
    })


class TestHealth:
    def test_no_model(self, client):
        data = client.get("/health").json()
        assert data["status"] == "healthy"
        assert data["model_pushed"] is False

    def test_with_model(self, client, model_dir, sample_tar):
        client.post("/push-model", files={"file": ("m.tar.gz", sample_tar)})
        assert client.get("/health").json()["model_pushed"] is True


class TestPushModel:
    def test_push_ok(self, client, model_dir, sample_tar):
        resp = client.post("/push-model", files={"file": ("model.tar.gz", sample_tar)})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert (model_dir / "config.json").exists()
        assert (model_dir / "model.safetensors").exists()

    def test_push_rejected_after_first(self, client, model_dir, sample_tar):
        client.post("/push-model", files={"file": ("model.tar.gz", sample_tar)})
        resp = client.post("/push-model", files={"file": ("model.tar.gz", sample_tar)})
        assert resp.status_code == 410

    def test_push_invalid_archive(self, client, model_dir):
        resp = client.post("/push-model", files={"file": ("bad.tar.gz", io.BytesIO(b"not a tar"))})
        assert resp.status_code == 400
        from utils import model_pushed
        assert not model_pushed(model_dir)

    def test_push_with_expected_hash(self, client, model_dir):
        tar1 = make_tar_gz({"a.txt": b"hello"})
        client.post("/push-model", files={"file": ("m.tar.gz", tar1)})
        correct_hash = client.get("/model-hash").json()["hash"]

        # Clean and push again with expected_hash
        shutil.rmtree(model_dir)
        model_dir.mkdir()
        import app
        app._cached_hash = None

        tar2 = make_tar_gz({"a.txt": b"hello"})
        resp = client.post(
            "/push-model",
            files={"file": ("m.tar.gz", tar2)},
            data={"expected_hash": correct_hash},
        )
        assert resp.status_code == 200

    def test_push_with_wrong_hash(self, client, model_dir):
        tar = make_tar_gz({"a.txt": b"hello"})
        resp = client.post(
            "/push-model",
            files={"file": ("m.tar.gz", tar)},
            data={"expected_hash": "sha256:0000000000000000000000000000000000000000000000000000000000000000"},
        )
        assert resp.status_code == 400
        assert "mismatch" in resp.json()["detail"].lower()


class TestModelHash:
    def test_no_model(self, client):
        assert client.get("/model-hash").status_code == 404

    def test_after_push(self, client, model_dir, sample_tar):
        client.post("/push-model", files={"file": ("m.tar.gz", sample_tar)})
        resp = client.get("/model-hash")
        assert resp.status_code == 200
        data = resp.json()
        assert data["hash"].startswith("sha256:")
        assert data["algorithm"] == "sha256"
        assert len(data["files"]) == 2

    def test_deterministic(self, client, model_dir, sample_tar):
        client.post("/push-model", files={"file": ("m.tar.gz", sample_tar)})
        h1 = client.get("/model-hash").json()["hash"]
        h2 = client.get("/model-hash").json()["hash"]
        assert h1 == h2

    def test_ignores_temp_files(self, client, model_dir, sample_tar):
        client.post("/push-model", files={"file": ("m.tar.gz", sample_tar)})
        (model_dir / ".DS_Store").write_bytes(b"junk")
        (model_dir / "x.tmp").write_bytes(b"junk")
        resp = client.get("/model-hash")
        assert len(resp.json()["files"]) == 2
