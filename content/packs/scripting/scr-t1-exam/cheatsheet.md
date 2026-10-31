# Cheatsheet — exam report building blocks

## Fetch the three sources

```bash
ssh user@$T 'cat /var/log/auth.log' > auth.log
curl -s ftp://$T/assets.csv -o assets.csv
curl -s http://$T:8080/status.json -o status.json
```

## Rank a column by frequency

```bash
awk '{print $11}' auth.log | sort | uniq -c | sort -rn | head -1
```

## CSV columns to a comma list

```bash
tail -n +2 assets.csv | cut -d, -f1 | paste -sd,
```

## Tiny-JSON parsing without jq

```bash
tr -d '{}" ' < status.json | tr ',' '\n' | grep '^services' | cut -d: -f2
```

(jq is installed on Kali too — `jq -r '.services|join(",")'`)

## The exact output contract

```bash
printf 'SERVICES=%s\nATTACKER=%s\nASSETS=%s\n' "$svc" "$ip" "$hosts" \
  > /root/report.txt
```
