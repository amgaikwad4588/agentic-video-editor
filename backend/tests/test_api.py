"""API integration tests: media, projects, timeline, export jobs."""

import time

from tests.conftest import register_asset


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ---- media -----------------------------------------------------------------

def test_upload_and_list_media(client, sample_clip):
    with sample_clip.open("rb") as f:
        r = client.post("/api/media", files={"file": ("myvideo.mp4", f, "video/mp4")})
    assert r.status_code == 201, r.text
    asset = r.json()
    assert asset["filename"] == "myvideo.mp4"
    assert asset["media_type"] == "video"
    assert 1.5 < asset["duration"] < 2.5

    r = client.get("/api/media")
    assert any(a["id"] == asset["id"] for a in r.json())

    # thumbnail was generated for the video
    r = client.get(f"/api/media/{asset['id']}/thumbnail")
    assert r.status_code == 200

    # raw file is served
    r = client.get(f"/api/media/{asset['id']}/file")
    assert r.status_code == 200


def test_upload_rejects_bad_extension(client):
    r = client.post("/api/media", files={"file": ("evil.exe", b"MZ", "application/exe")})
    assert r.status_code == 415


def test_upload_rejects_garbage_content(client):
    r = client.post("/api/media", files={"file": ("fake.mp4", b"not a video", "video/mp4")})
    assert r.status_code == 422


# ---- projects & timeline ---------------------------------------------------

def test_project_crud(client):
    r = client.post("/api/projects", json={"name": "My Film"})
    assert r.status_code == 201
    pid = r.json()["id"]

    assert client.get(f"/api/projects/{pid}").json()["name"] == "My Film"
    assert any(p["id"] == pid for p in client.get("/api/projects").json())

    assert client.delete(f"/api/projects/{pid}").status_code == 204
    assert client.get(f"/api/projects/{pid}").status_code == 404


def test_timeline_update_validates_assets(client, db_session, sample_clip):
    asset = register_asset(db_session, sample_clip)
    pid = client.post("/api/projects", json={"name": "T"}).json()["id"]

    ok = client.put(f"/api/projects/{pid}/timeline", json={
        "clips": [{"asset_id": asset.id, "start": 0.0, "end": 1.0}],
    })
    assert ok.status_code == 200
    assert len(ok.json()["timeline"]["clips"]) == 1

    bad = client.put(f"/api/projects/{pid}/timeline", json={
        "clips": [{"asset_id": "does-not-exist", "start": 0}],
    })
    assert bad.status_code == 422


# ---- export jobs -------------------------------------------------------------

def test_export_empty_timeline_rejected(client):
    pid = client.post("/api/projects", json={"name": "E"}).json()["id"]
    r = client.post(f"/api/projects/{pid}/export")
    assert r.status_code == 422


def test_export_job_lifecycle(client, db_session, sample_clip):
    """Queue a real 1s render and poll it to completion."""
    asset = register_asset(db_session, sample_clip)
    pid = client.post("/api/projects", json={"name": "Render"}).json()["id"]
    client.put(f"/api/projects/{pid}/timeline", json={
        "clips": [{"asset_id": asset.id, "start": 0.0, "end": 1.0}],
    })

    r = client.post(f"/api/projects/{pid}/export")
    assert r.status_code == 202
    job_id = r.json()["id"]

    deadline = time.time() + 120
    status = "queued"
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        status = job["status"]
        if status in ("done", "failed"):
            break
        time.sleep(0.5)

    assert status == "done", f"job ended as {status}: {job.get('error')}"
    assert job["progress"] == 1.0

    dl = client.get(f"/api/jobs/{job_id}/download")
    assert dl.status_code == 200
    assert len(dl.content) > 0
    assert any(j["id"] == job_id for j in client.get(f"/api/projects/{pid}/jobs").json())


def test_download_before_done_conflicts(client, db_session, sample_clip):
    asset = register_asset(db_session, sample_clip)
    pid = client.post("/api/projects", json={"name": "R2"}).json()["id"]
    client.put(f"/api/projects/{pid}/timeline", json={
        "clips": [{"asset_id": asset.id, "start": 0.0, "end": 0.5}],
    })
    job_id = client.post(f"/api/projects/{pid}/export").json()["id"]
    r = client.get(f"/api/jobs/{job_id}/download")
    assert r.status_code in (409, 200)  # 200 only if the tiny render already finished
