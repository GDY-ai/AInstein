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
