FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl tree ripgrep patch \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir pytest

WORKDIR /workspace
ENV PYTHONPATH="/workspace:${PYTHONPATH}"

RUN useradd -m -s /bin/bash user && \
    chown -R user:user /workspace

# Let git operate on /workspace regardless of who owns it — the sandbox mixes
# root-run setup (inspect_ai writing seed files) with user-run tools, which
# would otherwise trip git's "dubious ownership" check.
RUN git config --system --add safe.directory '*'

CMD ["tail", "-f", "/dev/null"]
