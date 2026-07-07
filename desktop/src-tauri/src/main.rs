// jobContext Desktop shell.
//
// Lifecycle (see docs/desktop/ROADMAP.md "Shell contract"):
//   1. Spawn the PyInstaller onedir sidecar from the bundle's resource dir.
//   2. Read its stdout for the stable `JOBCONTEXT_PORT=<port>` line.
//   3. Poll GET /healthz until 200, then point the webview (showing the
//      bundled splash page until then) at http://127.0.0.1:<port>/app.
//   4. On exit: POST /desktop/shutdown, give the backend a moment to stop
//      cleanly, then kill as a last resort — never orphan the backend.
//
// Single-instance: a second launch focuses the existing window instead of
// spawning a second backend against the same SQLite file.

#![cfg_attr(all(not(debug_assertions), target_os = "windows"), windows_subsystem = "windows")]

use std::io::{BufRead, BufReader, Read, Write};
use std::net::TcpStream;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::{Manager, RunEvent};

struct Backend {
    child: Child,
    port: u16,
}

struct BackendState(Mutex<Option<Backend>>);

fn backend_exe(app: &tauri::AppHandle) -> Result<std::path::PathBuf, String> {
    let exe = if cfg!(windows) { "jobcontext-backend.exe" } else { "jobcontext-backend" };
    // Bundled: resources/binaries/jobcontext-backend/<exe> (tauri.conf.json).
    // Dev fallback (`tauri dev` without a bundle): repo dist/ from a local
    // `pyinstaller packaging/pyinstaller/jobcontext-backend.spec` build.
    let resource = app
        .path()
        .resource_dir()
        .map(|d| d.join("binaries").join("jobcontext-backend").join(exe))
        .map_err(|e| e.to_string())?;
    if resource.is_file() {
        return Ok(resource);
    }
    let dev = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../dist/jobcontext-backend")
        .join(exe);
    if dev.is_file() {
        return Ok(dev);
    }
    Err(format!(
        "backend binary not found (looked in {resource:?} and {dev:?}); \
         build it with: pyinstaller packaging/pyinstaller/jobcontext-backend.spec"
    ))
}

fn spawn_backend(app: &tauri::AppHandle) -> Result<Backend, String> {
    let bin = backend_exe(app)?;
    // stdin stays piped and held open for our whole lifetime: the backend's
    // --parent-watchdog exits on stdin EOF, so even a SIGKILL to this shell
    // (which fires no Tauri exit event) can't orphan the backend against the
    // SQLite file.
    let mut child = Command::new(&bin)
        .arg("--parent-watchdog")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .spawn()
        .map_err(|e| format!("failed to spawn {bin:?}: {e}"))?;

    let stdout = child.stdout.take().ok_or("backend stdout not captured")?;
    let mut reader = BufReader::new(stdout);
    let deadline = Instant::now() + Duration::from_secs(30);
    let mut line = String::new();
    let port: u16 = loop {
        if Instant::now() > deadline {
            let _ = child.kill();
            return Err("timed out waiting for JOBCONTEXT_PORT line".into());
        }
        line.clear();
        match reader.read_line(&mut line) {
            Ok(0) => {
                return Err("backend exited before printing its port".into());
            }
            Ok(_) => {
                if let Some(rest) = line.trim().strip_prefix("JOBCONTEXT_PORT=") {
                    match rest.parse() {
                        Ok(p) => break p,
                        Err(e) => return Err(format!("unparseable port {rest:?}: {e}")),
                    }
                }
            }
            Err(e) => return Err(format!("reading backend stdout: {e}")),
        }
    };

    // Keep draining stdout so the backend never blocks on a full pipe.
    std::thread::spawn(move || {
        let mut sink = String::new();
        while matches!(reader.read_line(&mut sink), Ok(n) if n > 0) {
            sink.clear();
        }
    });

    Ok(Backend { child, port })
}

fn http_request(port: u16, request_head: &str) -> Option<String> {
    let mut stream = TcpStream::connect(("127.0.0.1", port)).ok()?;
    stream.set_read_timeout(Some(Duration::from_secs(2))).ok()?;
    stream
        .write_all(
            format!("{request_head} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n")
                .as_bytes(),
        )
        .ok()?;
    let mut response = String::new();
    let _ = stream.read_to_string(&mut response);
    Some(response)
}

fn wait_healthy(port: u16, timeout: Duration) -> bool {
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        if let Some(resp) = http_request(port, "GET /healthz") {
            if resp.starts_with("HTTP/1.1 200") {
                return true;
            }
        }
        std::thread::sleep(Duration::from_millis(200));
    }
    false
}

fn stop_backend(state: &BackendState) {
    if let Some(mut backend) = state.0.lock().unwrap().take() {
        // Ask nicely first so SQLite/WAL closes cleanly…
        let _ = http_request(backend.port, "POST /desktop/shutdown");
        let deadline = Instant::now() + Duration::from_secs(5);
        while Instant::now() < deadline {
            if matches!(backend.child.try_wait(), Ok(Some(_))) {
                return;
            }
            std::thread::sleep(Duration::from_millis(100));
        }
        // …then make sure no orphan survives.
        let _ = backend.child.kill();
        let _ = backend.child.wait();
    }
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.unminimize();
                let _ = window.set_focus();
            }
        }))
        .manage(BackendState(Mutex::new(None)))
        .setup(|app| {
            let handle = app.handle().clone();
            std::thread::spawn(move || {
                let result = spawn_backend(&handle).and_then(|backend| {
                    if !wait_healthy(backend.port, Duration::from_secs(30)) {
                        return Err("backend never became healthy".into());
                    }
                    Ok(backend)
                });
                let window = handle.get_webview_window("main");
                match result {
                    Ok(backend) => {
                        let port = backend.port;
                        *handle.state::<BackendState>().0.lock().unwrap() = Some(backend);
                        if let Some(w) = window {
                            let _ = w.eval(&format!(
                                "window.location.replace('http://127.0.0.1:{port}/app')"
                            ));
                        }
                    }
                    Err(message) => {
                        if let Some(w) = window {
                            let escaped = message.replace('\\', "\\\\").replace('\'', "\\'");
                            let _ = w.eval(&format!(
                                "document.getElementById('status').textContent = 'Startup failed: {escaped}'"
                            ));
                        }
                    }
                }
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building jobContext Desktop")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                stop_backend(&app.state::<BackendState>());
            }
        });
}
