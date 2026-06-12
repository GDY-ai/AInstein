const BASE = '/ainstein/api';

async function request(path: string, opts?: RequestInit) {
  const resp = await fetch(`${BASE}${path}`, opts);
  if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`);
  return resp.json();
}

export const api = {
  health: () => request('/health'),
  listProjects: () => request('/projects'),
  createProject: (data: {name: string; mission: string; domain: string; config?: object}) =>
    request('/projects', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)}),
  getProject: (id: number) => request(`/projects/${id}`),
  getQueue: (id: number) => request(`/projects/${id}/queue`),
  addQueueItem: (id: number, data: {topic: string; priority?: number}) =>
    request(`/projects/${id}/queue`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)}),
  getSessions: (id: number) => request(`/projects/${id}/sessions`),
  getSession: (pid: number, sid: number) => request(`/projects/${pid}/sessions/${sid}`),
  runSession: (id: number, topic?: string) =>
    request(`/projects/${id}/sessions/run`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({topic})}),
  getFindings: (id: number, params?: {status?: string; category?: string; limit?: number}) => {
    const qs = new URLSearchParams();
    if (params?.status) qs.set('status', params.status);
    if (params?.category) qs.set('category', params.category);
    qs.set('limit', String(params?.limit || 50));
    return request(`/projects/${id}/findings?${qs}`);
  },
  getDatasets: (id: number) => request(`/projects/${id}/datasets`),
  uploadDataset: (id: number, file: File) => {
    const fd = new FormData();
    fd.append('file', file);
    return request(`/projects/${id}/datasets/upload`, {method: 'POST', body: fd});
  },
  getDirectives: (id: number) => request(`/projects/${id}/directives`),
  getMemory: (id: number, kind?: string) => {
    const qs = kind ? `?kind=${kind}` : '';
    return request(`/projects/${id}/memory${qs}`);
  },
  runScientist: (id: number) =>
    request(`/projects/${id}/scientist/run`, {method: 'POST'}),
  runDirector: (id: number) =>
    request(`/projects/${id}/director/run`, {method: 'POST'}),
};
