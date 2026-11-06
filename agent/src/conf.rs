//! /etc/pentrain/telemetried.conf — KEY=VAL, '#' comments, re-read on mtime
//! change (the backend rewrites it on session reset → tokens rotate live).

use std::collections::HashMap;
use std::path::PathBuf;
use std::time::SystemTime;

pub const CONF_PATH: &str = "/etc/pentrain/telemetried.conf";

#[derive(Debug, Clone, Default)]
pub struct Conf {
    pub token: String,
    pub session: String,
    pub api: String,
    pub host: String,
    pub shell: bool,
    pub exec: bool,
}

impl Conf {
    pub fn parse(text: &str, hostname: &str) -> Self {
        let mut m: HashMap<String, String> = HashMap::new();
        for line in text.lines() {
            let line = line.trim();
            if line.is_empty() || line.starts_with('#') {
                continue;
            }
            if let Some((k, v)) = line.split_once('=') {
                m.insert(k.trim().to_string(), v.trim().to_string());
            }
        }
        Conf {
            token: m.get("TOKEN").cloned().unwrap_or_default(),
            session: m.get("SESSION").cloned().unwrap_or_default(),
            api: m.get("API").cloned().unwrap_or_default(),
            host: m.get("HOST").cloned().unwrap_or_else(|| hostname.to_string()),
            shell: m.get("SHELL").map(|v| v == "1").unwrap_or(false),
            exec: m.get("EXEC").map(|v| v == "1").unwrap_or(false),
        }
    }

    pub fn telemetry_ready(&self) -> bool {
        !self.token.is_empty()
    }

    /// ws:// or wss:// base URL derived from the API http(s) URL.
    pub fn ws_base(&self) -> String {
        let base = self.api.trim_end_matches('/');
        if let Some(rest) = base.strip_prefix("https://") {
            format!("wss://{rest}")
        } else if let Some(rest) = base.strip_prefix("http://") {
            format!("ws://{rest}")
        } else {
            format!("ws://{base}")
        }
    }
}

/// Watches the conf file for mtime changes and yields fresh Conf values.
pub struct ConfWatcher {
    path: PathBuf,
    last_mtime: Option<SystemTime>,
    pub current: Conf,
    hostname: String,
}

impl ConfWatcher {
    pub fn new(path: Option<PathBuf>) -> Self {
        let path = path.unwrap_or_else(|| PathBuf::from(CONF_PATH));
        let hostname = hostname::get()
            .ok()
            .and_then(|h| h.into_string().ok())
            .unwrap_or_else(|| "agent".into());
        let mut w = ConfWatcher {
            path,
            last_mtime: None,
            current: Conf::default(),
            hostname,
        };
        w.refresh();
        w
    }

    /// Re-read the file if its mtime changed. Returns true when Conf changed.
    pub fn refresh(&mut self) -> bool {
        let mtime = std::fs::metadata(&self.path)
            .and_then(|m| m.modified())
            .ok();
        if mtime == self.last_mtime {
            return false;
        }
        self.last_mtime = mtime;
        let text = std::fs::read_to_string(&self.path).unwrap_or_default();
        let next = Conf::parse(&text, &self.hostname);
        let changed = next.token != self.current.token
            || next.session != self.current.session
            || next.api != self.current.api
            || next.shell != self.current.shell
            || next.exec != self.current.exec;
        self.current = next;
        changed
    }
}

// hostname crate not in deps — tiny wrapper via /etc/hostname / uname
mod hostname {
    use std::ffi::OsString;

    pub fn get() -> std::io::Result<OsString> {
        let mut uts: libc::utsname = unsafe { std::mem::zeroed() };
        if unsafe { libc::uname(&mut uts) } != 0 {
            return Err(std::io::Error::last_os_error());
        }
        let s = unsafe { std::ffi::CStr::from_ptr(uts.nodename.as_ptr()) };
        Ok(OsString::from(s.to_string_lossy().into_owned()))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_conf() {
        let c = Conf::parse(
            "# c\nTOKEN=abc\nSESSION=7\nHOST=kali\nAPI=https://x:8000\nSHELL=1\nEXEC=1\n",
            "h",
        );
        assert_eq!(c.token, "abc");
        assert_eq!(c.session, "7");
        assert_eq!(c.host, "kali");
        assert!(c.shell && c.exec);
        assert_eq!(c.ws_base(), "wss://x:8000");
    }

    #[test]
    fn defaults_and_ws() {
        let c = Conf::parse("TOKEN=t\nAPI=http://app:8000/\n", "box1");
        assert_eq!(c.host, "box1");
        assert!(!c.shell && !c.exec);
        assert_eq!(c.ws_base(), "ws://app:8000");
        assert!(c.telemetry_ready());
    }

    #[test]
    fn empty_not_ready() {
        let c = Conf::parse("", "h");
        assert!(!c.telemetry_ready());
    }
}
