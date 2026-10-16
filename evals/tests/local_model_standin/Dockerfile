# A stand-in for the llama.cpp model server, used only by the opt-in docker tests of a local model
# (WB_LOCAL_MODEL_DOCKER_TESTS=1, evals/tests/test_local_model_docker.py). It is built locally, never pulled, from a base image that
# is already on the machine and has python3 (BASE: the key proxy's image of the eval harness by default), outside evals/container/ so
# that it is not part of the measurement fingerprint. It answers like the model server does on /health, /v1/models and
# /v1/chat/completions, and has the same HEALTHCHECK shape (the image's health status is how the executor sees a server ready).
ARG BASE
FROM ${BASE}
COPY server.py /standin/server.py
HEALTHCHECK --interval=2s --timeout=2s --retries=3 CMD ["python3", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2)"]
ENTRYPOINT ["python3", "/standin/server.py"]
