import test from 'node:test';
import assert from 'node:assert/strict';

test('API Service - fetchCurrentUser returns authenticated user', async () => {
  // Mock global.fetch
  const originalFetch = global.fetch;
  global.fetch = async (url) => {
    if (url === '/api/auth/me') {
      return {
        ok: true,
        json: async () => ({
          authenticated: true,
          user: { id: 123, username: 'testuser', display_name: 'Test Creator' },
          has_api_key: true,
        }),
      };
    }
    return { ok: false };
  };

  try {
    const { fetchCurrentUser } = await import('../src/services/api.ts');
    const data = await fetchCurrentUser();
    assert.equal(data.authenticated, true);
    assert.equal(data.user.username, 'testuser');
    assert.equal(data.has_api_key, true);
  } finally {
    global.fetch = originalFetch;
  }
});

test('API Service - rollbackRelease sends POST with slug and target_version', async () => {
  const originalFetch = global.fetch;
  let sentPayload = null;

  global.fetch = async (url, options) => {
    if (url === '/api/releases/rollback') {
      sentPayload = JSON.parse(options.body);
      return {
        ok: true,
        json: async () => ({
          success: true,
          active_version: 2,
          message: 'Rolled back to v2',
        }),
      };
    }
    return { ok: false };
  };

  try {
    const { rollbackRelease } = await import('../src/services/api.ts');
    const res = await rollbackRelease('my-game', 2);
    assert.equal(res.success, true);
    assert.equal(res.active_version, 2);
    assert.deepEqual(sentPayload, { slug: 'my-game', target_version: 2 });
  } finally {
    global.fetch = originalFetch;
  }
});
