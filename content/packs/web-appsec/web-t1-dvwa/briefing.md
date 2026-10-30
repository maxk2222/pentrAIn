# Damn Vulnerable

A `dvwa01` host runs the Damn Vulnerable Web Application on port 80 in the
training range. Two flags: one file you can reach via file inclusion, one
state flag that verifies you actually got code execution.

## Objectives

1. Reach DVWA — `admin` / `password`, set security to `low`.
2. Flag 1: use **File Inclusion** to read `/flags/flag1.txt` off the container.
3. Flag 2: get a `.php` file into `hackable/uploads` — the check runs itself.

## Setup

- DVWA lives in a Docker container on `dvwa01`.
- The flag file is *outside* the document root — you must abuse the inclusion.
- The state flag is auto-verified: upload a shell, click "Verify" on the flag.

## Ground rules

- Stay on `dvwa01` — the docker host is off-limits except for the flag check.
- Low security level is the intended path; try medium/high afterwards as bonus.
