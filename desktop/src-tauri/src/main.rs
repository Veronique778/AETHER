//! AETHER desktop shell (Tauri 2).
//!
//! Responsibilities – nothing visual: the window shows the unchanged AETHER v0.5 web UI.
//!  1. pick a free 127.0.0.1 port and start the bundled backend sidecar (`aether-backend`) with the
//!     per-user data directory (AETHER_DB_PATH) and this process id (so it exits if we crash);
//!  2. tell the UI where the backend is via `window.__AETHER_DESKTOP__` (initialization script);
//!  3. stop the backend when AETHER exits.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::Write;
use std::net::TcpListener;
use std::sync::Mutex;

use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

/// Handle of the running backend sidecar, killed on exit.
struct Backend(Mutex<Option<CommandChild>>);

const TITLE: &str = "AETHER — Adaptive Ecosystem for Human Exploration and Resilience";

/// Ask the OS for an unused loopback port (bound to 127.0.0.1 only).
fn free_port() -> u16 {
    TcpListener::bind("127.0.0.1:0")
        .and_then(|l| l.local_addr())
        .map(|a| a.port())
        .unwrap_or(8765)
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(Backend(Mutex::new(None)))
        .setup(|app| {
            let port = free_port();
            let data_dir = app.path().app_data_dir()?;
            let log_dir = app.path().app_log_dir()?;
            std::fs::create_dir_all(&data_dir)?;
            std::fs::create_dir_all(&log_dir)?;
            let db_path = data_dir.join("aether.sqlite3");
            let log_path = log_dir.join("backend.log");
            // Keep the previous run's log for diagnostics.
            let _ = std::fs::rename(&log_path, log_dir.join("backend.prev.log"));

            let mut backend_error: Option<String> = None;
            match app.shell().sidecar("aether-backend") {
                Ok(cmd) => {
                    let cmd = cmd
                        .args([
                            "--port".to_string(),
                            port.to_string(),
                            "--parent-pid".to_string(),
                            std::process::id().to_string(),
                        ])
                        .env("AETHER_DB_PATH", db_path.to_string_lossy().to_string())
                        .env(
                            "AETHER_CORS_ORIGINS",
                            "http://tauri.localhost,https://tauri.localhost,tauri://localhost",
                        );
                    match cmd.spawn() {
                        Ok((mut rx, child)) => {
                            *app.state::<Backend>().0.lock().unwrap() = Some(child);
                            let log_path = log_path.clone();
                            tauri::async_runtime::spawn(async move {
                                let mut log = std::fs::OpenOptions::new()
                                    .create(true)
                                    .append(true)
                                    .open(&log_path)
                                    .ok();
                                while let Some(event) = rx.recv().await {
                                    let line = match event {
                                        CommandEvent::Stdout(b) | CommandEvent::Stderr(b) => {
                                            String::from_utf8_lossy(&b).trim_end().to_string()
                                        }
                                        CommandEvent::Terminated(t) => format!(
                                            "backend terminated: code={:?} signal={:?}",
                                            t.code, t.signal
                                        ),
                                        CommandEvent::Error(e) => format!("backend error: {e}"),
                                        _ => continue,
                                    };
                                    if let Some(f) = log.as_mut() {
                                        let _ = writeln!(f, "{line}");
                                    }
                                }
                            });
                        }
                        Err(e) => {
                            backend_error =
                                Some(format!("could not start the bundled backend: {e}"))
                        }
                    }
                }
                Err(e) => backend_error = Some(format!("bundled backend not found: {e}")),
            }

            let info = serde_json::json!({
                "apiBase": format!("http://127.0.0.1:{port}"),
                "version": app.package_info().version.to_string(),
                "dataDir": data_dir,
                "logFile": log_path,
                "backendError": backend_error,
            });
            let init = format!("window.__AETHER_DESKTOP__ = Object.freeze({info});");

            WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
                .title(TITLE)
                .inner_size(1600.0, 960.0)
                .min_inner_size(1024.0, 680.0)
                .resizable(true)
                .maximizable(true)
                .center()
                .background_color(tauri::window::Color(3, 11, 23, 255))
                .initialization_script(&init)
                .build()?;
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building AETHER")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                if let Some(child) = app.state::<Backend>().0.lock().unwrap().take() {
                    let _ = child.kill();
                }
            }
        });
}
