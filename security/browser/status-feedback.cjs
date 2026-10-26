/* Status-only synthetic responses on a new local-fixture page. These narrowly
 * scoped routes never generate documents, query live work, or weaken the
 * runner's deny-by-default network proxy. No popup uses this intercepted page.
 */
const assert = require('node:assert/strict');
const path = require('node:path');

async function checkStatusFeedback({ context, origin, reports, until }) {
  const page = await context.newPage();
  const workId = 900001;
  const run = { id: workId, kind: 'badge_materials', status: 'running',
    inputs: { job_id: 1, material: 'both' }, artifacts: {} };
  let mode = 'running', checks = 0, release;
  const mutations = [];
  page.on('request', request => {
    if (request.method() !== 'GET') mutations.push(request.url());
  });
  await page.route(`${origin}/api/work/${workId}`, route => route.fulfill({ json: run }));
  await page.route(`${origin}/api/badge/work/${workId}`, async route => {
    checks += 1;
    const responseMode = mode;
    if (responseMode === 'hold') await new Promise(resolve => { release = resolve; });
    await route.fulfill(responseMode === 'error'
      ? { status: 503, json: { detail: 'Synthetic unavailable response' } }
      : { json: { work_id: workId, status: responseMode === 'complete' ? 'succeeded' : 'running',
        made: responseMode === 'complete' ? ['resume', 'cover_letter'] : [], detail: '' } });
  });
  await page.goto(`${origin}/app/conference-demo?work=${workId}`);
  await page.getByText('Still running on the server.', { exact: false }).waitFor();
  const firstChecked = await page.locator('time').getAttribute('datetime');
  const check = page.getByRole('button', { name: 'Check status', exact: true });
  await check.focus();
  mode = 'hold';
  await page.keyboard.press('Enter');
  const pending = page.getByRole('button', { name: 'Checking status…', exact: true });
  await pending.waitFor();
  assert.equal(await pending.isEnabled(), false);
  assert.equal(await pending.getAttribute('aria-busy'), 'true');
  await page.getByText('Checking the server for an update…', { exact: true }).waitFor();
  await until(() => typeof release === 'function', 'held status request reaches its fixture route');
  const pendingChecks = checks;
  // Native disabled buttons ignore repeated activation. Keeping the request
  // pending longer than the poll interval also proves no automatic overlap.
  await pending.evaluate(button => { button.click(); button.click(); });
  await page.waitForTimeout(3200);
  assert.equal(checks, pendingChecks);
  mode = 'running';
  release();
  await check.waitFor();
  assert.equal(await check.isEnabled(), true);
  assert.notEqual(await page.locator('time').getAttribute('datetime'), firstChecked);
  await page.getByText('Still running on the server.', { exact: false }).waitFor();
  for (const width of [390, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.screenshot({ path: path.join(reports, `conference-status-${width}.png`), fullPage: true });
  }
  await check.focus();
  mode = 'error';
  await page.keyboard.press('Space');
  await page.getByText('Status check paused.', { exact: false }).waitFor();
  assert.equal(await check.isEnabled(), true);
  mode = 'complete';
  await check.click();
  await page.getByText('Completed', { exact: true }).waitFor();
  assert.equal(await check.count(), 0);
  assert.equal(await page.getByText('Status check paused.', { exact: false }).count(), 0);
  assert.deepEqual(mutations, [], 'Status checks must not submit any mutation');
  await page.close();
}

module.exports = { checkStatusFeedback };
