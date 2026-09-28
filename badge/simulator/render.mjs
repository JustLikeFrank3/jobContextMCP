// Render every screen of badge/jobcontext through the real Badgeware graphics
// stack, headlessly. See README.md in this directory.
//
//   git clone --depth 1 https://github.com/pimoroni/badgeware-web-simulator /tmp/websim
//   SIM_DIR=/tmp/websim node badge/simulator/render.mjs [out-dir]
//
// Needs Playwright (global or local) and a Chromium it can launch.
import fs from 'fs'
import http from 'http'
import path from 'path'
import { createRequire } from 'module'
import { fileURLToPath } from 'url'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PW_PATH || 'playwright')

const here = path.dirname(fileURLToPath(import.meta.url))
const appDir = path.join(here, '..', 'jobcontext')
const simDir = process.env.SIM_DIR
const outDir = process.argv[2] || path.join(here, 'out')
if (!simDir || !fs.existsSync(path.join(simDir, 'simulator', 'micropython.worker.js'))) {
  console.error('Set SIM_DIR to a clone of pimoroni/badgeware-web-simulator')
  process.exit(2)
}

const HARNESS = `<!doctype html><body style="margin:0;background:#000">
<canvas id="c" width="320" height="240"></canvas>
<script type="module">
const c = document.getElementById('c'), ctx = c.getContext('2d')
window.logs = []; window.shots = {}; let pending = null
const w = new Worker('simulator/micropython.worker.js', {type: 'module'})
w.onmessage = ({data}) => {
  if (data.stdout !== undefined) {
    window.logs.push(data.stdout)
    const m = /^SCENE (\\S+)/.exec(data.stdout)
    if (m) pending = {name: m[1], wait: 8}
  }
  if (data.frame) {
    const {buffer, width, height} = data.frame
    if (c.width !== width) { c.width = width; c.height = height }
    ctx.putImageData(new ImageData(new Uint8ClampedArray(buffer), width, height), 0, 0)
    if (pending && --pending.wait <= 0) { window.shots[pending.name] = c.toDataURL(); pending = null }
  }
  if (data.ready) w.postMessage({program: window.PROGRAM, files: window.FILES})
}
</script></body>`

const TYPES = {'.js': 'text/javascript', '.mjs': 'text/javascript', '.wasm': 'application/wasm', '.json': 'application/json', '.html': 'text/html'}
const server = http.createServer((req, res) => {
  const url = decodeURIComponent(req.url.split('?')[0])
  const headers = {'Cross-Origin-Opener-Policy': 'same-origin', 'Cross-Origin-Embedder-Policy': 'require-corp'}
  if (url === '/harness.html') {
    res.writeHead(200, {...headers, 'Content-Type': 'text/html'})
    return res.end(HARNESS)
  }
  const file = path.join(simDir, path.normalize(url))
  if (!file.startsWith(path.resolve(simDir)) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
    res.writeHead(404); return res.end()
  }
  res.writeHead(200, {...headers, 'Content-Type': TYPES[path.extname(file)] || 'application/octet-stream'})
  fs.createReadStream(file).pipe(res)
})
await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
const port = server.address().port

const files = fs.readdirSync(appDir).filter((f) => f.endsWith('.py') && f !== 'secrets.py')
  .map((f) => ({name: '/apps/jobcontext/' + f, content: fs.readFileSync(path.join(appDir, f), 'utf8')}))
const program = fs.readFileSync(path.join(here, 'scenes.py'), 'utf8')
const expected = (program.match(/^\s+\("\d\d-[^"]+"/gm) || []).length

const browser = await chromium.launch()
try {
  const page = await browser.newPage()
  page.on('pageerror', (e) => console.error('pageerror:', e.message))
  await page.addInitScript(([p, f]) => { window.PROGRAM = p; window.FILES = f }, [program, files])
  await page.goto(`http://127.0.0.1:${port}/harness.html`)

  const deadline = Date.now() + 120000
  let shots = {}, logs = []
  while (Date.now() < deadline) {
    await page.waitForTimeout(1000)
    shots = await page.evaluate(() => window.shots)
    logs = await page.evaluate(() => window.logs)
    if (Object.keys(shots).length >= expected || logs.some((l) => /Traceback|Error/.test(l))) break
  }
  const failed = logs.filter((l) => /Traceback|Error|File "/.test(l))
  if (failed.length) console.error(logs.slice(-15).join('\n'))

  fs.mkdirSync(outDir, {recursive: true})
  for (const [name, url] of Object.entries(shots)) {
    fs.writeFileSync(path.join(outDir, name + '.png'), Buffer.from(url.split(',')[1], 'base64'))
  }
  console.log(`rendered ${Object.keys(shots).length}/${expected} screens to ${outDir}`)
  process.exitCode = failed.length || Object.keys(shots).length < expected ? 1 : 0
} finally {
  await browser.close()
  server.close()
}
