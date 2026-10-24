/* Fail-closed test proxy. Chromium's interception bug #43496 stalls resources
 * in document.write/about:blank popups, so enforce isolation before the network
 * instead of using Playwright context.route. No caller-supplied target URL.
 */
const http = require('node:http');

const FALLBACK_PATH = '/dashboard/materials/file/job_assessments/security-fallback.md';

async function createFixtureProxy({ port, onBlocked = () => {}, onForwarded = () => {} }) {
  if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new Error('Invalid fixture port');
  const origin = `http://127.0.0.1:${port}`;
  const server = http.createServer((request, response) => {
    let url;
    try { url = new URL(request.url); } catch { /* malformed/non-absolute proxy request is refused */ }
    if (!url || url.origin !== origin || url.username || url.password) {
      onBlocked({ method: request.method, url: request.url });
      response.writeHead(403, { 'Content-Type': 'text/plain', 'Connection': 'close' });
      return response.end('Browser fixture proxy blocks non-fixture targets');
    }
    // Fetch gets a synthetic failure; navigation to the same file still uses
    // the real app response, exercising the production raw-iframe fallback.
    if (url.pathname === FALLBACK_PATH && request.headers['sec-fetch-dest'] === 'empty') {
      response.writeHead(503, { 'Content-Type': 'text/plain' });
      return response.end('Synthetic fetch failure');
    }
    onForwarded({ method: request.method, url: url.href });
    const headers = { ...request.headers, host: `127.0.0.1:${port}`, connection: 'close' };
    delete headers['proxy-connection'];
    delete headers['proxy-authorization'];
    // IMPORTANT: never take hostname/port from the untrusted request or Host.
    const upstream = http.request({ hostname: '127.0.0.1', port,
      path: url.pathname + url.search, method: request.method, headers, agent: false,
    }, incoming => {
      response.writeHead(incoming.statusCode, incoming.headers);
      incoming.pipe(response);
    });
    upstream.on('error', () => {
      if (!response.headersSent) response.writeHead(502);
      response.end('Disposable fixture unavailable');
    });
    request.on('aborted', () => upstream.destroy());
    response.on('close', () => { if (!response.writableFinished) upstream.destroy(); });
    request.pipe(upstream);
  });
  const denyTunnel = (request, socket) => {
    onBlocked({ method: request.method, url: request.url });
    socket.end('HTTP/1.1 403 Forbidden\r\nConnection: close\r\nContent-Length: 0\r\n\r\n');
  };
  // HTTPS and WebSocket tunnels would bypass the allowlist; none are needed.
  server.on('connect', denyTunnel);
  server.on('upgrade', denyTunnel);
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  return {
    url: `http://127.0.0.1:${server.address().port}`,
    close: () => new Promise(resolve => {
      server.close(resolve);
      server.closeAllConnections();
    }),
  };
}

module.exports = { createFixtureProxy, FALLBACK_PATH };
