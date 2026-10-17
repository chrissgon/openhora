# The image every eval run executes in (evals/executor.py builds and names it).
# Everything it installs is pinned: the base images by digest, the package index by a dated snapshot,
# the two runners by a committed lock file (runners/package-lock.json), gh by version and checksum.
# The PDF tools a run reaches for (pdftotext and pdftoppm from poppler-utils, python3-pypdf) come from the same snapshot.
# Changing this folder changes what a run measures: it is an execution-side change of the measurement
# (docs/architecture/reliability-model-2026-10-02.md, section 8), committed with a raised
# measurement_version in evals/eval-gate.json.
FROM ghcr.io/astral-sh/uv:0.12.19@sha256:04d046b13e60d6bcec73cbc5e1cad25d680dea90c8573340950a0ac2d1aef424 AS uv

FROM node:24.10.0-bookworm-slim@sha256:b8d2197aff9129d16c801a3e3e1b2a873c4946480f5a310f38056df2268c38d9

# Build arguments, not environment: a run does not inherit them.
ARG DEBIAN_FRONTEND=noninteractive
ARG DEBIAN_SNAPSHOT=20261001T000000Z
ARG TARGETARCH

# The package index of one day: the same build tomorrow installs the same versions. apt checks the
# archive's signature, so plain http is enough (the slim base has no certificates yet).
RUN rm -f /etc/apt/sources.list.d/debian.sources \
    && printf '%s\n' \
      "deb [check-valid-until=no] http://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT} bookworm main" \
      "deb [check-valid-until=no] http://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT} bookworm-updates main" \
      "deb [check-valid-until=no] http://snapshot.debian.org/archive/debian-security/${DEBIAN_SNAPSHOT} bookworm-security main" \
      > /etc/apt/sources.list \
    && printf 'Acquire::Retries "5";\n' > /etc/apt/apt.conf.d/80-retries \
    && apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl git python3 python3-venv chromium fonts-liberation jq less procps ripgrep file patch \
      poppler-utils python3-pypdf \
    && rm -rf /var/lib/apt/lists/*

# The code host's command-line tool, as a developer's machine has it, signed out: a model that
# reaches for it reads "not logged in", and a skill's script takes its gh branch.
ARG GH_VERSION=2.102.0
ARG GH_SHA256_ARM64=7862c86c72f43df3a2d93ddde6f473285b4e2af61b494849846827e513ef6484
ARG GH_SHA256_AMD64=bb766f710eef8ede859c18578c72c327597cd4c8a85b06001b1f3843c6019386
RUN case "${TARGETARCH}" in \
      arm64) sum="${GH_SHA256_ARM64}" ;; \
      amd64) sum="${GH_SHA256_AMD64}" ;; \
      *) echo "no pinned gh for the architecture '${TARGETARCH}'" >&2; exit 1 ;; \
    esac \
    && curl -fsSL -o /tmp/gh.tar.gz \
      "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_${TARGETARCH}.tar.gz" \
    && echo "${sum}  /tmp/gh.tar.gz" | sha256sum -c - \
    && tar -xzf /tmp/gh.tar.gz -C /tmp \
    && install -m 0755 "/tmp/gh_${GH_VERSION}_linux_${TARGETARCH}/bin/gh" /usr/local/bin/gh \
    && rm -rf /tmp/gh.tar.gz "/tmp/gh_${GH_VERSION}_linux_${TARGETARCH}"

# The two runners, from the lock file: exact versions, and exact versions of what they depend on.
# The floor runner tells its model to keep scratch files in /tmp/opencode, and its install step leaves
# that folder owned by root: it is made again, writable by whoever the run is.
COPY runners/package.json runners/package-lock.json /opt/runners/
RUN cd /opt/runners && npm ci --no-fund --no-audit \
    && npm cache clean --force \
    && ln -s /opt/runners/node_modules/.bin/claude /usr/local/bin/claude \
    && ln -s /opt/runners/node_modules/.bin/opencode /usr/local/bin/opencode \
    && rm -rf /tmp/opencode /root/.npm \
    && install -d -m 1777 /tmp/opencode
COPY --from=uv /uv /uvx /usr/local/bin/

# One clock, one locale and one user name for every run, whatever the caller's machine has; and no
# bytecode files, which a grader would otherwise be shown as files the run produced.
ENV TZ=UTC LANG=C.UTF-8 USER=eval PYTHONDONTWRITEBYTECODE=1

# A browser a skill's script can find, and no sandbox of its own: the container is the boundary.
ENV CHROME_BIN=/usr/bin/chromium PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium

# The adapters allow a model every tool and start only where this is set: here.
ENV WB_EVAL_CONTAINER=1

# The one git identity of a run (the executor forwards none).
RUN useradd --create-home --shell /bin/bash eval \
    && git config --system user.name "Eval" && git config --system user.email "eval@example.invalid" \
    && git config --system init.defaultBranch main && git config --system --add safe.directory '*'
# On Linux a run keeps the caller's numeric user, so the home must be usable by any of them.
RUN chmod 1777 /home/eval
USER eval
WORKDIR /eval
