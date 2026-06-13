export interface Project {
  id: number;
  name: string;
  mission: string;
  domain: string;
  config_json: string;
  status: string;
  created_at: string;
  stats?: ProjectStats;
}

export interface ProjectStats {
  sessions_total: number;
  sessions_completed: number;
  findings_total: number;
  findings_actionable: number;
  findings_validated: number;
  queue_pending: number;
}

export interface QueueItem {
  id: number;
  project_id: number;
  topic: string;
  priority: number;
  source: string;
  status: string;
  created_at: string;
}

export interface Session {
  id: number;
  project_id: number;
  topic: string;
  engine_type: string;
  status: string;
  hypotheses: string;
  verification: string;
  findings: string;
  next_directions: string;
  data_summary: string;
  duration_seconds: number;
  created_at: string;
}

export interface Finding {
  id: number;
  project_id: number;
  session_id: number;
  session_topic: string;
  finding: string;
  category: string;
  confidence: string;
  evidence: string;
  actionable: number;
  action_suggestion: string;
  status: string;
  created_at: string;
}

export interface Dataset {
  id: number;
  project_id: number;
  name: string;
  source: string;
  schema_json: string;
  row_count: number;
  status: string;
  created_at: string;
}

export interface Directive {
  id: number;
  project_id: number;
  directive: string;
  priority: number;
  status: string;
  created_at: string;
}

export interface MemoryEntry {
  id: number;
  project_id: number;
  kind: string;
  content: string;
  context_data: string;
  created_at: string;
}

// === 硅基大脑用户与大脑 ===

export interface User {
  id: number;
  username: string;
  email: string | null;
  role: 'user' | 'admin' | string;
  status: string;
  created_at: string;
}

export interface Brain {
  id: number;
  name: string;
  seed_question: string;
  owner_user_id: number;
  state: 'gestating' | 'active' | 'paused' | 'archived' | string;
  config_json: string;
  config?: Record<string, unknown>;
  frontier_score: number;
  created_at: string;
  started_at: string | null;
  last_active_at: string | null;
  agent_count?: number;
  ce_count?: number;
}

export interface AuthResponse {
  token: string;
  user: User;
}

export interface CreateBrainResponse {
  brain: Brain;
  seed_ce: { id: number; type: string; content: string } | null;
  initial_agents: { instance_id: number; role: string }[];
}

// ===== 硅基大脑 · 认知图谱 =====

export type CECategory =
  | 'observation' | 'question' | 'hypothesis' | 'evidence'
  | 'counter_evidence' | 'inference' | 'argument' | 'conclusion'
  | 'perspective' | 'insight' | 'consensus' | 'dissent' | string;

export interface CognitiveNode {
  id: number;
  ce_type: CECategory;
  title: string;
  content: string;
  confidence: number;
  status: string;
  created_at: string;
  metadata: string;
}

export interface CognitiveEdge {
  id: number;
  source_id: number;
  target_id: number;
  relation_type: string;
  weight: number;
}

export interface KnowledgeGraph {
  nodes: CognitiveNode[];
  edges: CognitiveEdge[];
  /** 数据库中认知元素总数（不受 limit 截断影响） */
  total_nodes?: number;
  /** 数据库中认知关系总数 */
  total_edges?: number;
}

export interface BrainFrontier {
  recent: CognitiveNode[];
  low_confidence: CognitiveNode[];
  unsupported: CognitiveNode[];
}

// ===== 硅基大脑 · 观察员视角 =====

export interface ObserverLogBody {
  narrative: string;
  main_directions: string[];
  key_developments: Array<{ summary: string; cited_ce_ids: number[] }>;
  deliberation_dynamics?: string;
  frontier_movement?: string;
  health_assessment?: string;
  importance: number;
}

export interface ObserverLog {
  id: number;
  brain_id: number;
  kind: 'summary' | 'alert' | 'milestone' | string;
  title: string;
  body: string;
  body_struct?: ObserverLogBody;
  cited_ce_ids: number[];
  pushed: number;
  created_at: string;
}
