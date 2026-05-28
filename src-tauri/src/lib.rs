// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::path::Path;
use std::process::{Command, Stdio};
use std::thread;

#[tauri::command]
fn greet(name: &str) -> String {
    format!("Hello, {}! You've been greeted from Rust!", name)
}

/// Returns the Python backend WebSocket URL so React can connect directly.
#[tauri::command]
fn get_backend_url() -> String {
    "ws://127.0.0.1:8765".to_string()
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .setup(|_app| {
            // env!("CARGO_MANIFEST_DIR") is `src-tauri/` at compile time.
            // parent() gives the project root: `Oryonix_for_desktop/`
            let project_root = Path::new(env!("CARGO_MANIFEST_DIR"))
                .parent()
                .expect("CARGO_MANIFEST_DIR has no parent directory")
                .to_path_buf();

            let script = project_root.join("agent_backend").join("main.py");
            
            let venv_python = if cfg!(windows) {
                project_root.join(".venv").join("Scripts").join("python.exe")
            } else {
                project_root.join(".venv").join("bin").join("python")
            };

            let python_bin = if venv_python.exists() {
                venv_python
            } else {
                std::path::PathBuf::from(if cfg!(windows) { "python" } else { "python3" })
            };

            thread::spawn(move || {
                match Command::new(&python_bin)
                    .arg(&script)
                    .current_dir(&project_root)
                    .stdout(Stdio::inherit()) // Python logs appear in Tauri dev console
                    .stderr(Stdio::inherit())
                    .spawn()
                {
                    Ok(mut child) => {
                        eprintln!("[Oryonix] Python backend started (pid {})", child.id());
                        let _ = child.wait();
                        eprintln!("[Oryonix] Python backend process exited");
                    }
                    Err(e) => {
                        eprintln!(
                            "[Oryonix] Failed to start Python backend: {e}\n\
                             Make sure Python is in PATH and run:\n\
                             cd agent_backend && pip install -r requirements.txt"
                        );
                    }
                }
            });

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![greet, get_backend_url])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
