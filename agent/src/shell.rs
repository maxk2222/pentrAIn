//! Browser-terminal channel — kali only (SHELL=1).
//! Polls which channels the UI wants, dials a WS per channel, bridges to a
//! PTY running `tmux new -A -s pentrain-web-<chan>`. 1:1 port of the python
//! _shell_loop/_chan_task: binary frames = pty bytes; text = JSON control
//! ({"t":"resize"} in; {"t":"exit","code"} out). Re-dials are free —
//! `tmux -A` reattaches to the same server-side session.

use serde_json::{json, Value};
use std::collections::HashMap;
use std::os::unix::io::{AsRawFd, FromRawFd, OwnedFd};
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::{mpsc, watch, Mutex};

use crate::conf::{Conf, ConfWatcher};

const SHELL_POLL_S: u64 = 2;

fn get_wants(api: &str, sid: &str, token: &str) -> HashMap<String, Value> {
    let url = format!("{}/api/terminal/wants/{sid}?token={token}", api.trim_end_matches('/'));
    match ureq::get(&url).timeout(Duration::from_secs(10)).call() {
        Ok(r) => r
            .into_json::<Value>()
            .ok()
            .and_then(|v| v["chans"].as_object().cloned())
            .map(|m| m.into_iter().collect())
            .unwrap_or_default(),
        Err(_) => HashMap::new(),
    }
}

struct Pty {
    master: OwnedFd,
    child: std::process::Child,
}

fn spawn_pty(chan: &str, cols: u16, rows: u16) -> std::io::Result<Pty> {
    use std::io;
    let mut master: libc::c_int = -1;
    let mut slave: libc::c_int = -1;
    let mut ws: libc::winsize = unsafe { std::mem::zeroed() };
    ws.ws_row = rows;
    ws.ws_col = cols;
    if unsafe {
        libc::openpty(
            &mut master,
            &mut slave,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            &mut ws,
        )
    } != 0
    {
        return Err(io::Error::last_os_error());
    }
    use std::os::unix::process::CommandExt;
    let has_tmux = std::path::Path::new("/usr/bin/tmux").exists();
    let mut cmd = std::process::Command::new(if has_tmux { "tmux" } else { "bash" });
    if has_tmux {
        cmd.args(["new-session", "-A", "-s", &format!("pentrain-web-{chan}")]);
    } else {
        cmd.arg("-l");
    }
    cmd.env("TERM", "xterm-256color")
        .env("HOME", "/root")
        .env("SHELL", "/bin/bash");
    unsafe {
        cmd.pre_exec(move || {
            libc::setsid();
            libc::ioctl(slave, libc::TIOCSCTTY, 0);
            libc::dup2(slave, 0);
            libc::dup2(slave, 1);
            libc::dup2(slave, 2);
            if slave > 2 {
                libc::close(slave);
            }
            Ok(())
        });
    }
    let child = cmd.spawn()?;
    unsafe { libc::close(slave) };
    Ok(Pty {
        master: unsafe { OwnedFd::from_raw_fd(master) },
        child,
    })
}

async fn chan_task(conf: Conf, chan: String, cols: u16, rows: u16,
                   mut stop: watch::Receiver<bool>) {
    use futures::{SinkExt, StreamExt};
    use tokio_tungstenite::tungstenite::Message;

    let url = format!(
        "{}/api/terminal/kali/{}/{}?token={}",
        conf.ws_base(), conf.session, chan, conf.token
    );
    let mut pty = match spawn_pty(&chan, cols, rows) {
        Ok(p) => p,
        Err(e) => {
            tracing::warn!(chan = %chan, error = %e, "pty spawn failed");
            return;
        }
    };
    let ws = match tokio_tungstenite::connect_async(&url).await {
        Ok((w, _)) => w,
        Err(e) => {
            tracing::warn!(chan = %chan, error = %e, "terminal ws dial failed");
            return;
        }
    };
    let (ws_tx, mut ws_rx) = ws.split();
    let ws_tx = Arc::new(Mutex::new(ws_tx));

    // PTY → WS pump (blocking fd → reader task → bounded queue)
    let (q_tx, mut q_rx) = mpsc::channel::<Vec<u8>>(256);
    let master_fd = pty.master.as_raw_fd();
    let reader = tokio::task::spawn_blocking(move || {
        use std::io::Read;
        let mut f = unsafe { std::fs::File::from_raw_fd(master_fd) };
        let mut buf = [0u8; 65536];
        loop {
            match f.read(&mut buf) {
                Ok(0) | Err(_) => break,
                Ok(n) => {
                    if q_tx.blocking_send(buf[..n].to_vec()).is_err() {
                        break;
                    }
                }
            }
        }
    });

    let mut proc_dead = false;
    loop {
        tokio::select! {
            chunk = q_rx.recv() => match chunk {
                Some(b) => {
                    if ws_tx.lock().await.send(Message::Binary(b)).await.is_err() {
                        break;
                    }
                }
                None => break, // pty eof
            },
            msg = ws_rx.next() => match msg {
                Some(Ok(Message::Binary(b))) => {
                    use std::io::Write;
                    let mut f = unsafe { std::fs::File::from_raw_fd(master_fd) };
                    let _ = f.write_all(&b);
                    std::mem::forget(f); // don't close the shared fd
                }
                Some(Ok(Message::Text(t))) => {
                    if let Ok(ctl) = serde_json::from_str::<Value>(&t) {
                        if ctl["t"] == "resize" {
                            let mut wsz: libc::winsize = unsafe { std::mem::zeroed() };
                            wsz.ws_row = ctl["rows"].as_u64().unwrap_or(32) as u16;
                            wsz.ws_col = ctl["cols"].as_u64().unwrap_or(120) as u16;
                            unsafe { libc::ioctl(master_fd, libc::TIOCSWINSZ, &wsz) };
                        }
                    }
                }
                Some(Ok(Message::Close(_))) | None => break,
                Some(Err(_)) => break,
                _ => {}
            },
            _ = stop.changed() => break,
            _ = async {
                loop {
                    tokio::time::sleep(Duration::from_millis(500)).await;
                    if let Ok(Some(_)) = pty.child.try_wait() {
                        return;
                    }
                }
            } => { proc_dead = true; break; },
        }
    }
    if proc_dead {
        let code = pty.child.wait().ok().and_then(|s| s.code()).unwrap_or(-1);
        let _ = ws_tx
            .lock()
            .await
            .send(Message::Text(json!({"t": "exit", "code": code}).to_string()))
            .await;
    }
    let _ = ws_tx.lock().await.send(Message::Close(None)).await;
    let _ = pty.child.kill();
    reader.abort();
    // master fd closes with pty.master drop
}

pub async fn run(mut watcher: ConfWatcher) {
    let mut running: HashMap<String, watch::Sender<bool>> = HashMap::new();
    loop {
        watcher.refresh();
        let conf = watcher.current.clone();
        if !(conf.shell && !conf.session.is_empty() && !conf.token.is_empty()) {
            tokio::time::sleep(Duration::from_secs(SHELL_POLL_S)).await;
            continue;
        }
        let (api, sid, token) = (conf.api.clone(), conf.session.clone(), conf.token.clone());
        let wants = tokio::task::spawn_blocking(move || get_wants(&api, &sid, &token))
            .await
            .unwrap_or_default();
        // drop channels no longer wanted
        for chan in running.keys().cloned().collect::<Vec<_>>() {
            if !wants.contains_key(&chan) {
                if let Some(tx) = running.remove(&chan) {
                    let _ = tx.send(true);
                }
            }
        }
        // spawn newly wanted channels
        for (chan, meta) in wants {
            if running.contains_key(&chan) {
                continue;
            }
            let (stop_tx, stop_rx) = watch::channel(false);
            let c = conf.clone();
            let ch = chan.clone();
            let cols = meta["cols"].as_u64().unwrap_or(120) as u16;
            let rows = meta["rows"].as_u64().unwrap_or(32) as u16;
            tokio::spawn(async move { chan_task(c, ch, cols, rows, stop_rx).await });
            running.insert(chan, stop_tx);
        }
        tokio::time::sleep(Duration::from_secs(SHELL_POLL_S)).await;
    }
}
