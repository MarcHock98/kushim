// kushim Oberfläche. Der Rustteil liest Port und Token der lokalen Backend-API aus run/api.json (geschrieben von
// `kushim serve`) und ändert auf Wunsch Größe und Lage des eigenen Fensters (E2, kleines Fenster).
// Er öffnet kein Netz, startet nichts, schreibt nichts und holt nie den Fokus.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use tauri::{LogicalSize, PhysicalPosition, PhysicalSize, State, UserAttentionType, WebviewWindow};

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

// ----- E2: kleines Fenster (docs/ui-e2e3-plan.md, Abschnitt 3) -----------------------------------------------------------
// Die Befehle ändern nur Größe, Lage und "immer im Vordergrund" des eigenen Fensters. Sie holen nie den Fokus (kein
// Fokus-Befehl), öffnen nichts, schreiben nichts. Eigene Befehle brauchen keine zusätzlichen Tauri-Rechte.

const COMPACT: (f64, f64) = (400.0, 200.0);
const COMPACT_MIN: (f64, f64) = (340.0, 180.0);
const APPROVAL: (f64, f64) = (420.0, 640.0);
const NORMAL_MIN: (f64, f64) = (360.0, 480.0);     // wie tauri.conf.json

/// Lage und Größe des großen Fensters vor dem Umschalten; dazu Größe und Lage des kleinen vor dem Wachsen für eine Freigabe.
#[derive(Default)]
struct WinMemory {
    compact: bool,
    grown: bool,
    big_size: Option<PhysicalSize<u32>>,
    big_pos: Option<PhysicalPosition<i32>>,
    big_maximized: bool,
    small_size: Option<PhysicalSize<u32>>,
    small_pos: Option<PhysicalPosition<i32>>,
}

/// Ein Schritt am eigenen Fenster. Die Reihenfolge legen `plan_compact` und `plan_grow` fest (ohne Fenster prüfbar).
#[derive(Debug, PartialEq, Clone, Copy)]
enum Step {
    Unmaximize,
    SaveBig,              // normale Größe und Lage merken (erst nach Unmaximize, sonst wären es die maximierten Maße)
    RestoreBig,
    Maximize,
    SaveSmall,            // Größe und Lage des kleinen Fensters merken (falls der Nutzer es verändert hat)
    RestoreSmall,
    MinSize(f64, f64),
    Fit(f64, f64),        // Innengröße setzen und ganz auf dem Bildschirm halten
    OnTop(bool),
}

/// Schritte für klein/groß. Leer, wenn das Fenster schon so ist (z. B. `set_compact(false)` beim Start nach F5).
fn plan_compact(on: bool, m: &WinMemory, maximized: bool) -> Vec<Step> {
    match (on, m.compact) {
        (true, false) => {
            let mut s = Vec::new();
            if maximized {
                s.push(Step::Unmaximize);
            }
            s.extend([Step::SaveBig, Step::MinSize(COMPACT_MIN.0, COMPACT_MIN.1), Step::Fit(COMPACT.0, COMPACT.1), Step::OnTop(true)]);
            s
        }
        (false, true) => {
            let mut s = vec![Step::OnTop(false), Step::MinSize(NORMAL_MIN.0, NORMAL_MIN.1), Step::RestoreBig];
            if m.big_maximized {
                s.push(Step::Maximize);
            }
            s
        }
        _ => Vec::new(),
    }
}

/// Schritte für die Freigabe im kleinen Fenster: wachsen, danach zurück auf die gemerkte kleine Größe und Lage.
fn plan_grow(on: bool, m: &WinMemory) -> Vec<Step> {
    if !m.compact || on == m.grown {
        return Vec::new();
    }
    if on {
        vec![Step::SaveSmall, Step::Fit(APPROVAL.0, APPROVAL.1)]
    } else {
        vec![Step::RestoreSmall]
    }
}

fn run(window: &WebviewWindow, m: &mut WinMemory, steps: &[Step]) -> Result<(), String> {
    for step in steps {
        match *step {
            Step::Unmaximize => window.unmaximize().map_err(fail)?,
            Step::SaveBig => {
                m.big_size = window.inner_size().ok();
                m.big_pos = window.outer_position().ok();
            }
            Step::RestoreBig => {
                if let Some(size) = m.big_size.take() {
                    window.set_size(size).map_err(fail)?;
                }
                if let Some(pos) = m.big_pos.take() {
                    window.set_position(pos).map_err(fail)?;
                }
            }
            Step::Maximize => window.maximize().map_err(fail)?,
            Step::SaveSmall => {
                m.small_size = window.inner_size().ok();
                m.small_pos = window.outer_position().ok();
            }
            Step::RestoreSmall => {
                match m.small_size.take() {
                    Some(size) => window.set_size(size).map_err(fail)?,
                    None => window.set_size(LogicalSize::new(COMPACT.0, COMPACT.1)).map_err(fail)?,
                }
                if let Some(pos) = m.small_pos.take() {
                    window.set_position(pos).map_err(fail)?;
                }
            }
            Step::MinSize(w, h) => window.set_min_size(Some(LogicalSize::new(w, h))).map_err(fail)?,
            Step::Fit(w, h) => resize_on_screen(window, w, h)?,
            Step::OnTop(on) => window.set_always_on_top(on).map_err(fail)?,
        }
    }
    Ok(())
}

#[derive(Default)]
struct WinState(Mutex<WinMemory>);

fn fail<E>(_: E) -> String {
    "window".to_string()
}

/// Schiebt ein Rechteck (Lage, Größe) in den Arbeitsbereich des Bildschirms; ist es größer, bleibt die linke obere Ecke sichtbar.
fn fit(pos: (i32, i32), size: (u32, u32), area_pos: (i32, i32), area_size: (u32, u32)) -> (i32, i32) {
    let axis = |p: i32, s: u32, ap: i32, asz: u32| -> i32 {
        let max = ap.saturating_add(asz as i32).saturating_sub(s as i32);
        p.min(max).max(ap)
    };
    (axis(pos.0, size.0, area_pos.0, area_size.0), axis(pos.1, size.1, area_pos.1, area_size.1))
}

/// Setzt die Innengröße (logische Pixel) und hält das Fenster dabei ganz auf seinem Bildschirm.
fn resize_on_screen(window: &WebviewWindow, w: f64, h: f64) -> Result<(), String> {
    let scale = window.scale_factor().map_err(fail)?;
    let pos = window.outer_position().map_err(fail)?;
    let inner = window.inner_size().map_err(fail)?;
    let outer = window.outer_size().map_err(fail)?;
    window.set_size(LogicalSize::new(w, h)).map_err(fail)?;
    if let Ok(Some(monitor)) = window.current_monitor() {
        let frame = (outer.width.saturating_sub(inner.width), outer.height.saturating_sub(inner.height));
        let target = ((w * scale).round() as u32 + frame.0, (h * scale).round() as u32 + frame.1);
        let area = monitor.work_area();
        let (x, y) = fit((pos.x, pos.y), target, (area.position.x, area.position.y), (area.size.width, area.size.height));
        if (x, y) != (pos.x, pos.y) {
            window.set_position(PhysicalPosition::new(x, y)).map_err(fail)?;
        }
    }
    Ok(())
}

/// Klein (etwa 400 x 200, immer im Vordergrund) oder zurück auf Größe und Lage von vorher (immer im Vordergrund aus).
#[tauri::command]
fn set_compact(on: bool, window: WebviewWindow, state: State<'_, WinState>) -> Result<(), String> {
    let mut m = state.0.lock().map_err(fail)?;
    let maximized = on && !m.compact && window.is_maximized().unwrap_or(false);
    let steps = plan_compact(on, &m, maximized);
    if steps.is_empty() {
        return Ok(());
    }
    if on {
        *m = WinMemory { big_maximized: maximized, ..WinMemory::default() };
        run(&window, &mut m, &steps)?;
        m.compact = true;
    } else {
        run(&window, &mut m, &steps)?;
        *m = WinMemory::default();
    }
    Ok(())
}

/// "Immer im Vordergrund" an oder aus (Knopf im kleinen Fenster).
#[tauri::command]
fn set_always_on_top(on: bool, window: WebviewWindow) -> Result<(), String> {
    window.set_always_on_top(on).map_err(fail)
}

/// Freigabe offen im kleinen Fenster: auf 420 x 640 wachsen, danach zurück auf die vorige kleine Größe und Lage. Nur im kleinen Modus.
#[tauri::command]
fn grow_for_approval(on: bool, window: WebviewWindow, state: State<'_, WinState>) -> Result<(), String> {
    let mut m = state.0.lock().map_err(fail)?;
    let steps = plan_grow(on, &m);
    if steps.is_empty() {
        return Ok(());
    }
    run(&window, &mut m, &steps)?;
    m.grown = on;
    Ok(())
}

/// Taskleiste blinken lassen, bis der Nutzer das Fenster selbst nach vorn holt. Holt nie den Fokus.
#[tauri::command]
fn attention(window: WebviewWindow) -> Result<(), String> {
    window.request_user_attention(Some(UserAttentionType::Informational)).map_err(fail)
}

fn main() {
    tauri::Builder::default()
        .manage(WinState::default())
        .invoke_handler(tauri::generate_handler![api_info, set_compact, set_always_on_top, grow_for_approval, attention])
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

    #[test]
    fn fit_keeps_the_window_on_the_screen() {
        let area = ((0, 0), (1920, 1040));
        assert_eq!(fit((100, 100), (420, 640), area.0, area.1), (100, 100));      // passt: bleibt
        assert_eq!(fit((1800, 900), (420, 640), area.0, area.1), (1500, 400));    // rechts unten: hineingeschoben
        assert_eq!(fit((-50, -20), (420, 640), area.0, area.1), (0, 0));          // links oben
        assert_eq!(fit((0, 0), (3000, 2000), area.0, area.1), (0, 0));            // zu groß: linke obere Ecke sichtbar
        assert_eq!(fit((2000, 10), (400, 200), (1920, 0), (1280, 1000)), (2000, 10)); // zweiter Bildschirm rechts
    }

    #[test]
    fn compact_reads_the_normal_size_only_after_unmaximize() {
        let big = WinMemory::default();
        let s = plan_compact(true, &big, true);
        assert_eq!(&s[..2], &[Step::Unmaximize, Step::SaveBig]);
        assert_eq!(s.last(), Some(&Step::OnTop(true)));
        let s = plan_compact(true, &big, false);
        assert!(!s.contains(&Step::Unmaximize) && s[0] == Step::SaveBig);
    }

    #[test]
    fn back_to_big_restores_and_maximizes_again_only_if_it_was_maximized() {
        let small = WinMemory { compact: true, big_maximized: true, ..WinMemory::default() };
        let s = plan_compact(false, &small, false);
        assert_eq!(s, vec![Step::OnTop(false), Step::MinSize(NORMAL_MIN.0, NORMAL_MIN.1), Step::RestoreBig, Step::Maximize]);
        let small = WinMemory { compact: true, ..WinMemory::default() };
        assert!(!plan_compact(false, &small, false).contains(&Step::Maximize));
    }

    #[test]
    fn nothing_happens_when_the_window_already_is_in_that_mode() {
        assert!(plan_compact(false, &WinMemory::default(), false).is_empty());      // Start nach F5: set_compact(false) ist harmlos
        let small = WinMemory { compact: true, ..WinMemory::default() };
        assert!(plan_compact(true, &small, false).is_empty());
        assert!(plan_grow(true, &WinMemory::default()).is_empty());                 // groß: nie wachsen
        assert!(plan_grow(false, &small).is_empty());                               // nicht gewachsen: nichts zurück
    }

    #[test]
    fn approval_growth_remembers_and_restores_the_small_window() {
        let small = WinMemory { compact: true, ..WinMemory::default() };
        assert_eq!(plan_grow(true, &small), vec![Step::SaveSmall, Step::Fit(APPROVAL.0, APPROVAL.1)]);
        let grown = WinMemory { compact: true, grown: true, ..WinMemory::default() };
        assert_eq!(plan_grow(false, &grown), vec![Step::RestoreSmall]);
        assert!(plan_grow(true, &grown).is_empty());
    }
}
