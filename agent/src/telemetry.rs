//! Telemetry shipper — 1:1 port of telemetried.py's tailer/spool/poster.
//! Tails LOGDIR/*.log with persistent offsets, parses shell-hook lines,
//! batches to POST /api/telemetry, spools to disk when unreachable.

use serde_json::{json, Value};
use std::collections::HashMap;
use std::io::{BufRead, BufReader, Seek, SeekFrom};
use std::path::PathBuf;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use crate::conf::ConfWatcher;

const LOGDIR: &str = "/var/log/pentrain";
const SPOOL: &str = "/var/spool/pentrain/buffer.jsonl";
const OFFSETS: &str = "/var/spool/pentrain/buffer.offsets.json";
const BATCH_MAX: usize = 50;
const FLUSH_S: f64 = 3.0;
const HEARTBEAT_S: u64 = 60;
const SPOOL_CAP: usize = 5000;

fn now_s() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0)
}

struct Tailer {
    offsets_file: PathBuf,
    offsets: HashMap<String, u64>,
    logdir: PathBuf,
}

impl Tailer {
    fn new(logdir: PathBuf, offsets_file: PathBuf) -> Self {
        let offsets = std::fs::read_to_string(&offsets_file)
            .ok()
            .and_then(|t| serde_json::from_str(&t).ok())
            .unwrap_or_default();
        Tailer { offsets_file, offsets, logdir }
    }

    fn save(&self) {
        if let Ok(t) = serde_json::to_string(&self.offsets) {
            let _ = std::fs::write(&self.offsets_file, t);
        }
    }

    /// Read new non-empty lines from every *.log. New files start at 0;
    /// rotated/truncated files restart at 0 (same as the python version).
    fn read_new(&mut self) -> Vec<(String, String)> {
        let mut out = Vec::new();
        let mut paths: Vec<PathBuf> = match std::fs::read_dir(&self.logdir) {
            Ok(rd) => rd
                .filter_map(|e| e.ok())
                .map(|e| e.path())
                .filter(|p| p.extension().map(|x| x == "log").unwrap_or(false))
                .collect(),
            Err(_) => return out,
        };
        paths.sort();
        for path in paths {
            let key = path.to_string_lossy().into_owned();
            let size = std::fs::metadata(&path).map(|m| m.len()).unwrap_or(0);
            let off = match self.offsets.get(&key).copied() {
                Some(o) if o <= size => o,
                _ => 0,
            };
            let file = match std::fs::File::open(&path) {
                Ok(f) => f,
                Err(_) => continue,
            };
            let mut rdr = BufReader::new(file);
            if rdr.seek(SeekFrom::Start(off)).is_err() {
                continue;
            }
            let mut pos = off;
            loop {
                let mut line = String::new();
                match rdr.read_line(&mut line) {
                    Ok(0) => break,
                    Ok(n) => {
                        pos += n as u64;
                        let t = line.trim_end_matches('\n');
                        if !t.trim().is_empty() {
                            out.push((key.clone(), t.to_string()));
                        }
                    }
                    Err(_) => break,
                }
            }
            self.offsets.insert(key, pos);
        }
        out
    }
}

/// hook line formats:
///   command: <epoch>\t<user>\t<cwd>\t<command>
///   result:  R\t<exit_code>
pub fn parse_hook_line(line: &str) -> Option<Value> {
    if let Some(rest) = line.strip_prefix("R\t") {
        let code: i64 = rest.trim().parse().ok()?;
        return Some(json!({
            "kind": "command_result",
            "payload": {"exit_code": code}
        }));
    }
    let parts: Vec<&str> = line.split('\t').collect();
    if parts.len() < 4 {
        return None;
    }
    let ts: i64 = parts[0].parse::<f64>().map(|f| f as i64).unwrap_or(0);
    let cmd: String = parts[3..].join("\t").chars().take(4000).collect();
    Some(json!({
        "kind": "command",
        "payload": {"ts": ts, "user": parts[1], "cwd": parts[2], "command": cmd}
    }))
}

fn post(api: &str, token: &str, events: &[Value]) -> bool {
    let url = format!("{}/api/telemetry", api.trim_end_matches('/'));
    let body = json!({"token": token, "events": events});
    match ureq::post(&url)
        .timeout(Duration::from_secs(10))
        .set("Content-Type", "application/json")
        .send_json(body)
    {
        Ok(r) => (200..300).contains(&r.status()),
        Err(ureq::Error::Status(code, _)) => (200..300).contains(&code),
        Err(_) => false,
    }
}

pub async fn run(mut watcher: ConfWatcher) {
    let logdir = PathBuf::from(LOGDIR);
    let spool = PathBuf::from(SPOOL);
    let mut tailer = Tailer::new(logdir, PathBuf::from(OFFSETS));
    let mut pending: Vec<Value> = Vec::new();
    // reload spool from a previous run
    if let Ok(text) = std::fs::read_to_string(&spool) {
        for line in text.lines() {
            if let Ok(v) = serde_json::from_str::<Value>(line) {
                pending.push(v);
            }
        }
        let _ = std::fs::remove_file(&spool);
    }
    let mut last_flush = 0.0f64;
    let mut last_heartbeat = 0u64;

    loop {
        watcher.refresh();
        let conf = watcher.current.clone();
        if conf.telemetry_ready() {
            for (_path, line) in tailer.read_new() {
                if let Some(mut ev) = parse_hook_line(&line) {
                    ev["payload"]["host"] = json!(conf.host);
                    pending.push(ev);
                }
            }
            let now = now_s() as u64;
            if now.saturating_sub(last_heartbeat) >= HEARTBEAT_S {
                pending.push(json!({
                    "kind": "heartbeat",
                    "payload": {"host": conf.host, "ts": now}
                }));
                last_heartbeat = now;
            }
            tailer.save();
        }

        if !pending.is_empty()
            && (now_s() - last_flush >= FLUSH_S || pending.len() >= BATCH_MAX)
        {
            if conf.token.is_empty() || conf.api.is_empty() {
                // not configured yet — keep spooling in memory only
            } else {
                let batch: Vec<Value> = pending.drain(..BATCH_MAX.min(pending.len())).collect();
                let (api, token) = (conf.api.clone(), conf.token.clone());
                let batch2 = batch.clone();
                let ok = tokio::task::spawn_blocking(move || post(&api, &token, &batch2))
                    .await
                    .unwrap_or(false);
                if ok {
                    last_flush = now_s();
                } else {
                    pending = batch.into_iter().chain(pending).collect();
                    if pending.len() > SPOOL_CAP {
                        pending = pending.split_off(pending.len() - SPOOL_CAP);
                    }
                    if let Some(dir) = spool.parent() {
                        let _ = std::fs::create_dir_all(dir);
                    }
                    let text = pending
                        .iter()
                        .map(|e| e.to_string())
                        .collect::<Vec<_>>()
                        .join("\n")
                        + "\n";
                    let _ = std::fs::write(&spool, text);
                }
            }
        }
        tokio::time::sleep(Duration::from_secs(1)).await;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_command_line() {
        let v = parse_hook_line("1710000000\troot\t/root\tid -a").unwrap();
        assert_eq!(v["kind"], "command");
        assert_eq!(v["payload"]["user"], "root");
        assert_eq!(v["payload"]["command"], "id -a");
    }

    #[test]
    fn parses_result_line() {
        let v = parse_hook_line("R\t127").unwrap();
        assert_eq!(v["kind"], "command_result");
        assert_eq!(v["payload"]["exit_code"], 127);
    }

    #[test]
    fn rejects_garbage() {
        assert!(parse_hook_line("hello").is_none());
        assert!(parse_hook_line("R\tnope").is_none());
    }

    #[test]
    fn tailer_reads_new_and_tracks_offsets() {
        let dir = std::env::temp_dir().join(format!("ptn-tail-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let log = dir.join("a.log");
        std::fs::write(&log, "l1\nl2\n").unwrap();
        let mut t = Tailer::new(dir.clone(), dir.join("off.json"));
        let got = t.read_new();
        assert_eq!(got.len(), 2);
        assert!(t.read_new().is_empty());
        std::fs::write(&log, "l1\nl2\nl3\n").unwrap();
        let got = t.read_new();
        assert_eq!(got.len(), 1);
        std::fs::remove_dir_all(&dir).ok();
    }
}
