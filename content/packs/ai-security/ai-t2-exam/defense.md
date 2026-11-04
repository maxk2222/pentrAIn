# Defense notes — Exam: Model Operations

## Assessment themes

- Tool permissions and model artifact trust are separate boundaries.
- Authorization belongs in the service that performs the action.
- Artifact provenance should be immutable and independently verified.
- Validation workers should be disposable and narrowly privileged.

## Verification

Test denied tool actions and rejected untrusted artifacts with synthetic
fixtures. Confirm that an approved artifact has a recorded digest, publisher
and review trail, and that worker access is limited to the validation task.
