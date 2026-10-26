/* End-to-end browser regressions against this checkout only. No target input,
 * live data, remote credentials, service workers or outbound browser requests.
 * Install Playwright in an ephemeral tool prefix, not the app's dependency tree.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const net = require('node:net');
const { spawn } = require('node:child_process');
const { createRequire } = require('node:module');
const { createFixtureProxy } = require('./proxy.cjs');
const requireTool = createRequire(path.resolve(process.env.PLAYWRIGHT_TOOLS, 'package.json'));
const { chromium } = requireTool('playwright');
const root = path.resolve(__dirname, '../..');
const reports = path.join(__dirname, 'reports');
fs.mkdirSync(reports, { recursive: true });
const fixture = fs.mkdtempSync(path.join(os.tmpdir(), 'jobcontext-browser-'));
const results = { checks: [], blockedExternalRequests: [], blockedWebSockets: [], consoleMessages: [], requestFailures: [], popupStates: [], proxyRequests: [], externalPageRequests: [] };
let server, browser, context, proxy;
const cspErrors = [], runtimeErrors = [];
const delay = (ms) => new Promise(resolve => setTimeout(resolve, ms));
async function until(check, label, timeout = 30000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (await check()) return;
    await delay(100);
  }
  throw new Error(`Timed out: ${label}`);
}
function pass(check) { results.checks.push(check); console.log('PASS', check); }
async function freePort() {
  const socket = net.createServer();
  await new Promise((resolve, reject) => { socket.once('error', reject); socket.listen(0, '127.0.0.1', resolve); });
  const port = socket.address().port;
  await new Promise(resolve => socket.close(resolve));
  return port;
}
function assertNoBrowserErrors() {
  assert.deepEqual(cspErrors, [], 'Unexpected CSP violation');
  assert.deepEqual(runtimeErrors, [], 'Uncaught browser error');
  assert.deepEqual(results.blockedWebSockets, [], 'Unexpected WebSocket connection');
}
async function browserStorage(page) {
  return page.evaluate(() => ({ local: Object.keys(localStorage), session: Object.keys(sessionStorage) }));
}
async function preview(page, name, kind, origin) {
  const [popup] = await Promise.all([
    page.waitForEvent('popup'),
    page.getByTitle(`Preview ${name}`, { exact: true }).click(),
  ]);
  if (kind === 'markdown') await popup.locator('main.doc h1').waitFor();
  else await popup.locator('iframe#pv').waitFor();
  // Markdown replaces an initial loading shell using document.write. Wait for
  // the FINAL document and its deferred same-origin Print script, not shell load.
  await popup.waitForLoadState('load');
  await popup.waitForFunction(() => document.readyState === 'complete' &&
    [...document.styleSheets].some(s => s.href?.endsWith('/app/materials-preview.css')));
  assert.equal(await popup.evaluate(() => window.opener), null);
  assert.equal(await popup.locator('body').evaluate(el => getComputedStyle(el).backgroundColor), 'rgb(10, 16, 24)');
  assert.equal(await popup.evaluate(() => Boolean(window.fixtureInjected)), false);
  if (kind === 'markdown') {
    assert.equal(await popup.locator('main.doc h1').textContent(), 'Browser security fixture');
    assert.equal(await popup.locator('main.doc script').count(), 0);
  } else {
    const frame = popup.frameLocator('#pv');
    await frame.locator('body').waitFor();
    assert.match(await frame.locator('body').innerText(), /Synthetic (raw|fallback) preview/);
    assert.equal(new URL(await popup.locator('#pv').getAttribute('src'), origin).origin, origin);
  }
  // Observe the real click listener without opening an interactive print dialog.
  await popup.evaluate(() => {
    window.printCount = 0;
    window.print = () => { window.printCount += 1; };
    const frame = document.querySelector('#pv');
    if (frame) {
      frame.contentWindow.print = () => { window.printCount += 1; };
      frame.contentWindow.focus = () => {};
    }
  });
  await popup.locator('#print-preview').click();
  assert.equal(await popup.evaluate(() => window.printCount), 1);
  await popup.emulateMedia({ media: 'print' });
  assert.equal(await popup.locator('.bar').evaluate(el => getComputedStyle(el).display), 'none');
  assertNoBrowserErrors();
  pass(`${kind} preview: inherited CSP, external CSS/Print, no opener, same-origin iframe/sanitized Markdown`);
  await popup.close();
}
(async () => {
  const port = await freePort();
  const origin = `http://127.0.0.1:${port}`;
  const log = fs.openSync(path.join(reports, 'app.log'), 'w');
  server = spawn(process.env.PYTHON || 'python', [path.join(__dirname, 'start.py'), fixture, String(port)], {
    cwd: root, stdio: ['ignore', log, log],
    env: { PATH: process.env.PATH, HOME: fixture, LANG: 'C.UTF-8', PYTHONUNBUFFERED: '1' },
  });
  fs.closeSync(log);
  await until(async () => {
    if (server.exitCode !== null) throw new Error(`Fixture exited ${server.exitCode}: inspect app.log`);
    try { return (await fetch(`${origin}/health`, { signal: AbortSignal.timeout(1000) })).ok; }
    catch { return false; }
  }, 'disposable app health');
  // Playwright Chromium #43496 deadlocks about:blank popup subresources
  // whenever context.route/page.route is enabled. A local deny-by-default
  // proxy keeps network isolation without that CDP interception path.
  proxy = await createFixtureProxy({ port,
    onBlocked: request => results.blockedExternalRequests.push(request.url),
    onForwarded: request => results.proxyRequests.push(request.url),
  });
  browser = await chromium.launch({
    headless: true, proxy: { server: proxy.url, bypass: '<-loopback>' },
  });
  context = await browser.newContext({ serviceWorkers: 'block', viewport: { width: 1440, height: 1000 } });
  // No tested flow needs WebSockets. Keep browser interception as defense
  // in depth; the proxy independently denies all CONNECT/upgrade tunnels.
  await context.routeWebSocket('**/*', async socket => {
    results.blockedWebSockets.push(socket.url());
    await socket.close({ code: 1008, reason: 'Browser fixture blocks WebSocket connections' });
  });
  // Context-level network events cover requests initiated before a popup's
  // page event is delivered. Keep diagnostics without weakening any checks.
  context.on('request', request => {
    if (new URL(request.url()).origin !== origin) results.externalPageRequests.push(request.url());
  });
  context.on('requestfailed', request => {
    results.requestFailures.push({ url: request.url(), resourceType: request.resourceType(), failure: request.failure() });
  });
  context.on('page', page => {
    page.on('pageerror', err => runtimeErrors.push(err.message));
    page.on('console', msg => {
      results.consoleMessages.push({ page: page.url(), type: msg.type(), text: msg.text() });
      if (/violates.*Content Security Policy|Refused to.*(script|style|frame)|Content Security Policy.*violat/i.test(msg.text())) {
        cspErrors.push(msg.text());
      }
    });
  });
  const page = await context.newPage();
  for (const pathname of ['/', '/why', '/setup', '/architecture', '/login', '/privacy', '/terms']) {
    const response = await page.goto(origin + pathname);
    assert.equal(response.status(), 200);
    assert.match(response.headers()['content-security-policy'], /default-src 'none'/);
    assert.equal(await page.locator('body').evaluate(el => getComputedStyle(el).margin), '0px');
    assert.equal(await page.locator('body').evaluate(el => {
      const style = getComputedStyle(el);
      return style.backgroundColor !== 'rgba(0, 0, 0, 0)' || style.backgroundImage !== 'none';
    }), true);
    assert.deepEqual(await context.cookies(), [], `Public ${pathname} must not set cookies`);
    assert.deepEqual(await browserStorage(page), { local: [], session: [] }, `Public ${pathname} must not write browser storage`);
    assert.equal(await page.locator('link[href="/fonts/fonts.css"]').count(), 1, `Public ${pathname} uses same-origin fonts`);
    if (pathname === '/login') {
      assert.equal(await page.locator('a[href^="/privacy"]').count(), 1);
      assert.equal(await page.locator('a[href="/terms"]').count(), 1);
    }
    if (pathname === '/architecture') {
      assert.equal(await page.locator('img.diagram-image').count(), 2);
      assert.equal(await page.locator('img.diagram-image').evaluateAll(imgs => imgs.every(img => img.complete && img.naturalWidth > 0)), true);
      await page.screenshot({ path: path.join(reports, 'architecture.png'), fullPage: true });
    }
    assertNoBrowserErrors();
  }
  assert.deepEqual(results.externalPageRequests, [], 'Public pages must not request third-party assets');
  assert.equal(results.proxyRequests.some(url => url.endsWith('/static/architecture/capability-layer.svg')), true, 'Chromium must route loopback subresources through the isolation proxy');
  pass('All seven public pages keep authored styles; both architecture diagrams load under strict CSP');

  const malicious = '</a><script>window.fixtureInjected=true</script>';
  await page.goto(`${origin}/login?next=${encodeURIComponent(malicious)}`);
  assert.equal(await page.locator('script').count(), 0);
  assert.equal(await page.evaluate(() => Boolean(window.fixtureInjected)), false);
  assertNoBrowserErrors();
  // Independent browser enforcement probe: the API's evaluate can insert a
  // script node, but Chromium must refuse that node under the delivered CSP.
  await page.evaluate(() => {
    const probe = document.createElement('script');
    probe.textContent = 'window.fixtureInjected=true';
    document.body.append(probe);
  });
  await until(() => cspErrors.length > 0, 'browser blocked inline script');
  assert.equal(await page.evaluate(() => Boolean(window.fixtureInjected)), false);
  results.expectedInlineScriptViolation = cspErrors.splice(0);
  pass('Reflected next payload escaped; browser CSP independently blocks injected inline script');

  await page.goto(`${origin}/dashboard/login?next=%2Fapp%2Fmaterials`);
  assert.equal(await page.locator('a[href^="/privacy"]').count(), 1);
  assert.equal(await page.locator('a[href="/terms"]').count(), 1);
  assert.equal(await page.locator('body').evaluate(el => getComputedStyle(el).display), 'grid');
  assert.equal(await page.locator('form.card').evaluate(el => getComputedStyle(el).maxWidth), '420px');
  assert.match(await page.locator('[name="csrf_token"]').inputValue(), /^[A-Za-z0-9_-]{43}$/);
  await page.screenshot({ path: path.join(reports, 'login.png') });
  const externalBeforeApp = results.externalPageRequests.length;
  await page.locator('#api_key').fill('browser-synthetic-not-a-secret');
  await Promise.all([page.waitForURL(`${origin}/app/materials`), page.getByRole('button', { name: 'Sign in', exact: true }).click()]);
  await page.getByTitle('Preview security-preview.md', { exact: true }).waitFor();
  const session = (await context.cookies()).find(cookie => cookie.name === 'jc_session');
  assert.equal(session?.httpOnly, true);
  assert.equal(session?.sameSite, 'Lax');
  assert.equal(session?.path, '/');
  assert.ok(Math.abs(session.expires - Date.now() / 1000 - 30 * 24 * 60 * 60) < 120, 'API-key session has the disclosed 30-day expiry');
  assert.equal((await context.cookies()).some(cookie => cookie.name === 'jc_login_csrf'), false);
  assert.deepEqual((await context.cookies()).map(cookie => cookie.name), ['jc_session']);
  assert.deepEqual(await browserStorage(page), { local: [], session: [] });
  assertNoBrowserErrors();
  pass('Real API-key form signs in and removes pre-login cookie; built SPA loads and renders Materials');

  const fonts = await page.evaluate(async () => {
    const loads = [];
    for (const family of ['Inter', 'JetBrains Mono', 'Space Grotesk']) {
      for (const weight of [400, 500, 600, 700]) {
        const faces = await document.fonts.load(`${weight} 16px "${family}"`, 'AaЖΩă');
        loads.push({ family, weight, loaded: faces.length > 0 && faces.every(face => face.status === 'loaded') });
      }
    }
    return loads;
  });
  assert.equal(fonts.every(item => item.loaded), true, JSON.stringify(fonts));
  results.fonts = fonts;
  pass('Three self-hosted font families load at weights 400/500/600/700');

  await preview(page, 'security-preview.md', 'markdown', origin);
  await preview(page, 'security-preview.txt', 'raw', origin);
  await preview(page, 'security-fallback.md', 'fallback', origin);
  assert.equal(results.externalPageRequests.length, externalBeforeApp, 'SPA/preview must use only same-origin assets');
  assertNoBrowserErrors();
  await page.screenshot({ path: path.join(reports, 'materials.png'), fullPage: true });

  // Native button activation must work in a real browser, not only synthetic
  // jsdom click events. Exercise Enter and Space, including cancel/re-entry,
  // without importing any posts or contacting an external service.
  async function activate(name, key) {
    const control = page.getByRole('button', { name, exact: true });
    await control.focus();
    assert.equal(await control.evaluate(el => el === document.activeElement), true);
    await control.press(key);
  }
  await activate('Posts', 'Enter');
  for (const key of ['Enter', 'Space']) {
    await activate('↧ Import from LinkedIn', key);
    const fileInput = page.getByLabel('Choose CSV file', { exact: true });
    assert.equal(await fileInput.getAttribute('type'), 'file');
    await fileInput.focus();
    assert.equal(await fileInput.evaluate(el => el === document.activeElement), true);
    assert.equal(await fileInput.evaluate(el => getComputedStyle(el.closest('label')).outlineStyle), 'solid');
    await activate('Use sample Shares.csv', key === 'Enter' ? 'Space' : 'Enter');
    await page.getByText('Map & preview', { exact: true }).waitFor();
    await activate('Cancel', key);
    await page.getByRole('button', { name: '↧ Import from LinkedIn', exact: true }).waitFor();
  }
  await page.screenshot({ path: path.join(reports, 'posts-keyboard.png'), fullPage: true });
  await activate('Materials', 'Enter');
  await page.getByTitle('Preview security-preview.md', { exact: true }).waitFor();
  assert.equal(results.externalPageRequests.length, externalBeforeApp, 'Keyboard flows must remain same-origin');
  assertNoBrowserErrors();
  pass('Native sidebar/import controls respond to Enter/Space; sample preview cancels and reopens without side effects');

  // Real authenticated routes and saved template choices at both viewport
  // sizes. Only the disposable fixture executor replaces the external LLM.
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 844 });
    await page.goto(`${origin}/app/conference-demo`);
    await page.getByRole('heading', { name: 'Recent generations' }).waitFor();
    await page.getByLabel('Company or role').fill('Conference Fixture');
    await page.getByRole('button', { name: 'Search', exact: true }).click();
    await page.getByRole('button', { name: 'Select', exact: true }).click();
    await page.getByRole('button', { name: 'Choose templates', exact: true }).click();
    const dialog = page.getByRole('dialog', { name: 'Templates — Conference Fixture', exact: true });
    const choices = width === 1440
      ? { template: 'executive', style: 'forest', cl_template: 'sidebar', cl_style: 'warm' }
      : { template: 'portfolio', style: 'classic', cl_template: 'modern', cl_style: 'slate' };
    await dialog.getByLabel('Template', { exact: true }).selectOption(choices.template);
    await dialog.getByLabel('Style', { exact: true }).selectOption(choices.style);
    await dialog.getByRole('button', { name: 'Use this resume template', exact: true }).click();
    await dialog.getByText(`Resume template set: ${choices.template} / ${choices.style}.`, { exact: true }).waitFor();
    await dialog.getByRole('button', { name: 'Cover Letter', exact: true }).click();
    await dialog.getByLabel('Template', { exact: true }).selectOption(choices.cl_template);
    await dialog.getByLabel('Style', { exact: true }).selectOption(choices.cl_style);
    await dialog.getByRole('button', { name: 'Use this cover letter template', exact: true }).click();
    await dialog.getByText(`Cover letter template set: ${choices.cl_template} / ${choices.cl_style}.`, { exact: true }).waitFor();
    assert.equal(await dialog.locator('iframe').getAttribute('src'), `/dashboard/pipeline/preview-cl/${choices.cl_template}/${choices.cl_style}`);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true, `Template picker fits at ${width}px`);
    await page.screenshot({ path: path.join(reports, `conference-picker-${width}.png`), fullPage: true, animations: 'disabled' });
    await dialog.getByRole('button', { name: 'Close', exact: true }).click();
    // Reopen the existing picker: persisted choices, not just local select state.
    await page.getByRole('button', { name: 'Choose templates', exact: true }).click();
    assert.equal(await dialog.getByLabel('Template', { exact: true }).inputValue(), choices.template);
    assert.equal(await dialog.getByLabel('Style', { exact: true }).inputValue(), choices.style);
    await dialog.getByRole('button', { name: 'Cover Letter', exact: true }).click();
    assert.equal(await dialog.getByLabel('Template', { exact: true }).inputValue(), choices.cl_template);
    assert.equal(await dialog.getByLabel('Style', { exact: true }).inputValue(), choices.cl_style);
    await dialog.getByRole('button', { name: 'Close', exact: true }).click();
    const submission = page.waitForRequest(r => new URL(r.url()).pathname === '/api/badge/materials' && r.method() === 'POST');
    await page.getByRole('button', { name: 'Generate documents', exact: true }).click();
    assert.deepEqual((await submission).postDataJSON(), { job_id: 1, material: 'both', ...choices });
    await until(async () => (await page.locator('[role="status"]').textContent()) === 'Completed', 'conference generation completes');
    const workId = new URL(page.url()).searchParams.get('work');
    assert.match(workId, /^\d+$/);
    const stored = await page.evaluate(async id => (await fetch(`/api/work/${id}`)).json(), workId);
    for (const [key, value] of Object.entries(choices)) assert.equal(stored.inputs[key], value, `Queued ${key}`);
    await page.reload();
    await page.getByText('Completed', { exact: true }).waitFor();
    await page.getByText(`Queued layouts: resume ${choices.template} / ${choices.style}; cover letter ${choices.cl_template} / ${choices.cl_style}.`, { exact: true }).waitFor();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true, `No overflow at ${width}px`);
    await page.screenshot({ path: path.join(reports, `conference-${width}.png`), fullPage: true, animations: 'disabled' });
  }
  await context.setOffline(true);
  await page.getByText('You are offline.', { exact: false }).waitFor();
  assert.equal(await page.getByRole('button', { name: 'Search', exact: true }).isEnabled(), false);
  await context.setOffline(false);
  await page.getByRole('button', { name: 'Refresh recent generations', exact: true }).click();
  assertNoBrowserErrors();
  pass('Conference fallback: saved template choices reach queued work, both document layouts, reload recovery, 390px/1440px layout, offline controls');

  // The only app-owned Web Storage use preserves an unfinished golden-set
  // form. Exercise it with synthetic text, never Run or any provider call.
  await page.goto(`${origin}/app/evals`);
  await page.getByPlaceholder('Company', { exact: true }).fill('Privacy Fixture');
  await page.getByPlaceholder('Role title', { exact: true }).fill('Synthetic Role');
  await page.getByPlaceholder('Paste the full job description here', { exact: true }).fill('Synthetic privacy audit job description.');
  await page.locator('select:has(option[value="cover_letter"])').selectOption('cover_letter');
  assert.deepEqual(await browserStorage(page), { local: [], session: ['jc-evals-golden-draft'] });
  const draft = await page.evaluate(() => JSON.parse(sessionStorage.getItem('jc-evals-golden-draft')));
  assert.deepEqual(draft, { company: 'Privacy Fixture', role: 'Synthetic Role', jd: 'Synthetic privacy audit job description.', kind: 'cover_letter' });
  await page.reload();
  assert.equal(await page.getByPlaceholder('Company', { exact: true }).inputValue(), 'Privacy Fixture');
  assert.equal(await page.getByPlaceholder('Paste the full job description here', { exact: true }).inputValue(), draft.jd);
  assert.equal(await page.locator('select:has(option[value="cover_letter"])').inputValue(), 'cover_letter');
  const save = page.waitForResponse(response => new URL(response.url()).pathname === '/dashboard/evals/golden' && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Add entry', exact: true }).click();
  const saved = await save;
  assert.equal(saved.status(), 200);
  assert.ok((await saved.json()).entry.id, 'Draft clears only after a confirmed save');
  await until(async () => (await browserStorage(page)).session.length === 0, 'saved draft removed from sessionStorage');
  assert.deepEqual(await browserStorage(page), { local: [], session: [] });
  await Promise.all([
    page.waitForURL(`${origin}/`),
    page.getByRole('button', { name: 'Sign out', exact: true }).click(),
  ]);
  assert.deepEqual(await context.cookies(), [], 'Sign out removes the only session cookie');
  assert.deepEqual(await browserStorage(page), { local: [], session: [] });
  const anonymous = await context.request.get(`${origin}/api/dashboard/me`);
  assert.equal(anonymous.status(), 401, 'Signed-out session cannot access protected data');
  assert.deepEqual(results.externalPageRequests, [], 'Public and signed-in fixture flows must remain same-origin');
  assertNoBrowserErrors();
  pass('Privacy inventory: no public storage or third-party requests; Evals draft survives reload and clears on save; sign-out removes session cookie');
  results.status = 'passed';
})().catch(async err => {
  results.status = 'failed';
  results.error = err.stack;
  console.error(err);
  if (context) {
    for (const [index, page] of context.pages().entries()) {
      try {
        const state = await page.evaluate(() => ({
          url: location.href, origin: location.origin, baseURI: document.baseURI,
          readyState: document.readyState, openerIsNull: window.opener === null,
          links: [...document.querySelectorAll('link')].map(el => ({ href: el.href, attr: el.getAttribute('href'), rel: el.rel, hasSheet: Boolean(el.sheet) })),
          scripts: [...document.scripts].map(el => ({ src: el.src, attr: el.getAttribute('src'), defer: el.defer })),
          sheets: [...document.styleSheets].map(sheet => ({ href: sheet.href, disabled: sheet.disabled })),
          head: document.head?.innerHTML, body: document.body?.innerHTML,
        }));
        results.popupStates.push({ playwrightUrl: page.url(), ...state });
        fs.writeFileSync(path.join(reports, `failure-${index}.html`), await page.content());
        await page.screenshot({ path: path.join(reports, `failure-${index}.png`), fullPage: true });
      } catch (diagnosticError) { results.popupStates.push({ playwrightUrl: page.url(), diagnosticError: String(diagnosticError) }); }
    }
  }
  process.exitCode = 1;
}).finally(async () => {
  results.unexpectedCspErrors = cspErrors;
  results.runtimeErrors = runtimeErrors;
  fs.writeFileSync(path.join(reports, 'results.json'), JSON.stringify(results, null, 2));
  if (browser) await browser.close();
  if (proxy) await proxy.close();
  if (server && server.exitCode === null) {
    server.kill('SIGTERM');
    await Promise.race([new Promise(resolve => server.once('exit', resolve)), delay(5000)]);
    if (server.exitCode === null) server.kill('SIGKILL');
  }
  fs.rmSync(fixture, { recursive: true, force: true });
});
