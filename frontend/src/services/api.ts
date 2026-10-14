import { Project, ModelEntry } from '../types';

export async function fetchHealth(): Promise<any> {
  const res = await fetch('/api/health');
  return res.json();
}

export async function fetchModels(): Promise<{ live_models: ModelEntry[]; code_models: ModelEntry[] }> {
  const res = await fetch('/api/models');
  return res.json();
}

export async function fetchMyProjects(): Promise<{ success: boolean; projects: Project[] }> {
  const res = await fetch('/api/my-projects');
  if (!res.ok) throw new Error('Failed to load projects');
  return res.json();
}

export async function createProject(title: string, description = ''): Promise<any> {
  const res = await fetch('/api/create-project', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title, description }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.message || 'Failed to create project');
  return data;
}

export async function deleteProject(slug: string): Promise<any> {
  const res = await fetch('/api/delete-project', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ slug }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.message || 'Failed to delete project');
  return data;
}

export async function fetchProjectFiles(slug: string): Promise<{
  success: boolean;
  files: Record<string, string>;
  tree: any[];
  manifest: any;
}> {
  const res = await fetch(`/api/project-files/${encodeURIComponent(slug)}`);
  if (!res.ok) throw new Error('Failed to load project files');
  return res.json();
}

export async function saveProjectFile(slug: string, filePath: string, content: string): Promise<any> {
  const res = await fetch('/api/save-file', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ slug, file_path: filePath, content }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.message || 'Failed to save file');
  return data;
}

export async function modifyProject(slug: string, prompt: string, requestedModel?: string): Promise<any> {
  const res = await fetch('/api/modify-project', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ slug, prompt, requested_model: requestedModel }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.message || 'Failed to dispatch modification');
  return data;
}

export async function publishRelease(slug: string, title?: string, description?: string, changelog?: string): Promise<any> {
  const res = await fetch('/api/releases/publish', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ slug, title, description, changelog }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.message || 'Failed to publish release');
  return data;
}

export async function saveApiKey(apiKey: string): Promise<any> {
  const res = await fetch('/api/save-key', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ api_key: apiKey }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.message || 'Failed to verify API key');
  return data;
}

export async function fetchCommunityProjects(): Promise<{ success: boolean; projects: Project[] }> {
  const res = await fetch('/api/community-projects');
  if (!res.ok) throw new Error('Failed to load community arcade');
  return res.json();
}

export async function fetchCreatorProfile(username: string): Promise<{ success: boolean; profile: any }> {
  const res = await fetch(`/api/profile/${encodeURIComponent(username)}`);
  if (!res.ok) throw new Error('Failed to load creator profile');
  return res.json();
}
