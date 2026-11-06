# guest agent: static musl binary provisioned to kali/targets via QGA.
# musl-gcc keeps the artifact glibc-free so any lab guest (debian/alpine)
# runs it without a runtime dependency.
FROM rust:slim AS agent
RUN apt-get update && apt-get install -y --no-install-recommends musl-tools \
    && rm -rf /var/lib/apt/lists/* \
    && rustup target add x86_64-unknown-linux-musl
WORKDIR /src
COPY agent/Cargo.toml agent/Cargo.lock ./
COPY agent/src ./src
RUN mkdir -p .cargo \
    && printf '[target.x86_64-unknown-linux-musl]\nlinker = "musl-gcc"\n' \
       > .cargo/config.toml \
    && cargo build --release --target x86_64-unknown-linux-musl

FROM python:3.11-slim

WORKDIR /app
COPY backend/pyproject.toml ./
COPY backend/app ./app
RUN pip install --no-cache-dir .
COPY --from=agent \
    /src/target/x86_64-unknown-linux-musl/release/pentrain-agent \
    /opt/pentrain-agent

ENV PENTRAIN_CONTENT_DIR=/content/packs \
    PENTRAIN_DATABASE_URL=sqlite+aiosqlite:////data/pentrain.db

VOLUME /data
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
