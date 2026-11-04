# AI platform assessment — incident evidence

## Evidence A: retrieved content

A support assistant returned a record from a different business unit. The
retrieval worker log shows the record was passed to a summarization stage
before response filtering.

## Evidence B: tool governance

A tool's permission changed in production without a recorded owner approval.
The tool service did not re-check the requesting user's authorization.

## Evidence C: model artifact

A shared validation worker loaded an artifact with no trusted publisher or
recorded digest. The worker identity could read unrelated configuration.

## Required report

Prioritize the findings, separate observed evidence from assumptions, and
recommend containment, permanent controls and safe verification.
