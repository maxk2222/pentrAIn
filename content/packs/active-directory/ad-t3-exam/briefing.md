# Exam: Domain Takeover

T3 assessment — the capstone. The full corp.pentrain.local environment:
two domain controllers, two workstations, one misconfigured helpdesk
account. Go from zero to krbtgt.

## Objectives

1. Spray the onboarding user — seasonal passwords never die.
2. Map and walk the attack path through the workstations.
3. DCSync the domain and take the second DC too.

## Rules of engagement

- Four flags: spray, workstation, second-DC, DCSync.
- Domain admin is a milestone; `krbtgt` is the objective.

## Environment

- **Kali**: your attack workstation
- **dc01**/**dc02**: the domain controllers
- **ws01**/**ws02**: domain workstations
