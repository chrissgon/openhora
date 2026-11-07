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

# The CPU the code is compiled for, by architecture, chosen at build time with `dpkg --print-architecture`. The build does
# NOT use GGML_NATIVE: it makes gcc probe the machine it runs on (-mcpu=native), which inside a virtual machine can miss a
# feature the code then needs (the first build failed that way on Apple Silicon: fp16 intrinsics without +fp16), and it
# ties the image to the machine that built it. A fixed floor builds the same everywhere and runs on every CPU of its
# architecture that has the floor's features (the CPUs named below and everything newer).
#   arm64: Armv8.2-A with the dot-product and half-precision vector instructions (Apple M1 and later, Graviton 2 and
#          later, Ampere, Raspberry Pi 5). GGML_CPU_ARM_ARCH becomes -march=<value>.
#   amd64: the AVX2 / FMA / F16C / BMI2 set that x86-64-v3 CPUs have (Intel Haswell 2013 and later, AMD Zen). No AVX-512.
# The values are labels of the image (org.openhora.whisper-cpp.cpu-flags.<arch>), and the transcript's facts name the pair
# that matches the image's architecture. An image is one architecture: build it again on the other kind of machine. A
# CPU below the floor fails with an illegal-instruction error at the first run, never a silent wrong answer.
ARG CPU_FLAGS_ARM64="-DGGML_CPU_ARM_ARCH=armv8.2-a+dotprod+fp16"
ARG CPU_FLAGS_AMD64="-DGGML_SSE42=ON -DGGML_AVX=ON -DGGML_AVX2=ON -DGGML_FMA=ON -DGGML_F16C=ON -DGGML_BMI2=ON -DGGML_AVX512=OFF"

# debian:bookworm-20261005-slim
FROM debian@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587 AS build

ARG DEBIAN_FRONTEND=noninteractive
ARG DEBIAN_SNAPSHOT=20261006T000000Z
# whisper.cpp release v1.9.5 (published 2026-10-06). The tag is an annotated tag (object
# d2a764c648779feb36d44363f212a29b00aad1af); the commit below is what it points to. Read from the GitHub API.
ARG WHISPER_CPP_TAG=v1.9.5
ARG WHISPER_CPP_COMMIT=d1be6fde11ac6e0407606b4e42fe72d34add8037
ARG CPU_FLAGS_ARM64
ARG CPU_FLAGS_AMD64

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

# CPU only: no GPU backend, no network download of models (WHISPER_CURL off), no tests, no server. One static binary.
# GGML_NATIVE is off and the CPU floor comes from the CPU_FLAGS_* above. OpenMP is off so that the binary needs no extra
# library.
RUN case "$(dpkg --print-architecture)" in \
      arm64) cpu_flags="${CPU_FLAGS_ARM64}" ;; \
      amd64) cpu_flags="${CPU_FLAGS_AMD64}" ;; \
      *) echo "no CPU floor is pinned for the architecture $(dpkg --print-architecture)" >&2; exit 1 ;; \
    esac \
    && echo "CPU flags: ${cpu_flags}" \
    && cmake -S /src -B /src/build \
      -DCMAKE_BUILD_TYPE=Release \
      -DBUILD_SHARED_LIBS=OFF \
      -DGGML_NATIVE=OFF \
      ${cpu_flags} \
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
ARG CPU_FLAGS_ARM64
ARG CPU_FLAGS_AMD64

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
      org.openhora.whisper-cpp.cpu-flags.arm64="${CPU_FLAGS_ARM64}" \
      org.openhora.whisper-cpp.cpu-flags.amd64="${CPU_FLAGS_AMD64}" \
      org.openhora.definition="${DEFINITION_HASH}"

USER 10001:10001
WORKDIR /scratch
ENTRYPOINT ["/usr/local/bin/openhora-transcribe"]
