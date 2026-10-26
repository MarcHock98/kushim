// kushim Oberfläche. Der Rustteil tut genau eines: Port und Token der lokalen Backend-API aus run/api.json lesen
// (geschrieben von `kushim serve`). Er öffnet kein Netz, startet nichts, schreibt nichts.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

#[derive(Serialize, Deserialize, Debug, PartialEq)]
struct ApiInfo {
    port: u16,
    token: String,
}

fn parse(text: &str) -> Result<ApiInfo, &'static str> {
    let info: ApiInfo = serde_json::from_str(text).map_err(|_| "bad_file")?;
    if info.port == 0 || info.token.len() < 32 {
        return Err("bad_file");
    }
    Ok(info)
}

/// Sucht `run/api.json` vom Programmort aufwärts (Entwicklung: ui/src-tauri/target/...), nur im Projektbaum.
fn find_info(start: &Path) -> Option<PathBuf> {
    start
        .ancestors()
        .map(|d| d.join("run").join("api.json"))
        .find(|p| p.is_file() && p.parent().and_then(|r| r.parent()).map_or(false, |root| root.join("pyproject.toml").is_file()))
}

#[tauri::command]
fn api_info() -> Result<ApiInfo, String> {
    let exe = std::env::current_exe().map_err(|_| "offline".to_string())?;
    let path = find_info(&exe).ok_or_else(|| "offline".to_string())?;
    let text = std::fs::read_to_string(path).map_err(|_| "offline".to_string())?;
    parse(&text).map_err(|e| e.to_string())
}

fn main() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![api_info])
        .run(tauri::generate_context!())
        .expect("kushim UI konnte nicht starten");
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn accepts_valid_file() {
        let t = format!(r#"{{"port": 5000, "token": "{}"}}"#, "a".repeat(43));
        assert_eq!(parse(&t).unwrap().port, 5000);
    }

    #[test]
    fn rejects_bad_files() {
        for t in [
            "",
            "{}",
            r#"{"port": 0, "token": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}"#,
            r#"{"port": 70000, "token": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}"#,
            r#"{"port": 5000, "token": "kurz"}"#,
        ] {
            assert!(parse(t).is_err(), "{t}");
        }
    }
}
