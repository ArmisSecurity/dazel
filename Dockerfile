# A minimal image for running bazel through dazel. Point DAZEL_DOCKERFILE at it, or use it as a base
# for a project-specific image. Bazelisk is installed as `bazel`, so the workspace's `.bazelversion`
# (or USE_BAZEL_VERSION) selects the bazel release.
FROM debian:bookworm-slim

ARG BAZELISK_VERSION=v1.30.0
ARG BAZELISK_SHA256_AMD64=a248ae2b2b62b5baebb748f6fba7203bff1a27e5d01b55399a8406744cb539e8
ARG BAZELISK_SHA256_ARM64=b2bcc040c213b44586b121bda6d983c35df121b917c3a7a66fb16f2fa0df1a4f
ARG TARGETARCH

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential ca-certificates curl git patch python3 unzip zip \
 && rm -rf /var/lib/apt/lists/*

RUN case "${TARGETARCH:-amd64}" in \
      amd64) sha256="${BAZELISK_SHA256_AMD64}" ;; \
      arm64) sha256="${BAZELISK_SHA256_ARM64}" ;; \
      *) echo "unsupported architecture: ${TARGETARCH}" >&2; exit 1 ;; \
    esac \
 && curl -fsSL -o /usr/local/bin/bazelisk \
      "https://github.com/bazelbuild/bazelisk/releases/download/${BAZELISK_VERSION}/bazelisk-linux-${TARGETARCH:-amd64}" \
 && echo "${sha256}  /usr/local/bin/bazelisk" | sha256sum -c - \
 && chmod +x /usr/local/bin/bazelisk \
 && ln -s /usr/local/bin/bazelisk /usr/bin/bazel
