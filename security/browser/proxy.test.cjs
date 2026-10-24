/* Dependency-free isolation checks; every server/socket remains loopback. */
const assert = require('node:assert/strict');
const http = require('node:http');
const net = require('node:net');
const { test } = require('node:test');
const { createFixtureProxy, FALLBACK_PATH } = require('./proxy.cjs');

async function get(proxy, target, { method = 'GET', headers = {}, body = '' } = {}) {
  const proxyURL = new URL(proxy.url);
  return new Promise((resolve, reject) => {
    const req = http.request({ hostname: '127.0.0.1', port: proxyURL.port,
      path: target, method, headers, agent: false }, res => {
      let text = '';
      res.on('data', chunk => { text += chunk; });
      res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, text }));
    });
    req.on('error', reject);
    req.end(body);
  });
}

async function raw(proxy, line, extra = '') {
  return new Promise((resolve, reject) => {
    const socket = net.connect(Number(new URL(proxy.url).port), '127.0.0.1');
    let response = '';
    socket.setTimeout(2000, () => { socket.destroy(); reject(new Error('Proxy tunnel timeout')); });
    socket.on('connect', () => socket.write(`${line}\r\nHost: invalid.example\r\n${extra}\r\n`));
    socket.on('data', chunk => { response += chunk; });
    socket.on('end', () => resolve(response));
    socket.on('error', reject);
  });
}

test('proxy only forwards to fixed fixture, preserving login metadata and raw fallback', async () => {
  const requests = [];
  const fixture = http.createServer((req, res) => {
    let body = '';
    req.on('data', chunk => { body += chunk; });
    req.on('end', () => {
      requests.push({ url: req.url, method: req.method, headers: req.headers, body });
      res.setHeader('Content-Type', 'text/plain');
      res.setHeader('Content-Security-Policy', "default-src 'none'");
      res.end('Synthetic fixture response');
    });
  });
  await new Promise(resolve => fixture.listen(0, '127.0.0.1', resolve));
  const port = fixture.address().port;
  const origin = `http://127.0.0.1:${port}`;
  const blocked = [], forwarded = [];
  const proxy = await createFixtureProxy({ port, onBlocked: item => blocked.push(item), onForwarded: item => forwarded.push(item) });
  try {
    for (const target of [
      'http://example.invalid/', 'https://example.invalid/',
      `http://127.0.0.1:${port + 1}/`, `http://localhost:${port}/`,
      `http://user:pass@127.0.0.1:${port}/`, `http://127.0.0.1:${port}@example.invalid/`,
      '/relative', 'file:///etc/passwd',
    ]) {
      assert.equal((await get(proxy, target)).status, 403, target);
    }
    // Node's HTTP parser itself refuses a syntactically invalid request target.
    assert.equal((await get(proxy, 'not-a-url')).status, 400);
    assert.equal(requests.length, 0, 'Denied targets must never reach the fixture');
    assert.match(await raw(proxy, 'CONNECT example.invalid:443 HTTP/1.1'), /^HTTP\/1\.1 403/);
    assert.match(await raw(proxy, `CONNECT 127.0.0.1:${port} HTTP/1.1`), /^HTTP\/1\.1 403/);
    assert.match(await raw(proxy, `GET ${origin}/ws HTTP/1.1`, 'Connection: Upgrade\r\nUpgrade: websocket\r\n'), /^HTTP\/1\.1 403/);
    assert.equal(requests.length, 0, 'All tunnels are forbidden, including local ones');

    const good = await get(proxy, `${origin}/login?next=%2Fapp`, { method: 'POST',
      headers: { host: 'evil.example', origin, cookie: 'synthetic=nonce', 'content-type': 'application/x-www-form-urlencoded', 'proxy-authorization': 'must-not-forward' },
      body: 'csrf_token=synthetic',
    });
    assert.equal(good.status, 200);
    assert.equal(good.headers['content-security-policy'], "default-src 'none'");
    assert.equal(requests[0].url, '/login?next=%2Fapp');
    assert.equal(requests[0].method, 'POST');
    assert.equal(requests[0].headers.host, `127.0.0.1:${port}`);
    assert.equal(requests[0].headers.origin, origin);
    assert.equal(requests[0].headers.cookie, 'synthetic=nonce');
    assert.equal(requests[0].headers['proxy-authorization'], undefined);
    assert.equal(requests[0].body, 'csrf_token=synthetic');

    assert.equal((await get(proxy, origin + FALLBACK_PATH, { headers: { 'Sec-Fetch-Dest': 'empty' } })).status, 503);
    assert.equal(requests.length, 1, 'Synthetic failed fetch must not hit upstream');
    assert.equal((await get(proxy, origin + FALLBACK_PATH, { headers: { 'Sec-Fetch-Dest': 'iframe' } })).status, 200);
    assert.equal(requests.length, 2, 'Raw iframe gets real fixture response');
    assert.equal(forwarded.length, 2);
    assert.equal(blocked.length, 11);
  } finally {
    await proxy.close();
    await new Promise(resolve => fixture.close(resolve));
  }
});

test('proxy rejects invalid configured fixture ports', async () => {
  for (const port of [0, 80, 65536, '8000', NaN]) {
    await assert.rejects(createFixtureProxy({ port }), /Invalid fixture port/);
  }
});
