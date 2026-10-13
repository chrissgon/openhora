# The image the transcriber runs in (providers/transcriber/whispercpp.py builds it with `build --confirmed`, one
# command the person starts; nothing in the repository builds or pulls it by itself).
#
# What is pinned, and how:
#   - the base image, by the digest of its multi-architecture index, with the dated tag it came from kept in the
#     comment (the tag is not the pin: the digest is). Both lines were read from the registry's metadata on 2026-10-13,
#     nothing was pulled to read them;
#   - the package index, by a dated snapshot of the Debian archive (the same build tomorrow installs the same
#     versions; apt checks the archive's signature, so plain http is enough before the certificates are installed);
#   - whisper.cpp, by release tag AND commit: the build stops when the tag now points at another commit.
# The first build records the image's id in the state folder (image.json) and in each transcript's facts. A moved
# base tag cannot change the image by itself, because the digest names the base; a changed snapshot or a changed
# commit is a change of this file, and so a new definition hash and a new image.
#
# What the image holds: ffmpeg (with ffprobe) and whisper-cli, built for the CPU, and the entry script. No model
# (the person's own pinned, hash-checked file is mounted read-only at run time), no compiler, no git, no shell
# history, and a non-root user. At run time the provider starts it with no network, a read-only root file system and
# no environment (see whispercpp.py, "The container").

# debian:bookworm-20261005-slim
FROM debian@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587 AS build

ARG DEBIAN_FRONTEND=noninteractive
ARG DEBIAN_SNAPSHOT=20261006T000000Z
# whisper.cpp release v1.9.5 (published 2026-10-06). The tag is an annotated tag (object
# d2a764c648779feb36d44363f212a29b00aad1af); the commit below is what it points to. Read from the GitHub API.
ARG WHISPER_CPP_TAG=v1.9.5
ARG WHISPER_CPP_COMMIT=d1be6fde11ac6e0407606b4e42fe72d34add8037

RUN rm -f /etc/apt/sources.list.d/debian.sources \
    && printf '%s\n' \
      "deb [check-valid-until=no] http://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT} bookworm main" \
      "deb [check-valid-until=no] http://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT} bookworm-updates main" \
      "deb [check-valid-until=no] http://snapshot.debian.org/archive/debian-security/${DEBIAN_SNAPSHOT} bookworm-security main" \
      > /etc/apt/sources.list \
    && printf 'Acquire::Retries "5";\n' > /etc/apt/apt.conf.d/80-retries \
    && apt-get update && apt-get install -y --no-install-recommends \
      build-essential cmake git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# The source, at the pinned tag, then checked against the pinned commit. A tag that was moved fails the build here.
RUN git clone --quiet --depth 1 --branch "${WHISPER_CPP_TAG}" https://github.com/ggml-org/whisper.cpp /src \
    && test "$(git -C /src rev-parse HEAD)" = "${WHISPER_CPP_COMMIT}"

# CPU only: no GPU backend, no network download of models (WHISPER_CURL off), no tests, no server. One static
# binary. GGML_NATIVE builds for the CPU of the machine that builds it: the image is built where it runs and is
# never pushed, so it must be built again on another machine. OpenMP is off so that the binary needs no extra library.
RUN cmake -S /src -B /src/build \
      -DCMAKE_BUILD_TYPE=Release \
      -DBUILD_SHARED_LIBS=OFF \
      -DGGML_NATIVE=ON \
      -DGGML_OPENMP=OFF \
      -DWHISPER_CURL=OFF \
      -DWHISPER_SDL2=OFF \
      -DWHISPER_BUILD_TESTS=OFF \
      -DWHISPER_BUILD_SERVER=OFF \
      -DWHISPER_BUILD_EXAMPLES=ON \
    && cmake --build /src/build --config Release --target whisper-cli -j "$(nproc)" \
    && install -m 0755 "$(find /src/build -type f -name whisper-cli | head -n 1)" /whisper-cli

FROM debian@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587

ARG DEBIAN_FRONTEND=noninteractive
ARG DEBIAN_SNAPSHOT=20261006T000000Z
ARG WHISPER_CPP_TAG=v1.9.5
ARG WHISPER_CPP_COMMIT=d1be6fde11ac6e0407606b4e42fe72d34add8037
# Set by `build --confirmed` to the hash of this folder's definition (Dockerfile, transcribe.sh, .dockerignore); the
# provider compares the label with the hash it computes now, so an image older than the files is refused.
ARG DEFINITION_HASH=unset

RUN rm -f /etc/apt/sources.list.d/debian.sources \
    && printf '%s\n' \
      "deb [check-valid-until=no] http://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT} bookworm main" \
      "deb [check-valid-until=no] http://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT} bookworm-updates main" \
      "deb [check-valid-until=no] http://snapshot.debian.org/archive/debian-security/${DEBIAN_SNAPSHOT} bookworm-security main" \
      > /etc/apt/sources.list \
    && printf 'Acquire::Retries "5";\n' > /etc/apt/apt.conf.d/80-retries \
    && apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt /var/log/apt /var/log/dpkg.log

COPY --from=build /whisper-cli /usr/local/bin/whisper-cli
COPY transcribe.sh /usr/local/bin/openhora-transcribe
# The build fails here when the binary or ffmpeg is missing a shared library, instead of at the first run.
RUN chmod 0755 /usr/local/bin/openhora-transcribe \
    && ! ldd /usr/local/bin/whisper-cli | grep -q "not found" \
    && whisper-cli --version >/dev/null 2>&1 \
    && ffmpeg -hide_banner -version >/dev/null && ffprobe -hide_banner -version >/dev/null \
    && useradd --system --uid 10001 --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin transcriber

LABEL org.openhora.component="transcriber" \
      org.openhora.whisper-cpp.tag="${WHISPER_CPP_TAG}" \
      org.openhora.whisper-cpp.commit="${WHISPER_CPP_COMMIT}" \
      org.openhora.debian-snapshot="${DEBIAN_SNAPSHOT}" \
      org.openhora.definition="${DEFINITION_HASH}"

USER 10001:10001
WORKDIR /scratch
ENTRYPOINT ["/usr/local/bin/openhora-transcribe"]
