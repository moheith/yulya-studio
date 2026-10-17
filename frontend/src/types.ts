export interface User {
  id: number;
  username: string;
  display_name?: string;
  avatar?: string;
}

export interface Project {
  slug: string;
  title: string;
  description: string;
  files: string[];
  tags: string[];
  is_public: boolean;
  username?: string;
  user_id?: number;
  updated_at?: string;
  created_at?: string;
  views?: number;
  plays?: number;
}

export interface ProjectFileEntry {
  path: string;
  name: string;
  size: number;
  is_dir: boolean;
  extension: string;
}

export interface ManifestSystem {
  id: string;
  description: string;
}

export interface ProjectManifest {
  schema_version: string;
  slug: string;
  title: string;
  genre: string;
  engine: string;
  entrypoint: string;
  systems: (string | ManifestSystem)[];
  controls: Record<string, string> | string[];
  design_decisions: string[];
  known_bugs: string[];
  build_number?: number;
  build_status?: string;
}

export type BuildStage =
  | 'ACCEPTED'
  | 'INSPECTING'
  | 'PLANNING'
  | 'EDITING'
  | 'VALIDATING'
  | 'PREVIEW_READY'
  | 'SUCCEEDED'
  | 'FAILED'
  | 'CANCELLED';

export interface BuildProgressEvent {
  event_id: string;
  request_id: string;
  build_id: string;
  stage: BuildStage;
  message: string;
  timestamp: number;
  files_changed?: string[];
  diffs?: Record<string, string>;
  actual_model?: string;
  error?: string;
}

export type LiveSessionState =
  | 'DISCONNECTED'
  | 'CONNECTING'
  | 'CONNECTED'
  | 'LISTENING'
  | 'SPEAKING'
  | 'THINKING'
  | 'TOOL_RUNNING'
  | 'INTERRUPTED'
  | 'FALLING_BACK'
  | 'ERROR';

export interface ActivityLog {
  id: string;
  timestamp: string;
  level: 'info' | 'success' | 'warning' | 'error' | 'ai' | 'tool';
  message: string;
}

export interface ModelEntry {
  id: string;
  display_name: string;
  family: string;
  description: string;
  supports_live: boolean;
  supports_code_generation: boolean;
  recommended: boolean;
}

export interface ToastItem {
  id: string;
  type: 'info' | 'success' | 'warning' | 'error';
  message: string;
}
