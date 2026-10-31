# Exam: Evidence Pipeline

**Tier-2 capstone — Scripting & Automation.** An incident responder dumped
a packet capture onto `evidence01`'s evidence share. Somewhere in it, an
operator typed credentials over a cleartext protocol. Your script must do
the full pipeline a real IR automation would: fetch the capture, extract
the credentials, use them, and leave proof of analysis.

**Deliverables**

1. Pull the capture from the evidence share (HTTP, self-indexing).
2. Extract the credential pair from the cleartext protocol exchange.
3. Use them to log into the box and create
   `/home/ops-backup/proof.txt` containing `analysis-complete`.
4. Retrieve `/home/ops-backup/loot.txt` and submit its contents.

Everything past step 1 should be scripted — the grader checks the proof
file, not your keystrokes.

**This is an exam.** Solve every tier-2 scripting quest first.

Difficulty: medium · Track: Scripting & Automation
