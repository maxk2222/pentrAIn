//! Exec channel — the coach-visible command path.
//!
//! One persistent outbound WS per session: /api/agent/kali/{sid}?token=.
//! Backend requests drive the SAME tmux pane the desktop shows — the
//! semantics of exec_visible_in_kali, minus the QGA hop (local tmux calls
//! at ~50ms poll cadence instead of HTTPS→PVE→QGA round-trips).
//!
//! Frames (text/JSON):
//!   in : {"t":"exec","id":N,"cmd":..,"window":..,"timeout_s":60}
//!        {"t":"type","id":N,"text":..,"window":..}
//!        {"t":"peek","id":N,"window":..}
//!        {"t":"ctrl","id":N,"key":"c","window":..}
//!        {"t":"raw","id":N,"cmd":..,"timeout_s":..}   (no tmux — flag checks)
//!   out: {"t":"hello","agent":"pentrain-agent","v":1}
//!        {"t":"exec_out","id":N,"data":..}           (live tail deltas)
//!        {"t":"exec_done","id":N,...}                (the bridge result dict)

use serde_json::{json, Value};
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::sync::{mpsc, Mutex};

use crate::conf::ConfWatcher;
use crate::tmux;

const POLL_MS: u64 = 50;
const AGENT_VER: u64 = 1;

fn hex(n: usize) -> String {
    use std::time::{SystemTime, UNIX_EPOCH};
    let t = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    format!("{t:05x}")[..n.min(10)].to_string()
}

/// Port of the bridge's busy-checks + marker protocol. All tmux ops are
/// local — identical semantics, no guest-agent round-trip per probe.
pub async fn exec_visible(cmd: &str, window: Option<&str>, timeout_s: u64,
                          stream: &mpsc::Sender<String>) -> Value {
    let w = match window {
        Some(w) if tmux::valid_window(w) || w == "main" => Some(w),
        Some(w) => return err_val(format!("invalid pane window name {w:?}")),
        None => None,
    };
    if let Err(e) = tmux::ensure_session(w).await {
        return err_val(format!("tmux session: {e}"));
    }
    // ctrl-key passthrough — typed as real keys, not text
    let trimmed = cmd.trim();
    if trimmed.len() == 3 && trimmed.starts_with("C-") {
        let k = &trimmed[2..];
        if k.len() == 1 && k.chars().next().unwrap().is_ascii_lowercase() {
            let _ = tmux::send_ctrl(w, trimmed).await;
            tokio::time::sleep(Duration::from_millis(400)).await;
            let now = tmux::pane_current_command(w).await;
            let state = if tmux::is_shell_fg(&now) {
                format!("pane free — shell '{now}' at prompt")
            } else {
                format!("still busy — foreground: '{now}'")
            };
            return json!({"out": format!("(sent {trimmed} — {state})"),
                          "err": "", "exitcode": 0, "visible": true});
        }
    }

    let fg = tmux::pane_current_command(w).await;
    if !tmux::is_shell_fg(&fg) {
        return json!({"out": "", "visible": true, "busy": true,
                      "exitcode": Value::Null,
                      "err": format!("pane busy: '{fg}' is running interactively — use type_in_pane to send input lines into it (e.g. passwords, menu choices), or send 'C-c' via exec_in_kali to interrupt it")});
    }
    let last = tmux::last_pane_line(w).await;
    if is_continuation(&last) {
        return json!({"out": "", "visible": true, "busy": true,
                      "exitcode": Value::Null,
                      "err": format!("pane busy: shell awaits more input ({:?} — unfinished heredoc/quote?) — use type_in_pane to send the missing line/delimiter, or 'C-c' via exec_in_kali to reset the prompt", &last[last.len().saturating_sub(40)..])});
    }

    let marker = format!("PTN{}", hex(10));
    // long/multiline → script file (QGA wedged on embedded heredocs — the
    // local path keeps the same safety for the pane)
    let typed_line = if cmd.contains('\n') || cmd.len() > 180 {
        let script = format!("/tmp/ptn-{marker}.sh");
        let _ = std::fs::write(&script, format!("{cmd}\n"));
        format!("bash {script}")
    } else {
        cmd.to_string()
    };
    let n_cmd_lines = typed_line.matches('\n').count() + 1;
    let cmd_tail: String = typed_line
        .split('\n')
        .last()
        .unwrap_or("")
        .chars()
        .rev()
        .take(60)
        .collect::<String>()
        .chars()
        .rev()
        .collect::<String>()
        .trim_end()
        .to_string();

    let _ = tmux::send_literal(w, &format!("echo {marker}A")).await;
    let _ = tmux::send_enter(w).await;
    let _ = tmux::send_literal(w, &typed_line).await;
    let _ = tmux::send_enter(w).await;

    let mut b_sent = false;
    let mut last_tail = String::new();
    let deadline = Instant::now() + Duration::from_secs(timeout_s);
    while Instant::now() < deadline {
        let lines = match tmux::capture_tail(w).await {
            Ok(l) => l,
            Err(_) => {
                tokio::time::sleep(Duration::from_millis(POLL_MS)).await;
                continue;
            }
        };
        // find markers (real output lines only — anchored at line end)
        let mut ai: i64 = -1;
        let mut bi: i64 = -1;
        let mut exitcode = 0i64;
        for i in (0..lines.len()).rev() {
            let ln = lines[i].trim_end();
            if bi < 0 {
                if let Some(rest) = ln.strip_prefix(&format!("{marker}B:")) {
                    if let Ok(c) = rest.trim().parse::<i64>() {
                        bi = i as i64;
                        exitcode = c;
                    }
                }
            }
            if ai < 0 && ln.ends_with(&format!("{marker}A")) {
                ai = i as i64;
            }
            if ai >= 0 && bi >= 0 {
                break;
            }
        }
        if ai >= 0 && bi >= 0 {
            let a = ai as usize;
            let b = bi as usize;
            let typed_end = (a + 1..b.saturating_sub(1).max(a + 1))
                .rev()
                .find(|&i| !cmd_tail.is_empty() && lines[i].trim_end().ends_with(&cmd_tail))
                .unwrap_or(a + n_cmd_lines);
            let mut out_lines: Vec<&String> = lines
                .get(typed_end + 1..b.saturating_sub(1).max(typed_end + 1))
                .unwrap_or(&[])
                .iter()
                .filter(|ln| !ln.trim().is_empty() && !ln.contains(&marker))
                .collect();
            if let Some(last_l) = out_lines.last() {
                if prompt_half(last_l) {
                    out_lines.pop();
                }
            }
            let joined = out_lines
                .iter()
                .map(|s| s.as_str())
                .collect::<Vec<_>>()
                .join("\n");
            let out: String = joined.chars().rev().take(4000).collect::<String>().chars().rev().collect();
            return json!({"out": out, "err": "", "exitcode": exitcode,
                          "visible": true});
        }
        if ai >= 0 {
            let a = ai as usize;
            let typed_end = (a + 1..lines.len())
                .rev()
                .find(|&i| !cmd_tail.is_empty() && lines[i].trim_end().ends_with(&cmd_tail))
                .unwrap_or((a + n_cmd_lines).min(lines.len().saturating_sub(1)));
            let tail: String = lines
                .get(typed_end + 1..)
                .unwrap_or(&[])
                .iter()
                .filter(|ln| !ln.trim().is_empty() && !ln.contains(&marker))
                .map(|s| s.as_str())
                .collect::<Vec<_>>()
                .join("\n")
                .chars()
                .rev()
                .take(3000)
                .collect::<String>()
                .chars()
                .rev()
                .collect();
            if tail != last_tail {
                last_tail = tail.clone();
                let _ = stream.try_send(tail);
            }
            if !b_sent {
                let fg_now = tmux::pane_current_command(w).await;
                let typed_seen = cmd_tail.is_empty()
                    || lines[a..]
                        .iter()
                        .any(|ln| ln.trim_end().ends_with(&cmd_tail));
                let last_ln = lines
                    .iter()
                    .rev()
                    .find(|ln| !ln.trim().is_empty())
                    .map(|ln| ln.trim().to_string())
                    .unwrap_or_default();
                if tmux::is_shell_fg(&fg_now)
                    && typed_seen
                    && last_ln != ">"
                    && !is_continuation(&last_ln)
                {
                    let _ = tmux::send_literal(w, &format!("echo {marker}B:$?")).await;
                    let _ = tmux::send_enter(w).await;
                    b_sent = true;
                }
            }
        }
        tokio::time::sleep(Duration::from_millis(POLL_MS)).await;
    }
    json!({
        "out": if last_tail.is_empty() {
            "(still running — visible in the pentrain-coach tmux window)".to_string()
        } else { last_tail },
        "err": "still running — pane is now busy; further commands bounce until it finishes or you send 'C-c'. If it is waiting for INPUT (password/menu prompt), answer NOW with type_in_pane — prompts time out",
        "exitcode": Value::Null, "visible": true, "timed_out": true})
}

/// type_in_pane — literal text + Enter into a busy pane, return the slice
/// the typing produced (echo + effect + new prompt), plus fg/busy.
pub async fn type_in_pane(text: &str, window: Option<&str>) -> Value {
    let w = match window {
        Some(w) if tmux::valid_window(w) || w == "main" => Some(w),
        _ => None,
    };
    if let Err(e) = tmux::ensure_session(w).await {
        return err_val(format!("tmux session: {e}"));
    }
    let (h0, cy0) = tmux::capture_history_cursor(w).await;
    let _ = tmux::send_literal(w, text).await;
    let _ = tmux::send_enter(w).await;
    tokio::time::sleep(Duration::from_millis(600)).await;
    let lines = tmux::capture_tail(w).await.unwrap_or_default();
    let cur = tmux::pane_current_command(w).await;
    let out: String = if h0 >= 0 && (h0 + cy0) < lines.len() as i64 {
        lines[(h0 + cy0) as usize..]
            .join("\n")
            .chars()
            .rev()
            .take(3000)
            .collect::<String>()
            .chars()
            .rev()
            .collect()
    } else {
        lines
            .iter()
            .rev()
            .take(50)
            .cloned()
            .collect::<Vec<_>>()
            .into_iter()
            .rev()
            .collect::<Vec<_>>()
            .join("\n")
            .chars()
            .rev()
            .take(3000)
            .collect::<String>()
            .chars()
            .rev()
            .collect()
    };
    let busy = !tmux::is_shell_fg(&cur);
    json!({"out": out, "visible": true, "exitcode": Value::Null,
           "current_command": cur, "busy": busy})
}

/// peek_pane — read-only tail + foreground command.
pub async fn peek_pane(window: Option<&str>) -> Value {
    let w = match window {
        Some(w) if tmux::valid_window(w) || w == "main" => Some(w),
        _ => None,
    };
    let lines = tmux::capture_tail(w).await.unwrap_or_default();
    let cur = tmux::pane_current_command(w).await;
    let out = lines
        .iter()
        .rev()
        .take(50)
        .cloned()
        .collect::<Vec<_>>()
        .into_iter()
        .rev()
        .collect::<Vec<_>>()
        .join("\n")
        .chars()
        .rev()
        .take(3000)
        .collect::<String>()
        .chars()
        .rev()
        .collect::<String>();
    let busy = !tmux::is_shell_fg(&cur);
    json!({"out": out, "current_command": cur, "busy": busy,
           "exists": !out.trim().is_empty() || !cur.is_empty()})
}

/// raw — invisible exec for flag checks; structured out/err/exit.
pub async fn raw_exec(cmd: &str, timeout_s: u64) -> Value {
    let child = tokio::process::Command::new("/bin/sh")
        .args(["-c", cmd])
        .output();
    match tokio::time::timeout(Duration::from_secs(timeout_s.max(5)), child).await {
        Ok(Ok(o)) => json!({
            "out": String::from_utf8_lossy(&o.stdout),
            "err": String::from_utf8_lossy(&o.stderr),
            "exitcode": o.status.code().unwrap_or(-1)}),
        Ok(Err(e)) => err_val(format!("spawn: {e}")),
        Err(_) => json!({"out": "", "err": "timeout", "exitcode": 124}),
    }
}

/// Port of `re.search(r"(heredoc|dquote|quote|pipe)?>\s*$", last) and last != ">"`
/// — line ends in `>` (optional PS2 word prefix) but a bare `>` alone
/// doesn't count (that's the prompt the b-marker logic handles itself).
fn is_continuation(line: &str) -> bool {
    let l = line.trim_end();
    l != ">" && l.ends_with('>')
}

fn prompt_half(line: &str) -> bool {
    // `(host)-[cwd]` first half of the two-line zsh prompt
    let l = line.trim_end();
    l.contains(")-[") && l.ends_with(']')
}

fn err_val(msg: String) -> Value {
    json!({"error": msg, "status": "error"})
}

/// WS loop — re-dials forever, conf-driven (token rotation on reset).
pub async fn run(mut watcher: ConfWatcher) {
    use futures::{SinkExt, StreamExt};
    use tokio_tungstenite::tungstenite::Message;

    loop {
        watcher.refresh();
        let conf = watcher.current.clone();
        if !conf.exec || conf.session.is_empty() || conf.token.is_empty()
            || conf.api.is_empty()
        {
            tokio::time::sleep(Duration::from_secs(2)).await;
            continue;
        }
        let url = format!(
            "{}/api/agent/kali/{}?token={}",
            conf.ws_base(), conf.session, conf.token
        );
        let ws = match tokio_tungstenite::connect_async(&url).await {
            Ok((w, _)) => w,
            Err(e) => {
                tracing::warn!(error = %e, "agent ws dial failed");
                tokio::time::sleep(Duration::from_secs(3)).await;
                continue;
            }
        };
        let (mut tx, mut rx) = ws.split();
        let _ = tx
            .send(Message::Text(
                json!({"t": "hello", "agent": "pentrain-agent", "v": AGENT_VER})
                    .to_string(),
            ))
            .await;
        let tx = Arc::new(Mutex::new(tx));
        tracing::info!("exec channel connected");
        while let Some(msg) = rx.next().await {
            // conf rotated mid-connection → drop and re-dial with new token
            if watcher.refresh() {
                break;
            }
            let text = match msg {
                Ok(Message::Text(t)) => t,
                Ok(Message::Ping(p)) => {
                    let _ = tx.lock().await.send(Message::Pong(p)).await;
                    continue;
                }
                Ok(Message::Close(_)) => break,
                Ok(_) => continue,
                Err(_) => break,
            };
            let req: Value = match serde_json::from_str(&text) {
                Ok(v) => v,
                Err(_) => continue,
            };
            let id = req["id"].as_u64().unwrap_or(0);
            let txx = Arc::clone(&tx);
            tokio::spawn(async move {
                let (stx, mut srx) = mpsc::channel::<String>(32);
            tokio::spawn({
                let tx3 = Arc::clone(&txx);
                async move {
                    while let Some(data) = srx.recv().await {
                        if tx3.lock().await.send(Message::Text(
                            json!({"t": "exec_out", "id": id, "data": data})
                                .to_string())).await.is_err() {
                            break;
                        }
                    }
                }
            });
            let resp = match req["t"].as_str().unwrap_or("") {
                    "exec" => {
                        exec_visible(
                            req["cmd"].as_str().unwrap_or(""),
                            req["window"].as_str(),
                            req["timeout_s"].as_u64().unwrap_or(60).min(300),
                            &stx,
                        )
                        .await
                    }
                    "type" => {
                        type_in_pane(req["text"].as_str().unwrap_or(""),
                                     req["window"].as_str()).await
                    }
                    "peek" => peek_pane(req["window"].as_str()).await,
                    "ctrl" => {
                        let key = req["key"].as_str().unwrap_or("c");
                        exec_visible(&format!("C-{key}"), req["window"].as_str(),
                                     10, &stx).await
                    }
                    "raw" => {
                        raw_exec(req["cmd"].as_str().unwrap_or(""),
                                 req["timeout_s"].as_u64().unwrap_or(30).min(300)).await
                    }
                    "ping" => json!({"pong": true}),
                    _ => json!({"error": "unknown type"}),
                };
                let mut r = resp;
                r["t"] = json!("exec_done");
                r["id"] = json!(id);
                let _ = txx
                    .lock()
                    .await
                    .send(Message::Text(r.to_string()))
                    .await;
            });
        }
        tracing::info!("exec channel dropped — re-dial");
        tokio::time::sleep(Duration::from_secs(2)).await;
    }
}
