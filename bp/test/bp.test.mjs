import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import { mkdtempSync, writeFileSync, chmodSync, existsSync, rmSync, readdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

const BP = path.resolve(import.meta.dirname, '../bin/bp.mjs');
const pw = `${process.env.HOME}/Library/Caches/ms-playwright`;
const v = existsSync(pw) && readdirSync(pw).filter((d) => /^chromium-\d+$/.test(d)).sort((a, b) => b.slice(9) - a.slice(9))[0];
const CHROME = process.env.BP_CHROME || `${pw}/${v}/chrome-mac-${process.arch === 'arm64' ? 'arm64' : 'x64'}/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing`;
const bp = (args, env = {}, cwd = tmpdir()) => spawnSync(process.execPath, [BP, ...args], { cwd, encoding: 'utf8', env: { ...process.env, ...env } });

test('--help and -h print usage and exit 0 without running any command', () => {
  const dir = mkdtempSync(path.join(tmpdir(), 'bp-help-'));
  const marker = path.join(dir, 'launched');
  const chrome = path.join(dir, 'fake-chrome');
  writeFileSync(chrome, `#!/bin/sh\ntouch "${marker}"\n`); chmodSync(chrome, 0o755);
  // An unused port, a stub browser and a missing jev dir: nothing real can be touched even if a command runs.
  const env = { BP_PORT: '59871', BP_CHROME: chrome, JEV_DIR: path.join(dir, 'no-jev') };
  const cmds = ['launch', 'list', 'open', 'snap', 'hosts', 'text', 'click', 'clicktext', 'type', 'key', 'scroll', 'eval', 'upload', 'shot', 'reload', 'form', 'cookies', 'record', 'close', 'goal', 'kill', 'help'];
  for (const argv of [['--help'], ['-h'], ...cmds.flatMap((c) => [[c, '--help'], [c, '-h'], [c, 'x', '--help']])]) {
    const r = bp(argv, env, dir);
    assert.equal(r.status, 0, `bp ${argv.join(' ')} exited ${r.status}: ${r.stderr}`);
    assert.match(r.stdout, /launch \[url\]/, `bp ${argv.join(' ')} did not print usage`);
    assert.doesNotMatch(r.stdout, /up on :|killed|jev →|recording/, `bp ${argv.join(' ')} ran the command`);
  }
  assert.ok(!existsSync(marker), 'a --help invocation launched the browser');
  assert.ok(!existsSync(path.join(dir, '-h')) && !existsSync(path.join(dir, 'x')), 'record created a directory');
  rmSync(dir, { recursive: true, force: true });
});

test('type focuses the --selector element, even inside a shadow root, before typing', { skip: !existsSync(CHROME) && 'Playwright Chromium not installed' }, async (t) => {
  const port = '59872'; const env = { BP_PORT: port };
  const profile = mkdtempSync(path.join(tmpdir(), 'bp-type-'));
  const chrome = spawn(CHROME, ['--headless=new', `--user-data-dir=${profile}`, '--no-first-run', `--remote-debugging-port=${port}`, 'about:blank'], { stdio: 'ignore' });
  t.after(() => { chrome.kill(); rmSync(profile, { recursive: true, force: true }); });
  for (let i = 0; i < 40; i++) { try { await fetch(`http://127.0.0.1:${port}/json/version`); break; } catch { await new Promise((r) => setTimeout(r, 250)); } }
  // Focus starts on another input, so typing without focusing the target lands in the wrong field.
  const html = `<title>typetest</title><input id=other autofocus><div id=host></div><script>document.getElementById('host').attachShadow({mode:'open'}).innerHTML='<textarea></textarea>'</script>`;
  assert.equal(bp(['open', 'data:text/html,' + encodeURIComponent(html), '--wait', '1000'], env).status, 0);
  const r = bp(['type', 'typetest', 'hello', '--selector', 'textarea'], env);
  assert.equal(r.status, 0, r.stderr);
  const v = bp(['eval', 'typetest', `JSON.stringify([document.getElementById('host').shadowRoot.querySelector('textarea').value, document.getElementById('other').value])`], env);
  assert.equal(v.stdout.trim(), '["hello",""]');
  const missing = bp(['type', 'typetest', 'x', '--selector', '#nope'], env);
  assert.equal(missing.status, 1);
  assert.match(missing.stderr, /no element matching "#nope"/);
});
