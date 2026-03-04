"""Tests for the Model Service."""

import io
import tarfile

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def reset_state():
    import model_service

    model_service._model_pushed = False
    yield


@pytest.fixture
def client():
    from model_service import app

    return TestClient(app)


@pytest.fixture
def model_dir(tmp_path):
    import model_service

    model_service.MODEL_DIR = tmp_path
    return tmp_path


def make_tar_gz(files: dict[str, bytes]) -> io.BytesIO:
    """Create an in-memory tar.gz from {name: content}."""
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

    def test_with_model(self, client):
        import model_service

        model_service._model_pushed = True
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
        assert resp.status_code == 403

    def test_push_invalid_archive(self, client, model_dir):
        resp = client.post("/push-model", files={"file": ("bad.tar.gz", io.BytesIO(b"not a tar"))})
        assert resp.status_code == 400
        import model_service
        assert model_service._model_pushed is False  # reset on failure

    def test_push_with_expected_hash(self, client, model_dir):
        # Push once to get the hash
        tar1 = make_tar_gz({"a.txt": b"hello"})
        client.post("/push-model", files={"file": ("m.tar.gz", tar1)})
        hash_resp = client.get("/model-hash")
        correct_hash = hash_resp.json()["hash"]

        # Reset and push again with expected_hash
        import model_service
        model_service._model_pushed = False

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
        assert len(resp.json()["files"]) == 2  # ignored
