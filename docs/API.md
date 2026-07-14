# API Reference

Base URL: `http://localhost:8000`. Interactive docs at `/docs` (Swagger UI).

## Health
| Method | Path | Notes |
|---|---|---|
| GET | `/api/health` | liveness probe |

## Media
| Method | Path | Notes |
|---|---|---|
| POST | `/api/media` | multipart upload (`file`); probes + thumbnails; 201 → `MediaAsset` |
| GET | `/api/media` | list assets, newest first |
| GET | `/api/media/{id}/file` | raw media file (used by the preview player) |
| GET | `/api/media/{id}/thumbnail` | JPEG thumbnail (videos only) |
| DELETE | `/api/media/{id}` | 204 |

Errors: `415` bad extension, `413` over size limit, `422` not a valid media file.

## Projects & timeline
| Method | Path | Notes |
|---|---|---|
| POST | `/api/projects` | `{"name": "..."}` → 201 |
| GET | `/api/projects` | list |
| GET | `/api/projects/{id}` | includes `timeline` |
| PUT | `/api/projects/{id}/timeline` | `{"clips": [Clip...]}`; 422 on unknown asset ids |
| DELETE | `/api/projects/{id}` | 204 |

`Clip`: `{id?, asset_id, start, end|null, speed, volume, overlays: [TextOverlay...]}`

## Export jobs
| Method | Path | Notes |
|---|---|---|
| POST | `/api/projects/{id}/export` | 202 → `Job` (poll it) |
| GET | `/api/jobs/{job_id}` | `status`: queued/running/done/failed, `progress`: 0..1 |
| GET | `/api/projects/{id}/jobs` | job history |
| GET | `/api/jobs/{job_id}/download` | 200 mp4; 409 while not done |

## Agent
| Method | Path | Notes |
|---|---|---|
| POST | `/api/projects/{id}/agent` | `{"message": "cut the first 10 seconds and add a title"}` |

Response:
```json
{
  "reply": "I trimmed the clip to start at 10s and added the title.",
  "actions": [{"tool": "trim_clip", "input": {...}, "result": "..."}],
  "timeline": {"clips": [...]}
}
```
Errors: `503` no/invalid `ANTHROPIC_API_KEY`, `429` model rate limit,
`502` upstream API failure, `422` agent could not complete.
