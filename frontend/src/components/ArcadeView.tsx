import React, { useState } from 'react';
import { Project } from '../types';
import { Gamepad2, Search, Play, User, ExternalLink } from 'lucide-react';

interface ArcadeViewProps {
  projects: Project[];
  onPlayInStudio: (p: Project) => void;
}

export const ArcadeView: React.FC<ArcadeViewProps> = ({ projects, onPlayInStudio }) => {
  const [search, setSearch] = useState('');
  const [activeTag, setActiveTag] = useState<string>('all');
  const [selectedGame, setSelectedGame] = useState<Project | null>(null);

  const tags = ['all', 'arcade', 'canvas', 'retro', 'action', 'puzzle'];

  const filtered = projects.filter((p) => {
    const matchesSearch =
      p.title.toLowerCase().includes(search.toLowerCase()) ||
      p.slug.toLowerCase().includes(search.toLowerCase()) ||
      (p.description && p.description.toLowerCase().includes(search.toLowerCase()));

    const matchesTag =
      activeTag === 'all' || (p.tags && p.tags.includes(activeTag));

    return matchesSearch && matchesTag;
  });

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
      {/* Hero / Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end' }}>
        <div>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              color: 'var(--accent-primary)',
              fontSize: '13px',
              fontWeight: 700,
              textTransform: 'uppercase',
              letterSpacing: '1px',
            }}
          >
            <Gamepad2 size={16} />
            <span>Community Gallery</span>
          </div>
          <h1 style={{ fontSize: '28px', fontWeight: 700, marginTop: '4px', letterSpacing: '-0.5px' }}>
            Arcade Showcase
          </h1>
          <p style={{ color: 'var(--text-secondary)', fontSize: '14px', marginTop: '4px' }}>
            Browse and play games synthesized by creators through natural conversation.
          </p>
        </div>

        {/* Search Input */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            backgroundColor: 'var(--bg-elevated)',
            border: '1px solid var(--border-subtle)',
            borderRadius: '8px',
            padding: '6px 12px',
            width: '260px',
          }}
        >
          <Search size={14} color="var(--text-tertiary)" />
          <input
            type="text"
            placeholder="Search games..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{
              background: 'transparent',
              border: 'none',
              outline: 'none',
              color: 'var(--text-primary)',
              fontSize: '13px',
              width: '100%',
            }}
          />
        </div>
      </div>

      {/* Filter Tags */}
      <div style={{ display: 'flex', gap: '8px' }}>
        {tags.map((t) => (
          <button
            key={t}
            onClick={() => setActiveTag(t)}
            style={{
              backgroundColor: activeTag === t ? 'rgba(139, 92, 246, 0.2)' : 'var(--bg-elevated)',
              border: `1px solid ${activeTag === t ? 'var(--accent-primary)' : 'var(--border-subtle)'}`,
              color: activeTag === t ? 'var(--accent-primary)' : 'var(--text-secondary)',
              borderRadius: '20px',
              padding: '4px 12px',
              fontSize: '12px',
              fontWeight: 600,
              cursor: 'pointer',
              textTransform: 'capitalize',
            }}
          >
            {t}
          </button>
        ))}
      </div>

      {/* Game Cards Grid */}
      {filtered.length === 0 ? (
        <div
          style={{
            padding: '60px 0',
            textAlign: 'center',
            color: 'var(--text-tertiary)',
            backgroundColor: 'var(--bg-base)',
            borderRadius: '12px',
            border: '1px solid var(--border-subtle)',
          }}
        >
          <Gamepad2 size={36} style={{ opacity: 0.4, marginBottom: '8px' }} />
          <div style={{ fontWeight: 600, fontSize: '15px', color: 'var(--text-secondary)' }}>
            The arcade is quiet.
          </div>
          <div style={{ fontSize: '13px', marginTop: '4px' }}>
            No published games matched your search. Launch Studio to create one!
          </div>
        </div>
      ) : (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
            gap: '20px',
          }}
        >
          {filtered.map((game) => (
            <div
              key={game.slug}
              style={{
                backgroundColor: 'var(--bg-elevated)',
                border: '1px solid var(--border-subtle)',
                borderRadius: '12px',
                overflow: 'hidden',
                display: 'flex',
                flexDirection: 'column',
                transition: 'border-color 0.15s ease',
              }}
            >
              {/* Game Preview Thumbnail Container */}
              <div
                style={{
                  height: '160px',
                  backgroundColor: '#050110',
                  position: 'relative',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  borderBottom: '1px solid var(--border-subtle)',
                }}
              >
                <Gamepad2 size={40} color="var(--accent-primary)" style={{ opacity: 0.3 }} />
                <button
                  onClick={() => setSelectedGame(game)}
                  style={{
                    position: 'absolute',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px',
                    backgroundColor: 'var(--accent-primary)',
                    color: '#ffffff',
                    border: 'none',
                    borderRadius: '8px',
                    padding: '8px 16px',
                    fontWeight: 600,
                    fontSize: '13px',
                    cursor: 'pointer',
                    boxShadow: '0 4px 14px rgba(139, 92, 246, 0.4)',
                  }}
                >
                  <Play size={14} fill="#ffffff" />
                  <span>Play</span>
                </button>
              </div>

              {/* Game Metadata Info */}
              <div style={{ padding: '16px', flex: 1, display: 'flex', flexDirection: 'column' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                  <h3 style={{ fontSize: '16px', fontWeight: 700 }}>{game.title}</h3>
                </div>
                <p
                  style={{
                    fontSize: '13px',
                    color: 'var(--text-secondary)',
                    marginTop: '6px',
                    lineHeight: '1.4',
                    flex: 1,
                  }}
                >
                  {game.description || 'A browser game created in Yulya Studio.'}
                </p>

                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    marginTop: '16px',
                    borderTop: '1px solid var(--border-subtle)',
                    paddingTop: '12px',
                  }}
                >
                  <span
                    style={{
                      fontSize: '11px',
                      color: 'var(--text-tertiary)',
                      fontFamily: 'var(--font-mono)',
                    }}
                  >
                    /{game.slug}
                  </span>
                  <button
                    onClick={() => onPlayInStudio(game)}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '4px',
                      background: 'transparent',
                      border: 'none',
                      color: 'var(--accent-primary)',
                      fontSize: '12px',
                      fontWeight: 600,
                      cursor: 'pointer',
                    }}
                  >
                    <span>Open in IDE</span>
                    <ExternalLink size={12} />
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Play Modal Overlay */}
      {selectedGame && (
        <div
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: 'rgba(5, 1, 16, 0.85)',
            backdropFilter: 'blur(8px)',
            display: 'flex',
            justifyContent: 'center',
            alignItems: 'center',
            zIndex: 100,
            padding: '24px',
          }}
          onClick={() => setSelectedGame(null)}
        >
          <div
            style={{
              width: '900px',
              height: '620px',
              backgroundColor: 'var(--bg-elevated)',
              borderRadius: '12px',
              border: '1px solid var(--border-active)',
              display: 'flex',
              flexDirection: 'column',
              overflow: 'hidden',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div
              style={{
                height: '44px',
                padding: '0 16px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                borderBottom: '1px solid var(--border-subtle)',
              }}
            >
              <div style={{ fontWeight: 700, fontSize: '15px' }}>{selectedGame.title}</div>
              <button
                onClick={() => setSelectedGame(null)}
                style={{
                  background: 'transparent',
                  border: 'none',
                  color: 'var(--text-secondary)',
                  cursor: 'pointer',
                  fontSize: '16px',
                }}
              >
                ✕
              </button>
            </div>
            <div style={{ flex: 1, backgroundColor: '#050110' }}>
              <iframe
                src={`/tester/${selectedGame.slug}/`}
                title={selectedGame.title}
                sandbox="allow-scripts"
                style={{ width: '100%', height: '100%', border: 'none' }}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
