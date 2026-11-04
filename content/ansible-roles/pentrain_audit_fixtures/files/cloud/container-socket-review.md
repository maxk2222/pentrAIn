# Build monitor container — mount and permission review

## Deployment record

- The metrics sidecar receives access to the container runtime socket.
- The sidecar runs with a broad host filesystem mount.
- The service only needs to read application health metrics.
- No ownership or expiry is recorded for the socket exception.

## Impact assessment task

Review what authority the mounted control socket represents, whether the
sidecar needs it, and how the host mount changes the boundary. Propose a
least-privilege metrics design and a safe configuration test. Do not contact
the runtime API or start a container.
