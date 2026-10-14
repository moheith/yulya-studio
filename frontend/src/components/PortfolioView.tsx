import React, { useState } from 'react';
import { Project, User } from '../types';
import {
  User as UserIcon,
  Plus,
  Trash2,
  ExternalLink,
  UploadCloud,
  Code,
  Calendar,
  Layers,
} from 'lucide-react';

interface PortfolioViewProps {
  currentUser: User | null;
  projects: Project[];
  onOpenProject: (p: Project) => void;
  onNewProject: () => void;
  onDeleteProject: (slug: string) => void;
  onPublishRelease: (slug: string) => void;
}

export const PortfolioView: React.FC<PortfolioViewProps> = ({
  currentUser,
  projects,
  onOpenProject,
  onNewProject,
  onDeleteProject,
  onPublishRelease,
}) => {
  const [publishingSlug, setPublishingSlug] = useState<string | null>(null);
  const [changelog, setChangelog] = useState('Production release');

  const username = currentUser?.username || 'creator';

  return (
    <div
      style={{
        flex: 1,
        height: '100%',
        overflowY: 'auto',
        backgroundColor: 'var(--bg-deepest)',
        padding: '32px 40px',
        display: 'flex',
        flexDirection: 'column',
        gap: '24px',
      }}
    >
      {/* Profile Header */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          backgroundColor: 'var(--bg-elevated)',
          border: '1px solid var(--border-subtle)',
          borderRadius: '12px',
          padding: '24px',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          <div
            style={{
              width: '64px',
              height: '64px',
              borderRadius: '50%',
              backgroundColor: 'var(--bg-surface)',
              border: '2px solid var(--accent-primary)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: 'var(--accent-primary)',
            }}
          >
            <UserIcon size={32} />
          </div>
          <div>
            <h1 style={{ fontSize: '22px', fontWeight: 700 }}>
              @{username}
            </h1>
            <p style={{ color: 'var(--text-secondary)', fontSize: '13px', marginTop: '4px' }}>
              Game Creator & AI Studio Developer • {projects.length} Repositories
            </p>
          </div>
        </div>

        <button
          onClick={onNewProject}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            backgroundColor: 'var(--accent-primary)',
            color: '#ffffff',
            border: 'none',
            borderRadius: '8px',
            padding: '10px 18px',
            fontWeight: 600,
            fontSize: '13px',
            cursor: 'pointer',
            boxShadow: '0 4px 14px rgba(139, 92, 246, 0.3)',
          }}
        >
          <Plus size={16} />
          <span>New Game Project</span>
        </button>
      </div>

      {/* Projects List */}
      <div>
        <h2 style={{ fontSize: '18px', fontWeight: 700, marginBottom: '16px' }}>
          Repositories
        </h2>

        {projects.length === 0 ? (
          <div
            style={{
              padding: '48px',
              textAlign: 'center',
              backgroundColor: 'var(--bg-base)',
              border: '1px solid var(--border-subtle)',
              borderRadius: '12px',
              color: 'var(--text-secondary)',
            }}
          >
            <Layers size={32} style={{ opacity: 0.5, marginBottom: '8px' }} />
            <div style={{ fontWeight: 600, fontSize: '15px' }}>No projects found</div>
            <p style={{ fontSize: '13px', marginTop: '4px' }}>
              Create your first game to start building with Yulya.
            </p>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            {projects.map((p) => (
              <div
                key={p.slug}
                style={{
                  backgroundColor: 'var(--bg-elevated)',
                  border: '1px solid var(--border-subtle)',
                  borderRadius: '10px',
                  padding: '16px 20px',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                }}
              >
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <span
                      onClick={() => onOpenProject(p)}
                      style={{
                        fontSize: '16px',
                        fontWeight: 700,
                        color: 'var(--accent-blue)',
                        cursor: 'pointer',
                      }}
                    >
                      {p.title}
                    </span>
                    <span
                      style={{
                        fontSize: '11px',
                        fontFamily: 'var(--font-mono)',
                        color: 'var(--text-tertiary)',
                      }}
                    >
                      /{p.slug}
                    </span>
                    <span
                      style={{
                        fontSize: '10px',
                        padding: '2px 6px',
                        borderRadius: '4px',
                        backgroundColor: p.is_public
                          ? 'rgba(52, 211, 153, 0.1)'
                          : 'rgba(251, 191, 36, 0.1)',
                        color: p.is_public ? 'var(--accent-green)' : 'var(--accent-amber)',
                        border: `1px solid ${p.is_public ? 'rgba(52, 211, 153, 0.2)' : 'rgba(251, 191, 36, 0.2)'}`,
                      }}
                    >
                      {p.is_public ? 'Public' : 'Draft'}
                    </span>
                  </div>

                  <p
                    style={{
                      fontSize: '13px',
                      color: 'var(--text-secondary)',
                      marginTop: '6px',
                    }}
                  >
                    {p.description || 'Canvas game created in Yulya Studio.'}
                  </p>
                </div>

                {/* Actions */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <button
                    onClick={() => onOpenProject(p)}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '4px',
                      backgroundColor: 'var(--bg-surface)',
                      border: '1px solid var(--border-subtle)',
                      color: 'var(--text-primary)',
                      padding: '6px 12px',
                      borderRadius: '6px',
                      fontSize: '12px',
                      fontWeight: 600,
                      cursor: 'pointer',
                    }}
                  >
                    <Code size={13} color="var(--accent-primary)" />
                    <span>Open in IDE</span>
                  </button>

                  <button
                    onClick={() => setPublishingSlug(p.slug)}
                    title="Publish Release"
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '4px',
                      backgroundColor: 'rgba(52, 211, 153, 0.1)',
                      border: '1px solid var(--accent-green)',
                      color: 'var(--accent-green)',
                      padding: '6px 12px',
                      borderRadius: '6px',
                      fontSize: '12px',
                      fontWeight: 600,
                      cursor: 'pointer',
                    }}
                  >
                    <UploadCloud size={13} />
                    <span>Publish</span>
                  </button>

                  <button
                    onClick={() => {
                      if (confirm(`Delete project '${p.title}'? This cannot be undone.`)) {
                        onDeleteProject(p.slug);
                      }
                    }}
                    title="Delete project"
                    style={{
                      background: 'transparent',
                      border: 'none',
                      color: 'var(--text-tertiary)',
                      padding: '6px',
                      cursor: 'pointer',
                    }}
                  >
                    <Trash2 size={15} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Publish Release Modal */}
      {publishingSlug && (
        <div
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: 'rgba(5, 1, 16, 0.85)',
            backdropFilter: 'blur(6px)',
            display: 'flex',
            justifyContent: 'center',
            alignItems: 'center',
            zIndex: 100,
          }}
          onClick={() => setPublishingSlug(null)}
        >
          <div
            style={{
              width: '420px',
              backgroundColor: 'var(--bg-elevated)',
              border: '1px solid var(--border-active)',
              borderRadius: '12px',
              padding: '24px',
              display: 'flex',
              flexDirection: 'column',
              gap: '16px',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <h3 style={{ fontSize: '17px', fontWeight: 700 }}>
              Publish Release for /{publishingSlug}
            </h3>
            <p style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
              Publishing creates an immutable snapshot of your current game files and updates the public arcade URL.
            </p>

            <div>
              <label style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)' }}>
                Changelog Note
              </label>
              <input
                type="text"
                value={changelog}
                onChange={(e) => setChangelog(e.target.value)}
                style={{
                  width: '100%',
                  marginTop: '6px',
                  backgroundColor: 'var(--bg-deepest)',
                  border: '1px solid var(--border-subtle)',
                  borderRadius: '6px',
                  padding: '8px 12px',
                  color: 'var(--text-primary)',
                  fontSize: '13px',
                  outline: 'none',
                }}
              />
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px', marginTop: '8px' }}>
              <button
                onClick={() => setPublishingSlug(null)}
                style={{
                  backgroundColor: 'transparent',
                  border: '1px solid var(--border-subtle)',
                  color: 'var(--text-secondary)',
                  padding: '8px 14px',
                  borderRadius: '6px',
                  fontSize: '13px',
                  cursor: 'pointer',
                }}
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  onPublishRelease(publishingSlug);
                  setPublishingSlug(null);
                }}
                style={{
                  backgroundColor: 'var(--accent-primary)',
                  color: '#ffffff',
                  border: 'none',
                  padding: '8px 16px',
                  borderRadius: '6px',
                  fontSize: '13px',
                  fontWeight: 600,
                  cursor: 'pointer',
                }}
              >
                Publish Now
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
