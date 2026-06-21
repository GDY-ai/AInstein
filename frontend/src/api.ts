import type {
  AuthResponse,
  Brain,
  BrainFrontier,
  CreateBrainResponse,
  Discovery,
  DiscoveryAction,
  DiscoverySort,
  KnowledgeGraph,
  LeaderboardResponse,
  MyAchievementsResponse,
  ObserverLog,
  PaperShare,
  ThinkingSummary,
  User,
} from './types';

const BASE = '/ainstein/api';

const TOKEN_KEY = 'ainstein.token';

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* ignore */
  }
}

const USER_KEY = 'ainstein.user';

export function getStoredUser(): User | null {
  try {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? (JSON.parse(raw) as User) : null;
  } catch {
    return null;
  }
}

export function setStoredUser(user: User | null) {
  try {
    if (user) localStorage.setItem(USER_KEY, JSON.stringify(user));
    else localStorage.removeItem(USER_KEY);
  } catch {
    /* ignore */
  }
}

async function request(path: string, opts?: RequestInit) {
  const headers: Record<string, string> = {
    ...(opts?.headers as Record<string, string> | undefined),
  };
  const token = getToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const resp = await fetch(`${BASE}${path}`, { ...opts, headers });
  if (resp.status === 401) {
    // token 失效 → 清掉
    setToken(null);
    setStoredUser(null);
  }
  if (!resp.ok) {
    const text = await resp.text();
    let msg = text;
    try {
      const obj = JSON.parse(text);
      if (obj?.error) msg = obj.error;
    } catch {
      /* keep raw */
    }
    throw new Error(msg || `${resp.status}`);
  }
  if (resp.status === 204) return null;
  return resp.json();
}

function jsonBody(data: unknown): RequestInit {
  return {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  };
}

export const api = {
  health: () => request('/health'),

  // === Auth ===
  register: (data: { username: string; password: string; email?: string }) =>
    request('/auth/register', jsonBody(data)) as Promise<AuthResponse>,
  login: (data: { username: string; password: string }) =>
    request('/auth/login', jsonBody(data)) as Promise<AuthResponse>,
  me: () => request('/auth/me') as Promise<{ user: User }>,

  // === Brains ===
  listBrains: (opts?: { all?: boolean }) =>
    request(`/brains${opts?.all ? '?all=1' : ''}`) as Promise<{ items: Brain[] }>,
  createBrain: (data: { name: string; seed_question: string; config?: object }) =>
    request('/brains', jsonBody(data)) as Promise<CreateBrainResponse>,
  getBrain: (brainId: number) =>
    request(`/brains/${brainId}`) as Promise<Brain>,
  pauseBrain: (brainId: number) =>
    request(`/brains/${brainId}/pause`, { method: 'POST' }) as Promise<{ status: string; brain: Brain }>,
  resumeBrain: (brainId: number) =>
    request(`/brains/${brainId}/resume`, { method: 'POST' }) as Promise<{ status: string; brain: Brain }>,
  stopBrain: (brainId: number) =>
    request(`/brains/${brainId}/stop`, { method: 'POST' }) as Promise<{ status: string; brain: Brain }>,

  // === Legacy projects (Phase 0~4) ===
  listProjects: () => request('/projects'),
  createProject: (data: {name: string; mission: string; domain: string; config?: object}) =>
    request('/projects', jsonBody(data)),
  getProject: (id: number) => request(`/projects/${id}`),
  getQueue: (id: number) => request(`/projects/${id}/queue`),
  addQueueItem: (id: number, data: {topic: string; priority?: number}) =>
    request(`/projects/${id}/queue`, jsonBody(data)),
  getSessions: (id: number) => request(`/projects/${id}/sessions`),
  getSession: (pid: number, sid: number) => request(`/projects/${pid}/sessions/${sid}`),
  runSession: (id: number, topic?: string) =>
    request(`/projects/${id}/sessions/run`, jsonBody({ topic })),
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

  // 硅基大脑 · 知识图谱
  getKnowledgeGraph: async (brainId: number, params?: {types?: string; limit?: number}): Promise<KnowledgeGraph> => {
    const qs = new URLSearchParams();
    if (params?.types) qs.set('types', params.types);
    if (params?.limit) qs.set('limit', String(params.limit));
    const s = qs.toString();
    const raw = await request(`/brains/${brainId}/knowledge-graph${s ? `?${s}` : ''}`);
    // 规范化字段名（后端返回格式 → 前端期望格式）
    return {
      nodes: (raw.nodes || []).map((n: any) => ({
        id: n.id,
        ce_type: n.ce_type || n.type || 'question',
        title: n.title || n.label || n.content?.slice(0, 30) || '',
        content: n.content || '',
        confidence: n.confidence ?? 0.5,
        status: n.status || 'open',
        created_at: n.created_at || '',
        metadata: n.metadata || n.domain_tags || '',
      })),
      edges: (raw.edges || []).map((e: any) => ({
        id: e.id,
        source_id: e.source_id ?? e.source,
        target_id: e.target_id ?? e.target,
        relation_type: e.relation_type || e.relation || 'relates_to',
        weight: e.weight ?? e.strength ?? 0.5,
      })),
      total_nodes: typeof raw.total_nodes === 'number' ? raw.total_nodes : undefined,
      total_edges: typeof raw.total_edges === 'number' ? raw.total_edges : undefined,
    };
  },
  getBrainFrontier: (brainId: number, params?: {limit?: number; confidence_ceiling?: number}): Promise<BrainFrontier> => {
    const qs = new URLSearchParams();
    if (params?.limit) qs.set('limit', String(params.limit));
    if (params?.confidence_ceiling !== undefined) qs.set('confidence_ceiling', String(params.confidence_ceiling));
    const s = qs.toString();
    return request(`/brains/${brainId}/frontier${s ? `?${s}` : ''}`);
  },

  // 硅基大脑 · 观察员视角
  getObserverLogs: async (brainId: number, params?: { kind?: string; limit?: number }) => {
    const qs = new URLSearchParams();
    if (params?.kind) qs.set('kind', params.kind);
    if (params?.limit) qs.set('limit', String(params.limit));
    const s = qs.toString();
    return request(`/brains/${brainId}/observer-logs${s ? `?${s}` : ''}`) as Promise<{ items: ObserverLog[]; limit: number; kind: string | null }>;
  },
  getLatestObserverLog: async (brainId: number) => {
    return request(`/brains/${brainId}/observer-logs/latest`) as Promise<ObserverLog | null>;
  },
  generateObserverSummary: async (brainId: number, data?: { reason?: string; force?: boolean }) => {
    return request(`/brains/${brainId}/observer-logs/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data || {}),
    });
  },

  // 硅基大脑 · 思考总结（"想明白了什么"）
  getThinkingSummary: async (brainId: number): Promise<ThinkingSummary | null> => {
    const res = await request(`/brains/${brainId}/thinking-summary`) as any;
    return res?.summary || null;
  },

  // === 发现社区 ===
  listDiscoveries: (sort: DiscoverySort = 'hot', limit = 50, offset = 0) => {
    const qs = new URLSearchParams({ sort, limit: String(limit), offset: String(offset) });
    return request(`/discoveries?${qs.toString()}`) as Promise<{
      items: Discovery[];
      sort: DiscoverySort;
      limit: number;
      offset: number;
    }>;
  },
  likeDiscovery: (id: number) =>
    request(`/discoveries/${id}/like`, { method: 'POST' }) as Promise<{ status: string; liked: boolean }>,
  saveDiscovery: (id: number) =>
    request(`/discoveries/${id}/save`, { method: 'POST' }) as Promise<{ status: string; saved: boolean }>,
  myDiscoveries: () =>
    request('/discoveries/mine') as Promise<{ items: Discovery[] }>,
  myDiscoveryActions: () =>
    request('/discoveries/actions') as Promise<{ actions: DiscoveryAction[] }>,

  // === 管理员运营仪表盘（需 admin 角色）===
  adminStatsOverview: () => request('/admin/stats/overview') as Promise<any>,
  adminStatsTrends: () => request('/admin/stats/trends') as Promise<any>,
  adminStatsLeaderboard: () => request('/admin/stats/leaderboard') as Promise<any>,

  // === 用户成就与公开排行榜（Task #6）===
  getMyAchievements: () =>
    request('/users/me/achievements') as Promise<MyAchievementsResponse>,
  getLeaderboard: () =>
    request('/leaderboard') as Promise<LeaderboardResponse>,
};

// 命名导出方便直接 import
export const fetchKnowledgeGraph = (brainId: number) => api.getKnowledgeGraph(brainId);
export const fetchBrainFrontier = (brainId: number) => api.getBrainFrontier(brainId);

// 研究报告生成
export async function generatePaper(brainId: number): Promise<{ task_id: string; status: string }> {
  return request(`/brains/${brainId}/generate-paper`, { method: 'POST' });
}

export async function getPaperStatus(brainId: number, taskId: string): Promise<{ status: string; progress?: string; download_url?: string; error?: string }> {
  return request(`/brains/${brainId}/paper-status/${taskId}`);
}

// 论文公开分享
export async function sharePaper(brainId: number): Promise<PaperShare> {
  return request(`/brains/${brainId}/share`, { method: 'POST' });
}
