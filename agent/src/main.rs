//! pentrain-agent — single static binary for ludus guest VMs.
//! Replaces telemetried.py: telemetry shipper (always), browser-terminal
//! channel (SHELL=1, kali), coach exec channel (EXEC=1, kali).
//! Conf lives at /etc/pentrain/telemetried.conf — re-read on change.

mod conf;
mod exec;
mod shell;
mod telemetry;
mod tmux;

use conf::ConfWatcher;

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "info".into()),
        )
        .init();

    // each subsystem gets its own watcher instance — they re-read the file
    // independently so a rotating token drops only the stale connection
    let w_tele = ConfWatcher::new(None);
    let w_shell = ConfWatcher::new(None);
    let w_exec = ConfWatcher::new(None);

    tokio::spawn(telemetry::run(w_tele));
    tokio::spawn(shell::run(w_shell));
    tokio::spawn(exec::run(w_exec));

    // park forever — SIGTERM lets systemd restart cleanly
    tokio::signal::ctrl_c().await.ok();
}
