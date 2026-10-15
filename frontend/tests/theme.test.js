import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';

test('Theme Design Tokens - Restrained Graphite System', () => {
  const cssPath = path.resolve(process.cwd(), '../static/css/studio.css');
  assert.ok(fs.existsSync(cssPath), 'studio.css exists');
  const css = fs.readFileSync(cssPath, 'utf-8');

  // Must define restrained graphite colors
  assert.ok(css.includes('--bg-deepest: #0d0e12;'), 'Contains --bg-deepest: #0d0e12');
  assert.ok(css.includes('--bg-base: #131419;'), 'Contains --bg-base: #131419');
  assert.ok(css.includes('--bg-elevated: #1a1c23;'), 'Contains --bg-elevated: #1a1c23');
  assert.ok(css.includes('--border-subtle: #2b2f3a;'), 'Contains --border-subtle: #2b2f3a');
  assert.ok(css.includes('--accent-primary: #3b82f6;'), 'Contains --accent-primary: #3b82f6');

  // Must NOT contain old neon purple backgrounds
  assert.ok(!css.includes('#050110'), 'Eliminated neon #050110');
  assert.ok(!css.includes('#0a0518'), 'Eliminated neon #0a0518');
});

test('Frontend index.html Design Tokens', () => {
  const htmlPath = path.resolve(process.cwd(), 'index.html');
  assert.ok(fs.existsSync(htmlPath), 'index.html exists');
  const html = fs.readFileSync(htmlPath, 'utf-8');

  assert.ok(html.includes('--bg-deepest: #0d0e12;'), 'index.html has graphite deepest bg');
  assert.ok(html.includes('--bg-base: #131419;'), 'index.html has graphite base bg');
  assert.ok(html.includes('--bg-elevated: #1a1c23;'), 'index.html has graphite elevated bg');
});
