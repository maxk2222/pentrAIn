//! Local tmux driver — the same commands coach_bridge builds remotely via
//! QGA, executed directly. Keeping tmux as the I/O surface means the trainee
//! still watches the coach type on the desktop ('pentrain-coach' session).

use anyhow::{bail, Context, Result};
use tokio::process::Command;

pub const COACH_TMUX: &str = "pentrain-coach";
const SHELLS: &[&str] = &["bash", "zsh", "sh", "dash", "ksh", "fish"];

/// pane target: main coach pane is the bare session name, workers get named
/// windows (pentrain-coach:w1..w4). Name interpolates unquoted into -t, so
/// it is validated (port of coach_bridge._WINDOW_OK).
pub fn pane_target(window: Option<&str>) -> String {
    match window {
        Some(w) if !w.is_empty() && w != "main" => format!("{COACH_TMUX}:{w}"),
        _ => COACH_TMUX.to_string(),
    }
}

pub fn valid_window(w: &str) -> bool {
    !w.is_empty()
        && w.len() <= 16
        && w.chars().all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-')
}

async fn sh(cmd: &str) -> Result<String> {
    let out = Command::new("/bin/sh")
        .args(["-c", cmd])
        .output()
        .await
        .context("spawn sh")?;
    Ok(String::from_utf8_lossy(&out.stdout).into_owned())
}

async fn tmux(args: &[&str]) -> Result<String> {
    let out = Command::new("tmux")
        .args(args)
        .output()
        .await
        .context("spawn tmux")?;
    if !out.status.success() {
        bail!("tmux {:?} failed: {}", args, String::from_utf8_lossy(&out.stderr));
    }
    Ok(String::from_utf8_lossy(&out.stdout).into_owned())
}

/// Worker-window ensure (port of coach_bridge._tmux_ensure_sh): create the
/// named window inside pentrain-coach if missing; idempotent.
async fn ensure_window(window: Option<&str>) -> Result<()> {
    if matches!(window, None | Some("") | Some("main")) {
        return Ok(());
    }
    let w = window.unwrap();
    // tmux neww -d -n <w> -t <session>: if the window exists already this
    // errors — check first so it stays idempotent.
    let list = tmux(&["list-windows", "-t", COACH_TMUX, "-F", "#{window_name}"])
        .await
        .unwrap_or_default();
    if !list.lines().any(|l| l.trim() == w) {
        let _ = tmux(&["new-window", "-d", "-n", w, "-t", COACH_TMUX]).await;
    }
    Ok(())
}

/// Make sure the coach tmux session exists (detached create is fine — the
/// desktop xfce login attaches to the same session when it comes up).
pub async fn ensure_session(window: Option<&str>) -> Result<()> {
    if Command::new("tmux")
        .args(["has-session", "-t", COACH_TMUX])
        .output()
        .await
        .map(|o| !o.status.success())
        .unwrap_or(true)
    {
        let _ = tmux(&["new-session", "-d", "-s", COACH_TMUX]).await;
    }
    ensure_window(window).await
}

pub async fn pane_current_command(window: Option<&str>) -> String {
    tmux(&[
        "display-message",
        "-p",
        "-t",
        &pane_target(window),
        "#{pane_current_command}",
    ])
    .await
    .map(|s| s.trim().to_string())
    .unwrap_or_default()
}

pub fn is_shell_fg(fg: &str) -> bool {
    fg.is_empty() || SHELLS.contains(&fg)
}

/// Last non-empty pane line (continuation-prompt detection).
pub async fn last_pane_line(window: Option<&str>) -> String {
    sh(&format!(
        "tmux capture-pane -pt {} 2>/dev/null | grep -v '^$' | tail -1",
        shell_quote(&pane_target(window))
    ))
    .await
    .map(|s| s.trim_end().to_string())
    .unwrap_or_default()
}

/// Full scrollback tail: capture-pane -pJ -t <target> -S -1500 | tail -800
/// (joins wrapped lines so each typed line maps to exactly one pane line).
pub async fn capture_tail(window: Option<&str>) -> Result<Vec<String>> {
    let out = sh(&format!(
        "tmux capture-pane -pJ -t {} -S -1500 2>/dev/null | tail -800",
        shell_quote(&pane_target(window))
    ))
    .await?;
    Ok(out.split('\n').map(|l| l.trim_end().to_string()).collect())
}

pub async fn capture_history_cursor(window: Option<&str>) -> (i64, i64) {
    let out = tmux(&[
        "display-message",
        "-p",
        "-t",
        &pane_target(window),
        "#{history_size} #{cursor_y}",
    ])
    .await
    .unwrap_or_default();
    let mut it = out.split_whitespace();
    let h = it.next().and_then(|x| x.parse().ok()).unwrap_or(-1);
    let c = it.next().and_then(|x| x.parse().ok()).unwrap_or(0);
    (h, c)
}

pub async fn send_literal(window: Option<&str>, text: &str) -> Result<()> {
    tmux(&["send-keys", "-t", &pane_target(window), "-l", text]).await?;
    Ok(())
}

pub async fn send_enter(window: Option<&str>) -> Result<()> {
    tmux(&["send-keys", "-t", &pane_target(window), "Enter"]).await?;
    Ok(())
}

pub async fn send_ctrl(window: Option<&str>, key: &str) -> Result<()> {
    // key arrives as "C-c" already
    tmux(&["send-keys", "-t", &pane_target(window), key]).await?;
    Ok(())
}

pub fn shell_quote(s: &str) -> String {
    format!("'{}'", s.replace('\'', "'\\''"))
}
