// Thin typed client over the backend API. All calls are same-origin /api/*
// (proxied to FastAPI by next.config.ts rewrites).

import type {
  AgentResponse, ChatTurn, Clip, Job, MediaAsset, Project,
} from "./types";

class ApiError extends Error {
  constructor(public status: number, detail: string) {
    super(detail);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch { /* non-JSON error body */ }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  // media
  listMedia: () => request<MediaAsset[]>("/api/media"),
  // XHR instead of fetch: fetch has no upload-progress events, and visible
  // progress is what stops large uploads from feeling stuck.
  uploadMedia(file: File, onProgress?: (fraction: number) => void) {
    return new Promise<MediaAsset>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/media");
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total);
      };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(JSON.parse(xhr.responseText));
        } else {
          let detail = xhr.statusText || `Upload failed (${xhr.status})`;
          try {
            const body = JSON.parse(xhr.responseText);
            if (typeof body.detail === "string") detail = body.detail;
          } catch { /* non-JSON error body */ }
          reject(new ApiError(xhr.status, detail));
        }
      };
      xhr.onerror = () => reject(new ApiError(0, "Upload failed: network error"));
      const form = new FormData();
      form.append("file", file);
      xhr.send(form);
    });
  },
  deleteMedia: (id: string) => request<void>(`/api/media/${id}`, { method: "DELETE" }),
  mediaFileUrl: (id: string) => `/api/media/${id}/file`,
  thumbnailUrl: (id: string) => `/api/media/${id}/thumbnail`,

  // projects
  listProjects: () => request<Project[]>("/api/projects"),
  createProject: (name: string) => request<Project>("/api/projects", json("POST", { name })),
  getProject: (id: string) => request<Project>(`/api/projects/${id}`),
  updateTimeline: (id: string, clips: Clip[]) =>
    request<Project>(`/api/projects/${id}/timeline`, json("PUT", { clips })),
  deleteProject: (id: string) => request<void>(`/api/projects/${id}`, { method: "DELETE" }),

  // export jobs
  startExport: (projectId: string) =>
    request<Job>(`/api/projects/${projectId}/export`, { method: "POST" }),
  getJob: (jobId: string) => request<Job>(`/api/jobs/${jobId}`),
  listJobs: (projectId: string) => request<Job[]>(`/api/projects/${projectId}/jobs`),
  downloadUrl: (jobId: string) => `/api/jobs/${jobId}/download`,

  // agent
  sendAgentMessage: (projectId: string, message: string, history: ChatTurn[] = []) =>
    request<AgentResponse>(`/api/projects/${projectId}/agent`, json("POST", { message, history })),
};

export { ApiError };
