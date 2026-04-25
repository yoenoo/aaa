FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl tree ripgrep patch cron ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir pytest

COPY openclaw-bin/gh /usr/local/bin/gh
COPY openclaw-bin/crontab /usr/local/bin/crontab
COPY openclaw-bin/quarto /usr/local/bin/quarto
RUN chmod +x /usr/local/bin/gh /usr/local/bin/crontab /usr/local/bin/quarto

WORKDIR /workspace
ENV PYTHONPATH="/workspace:${PYTHONPATH}"

RUN useradd -m -s /bin/bash user && \
    chown -R user:user /workspace

RUN mkdir -p /root/.openclaw /home/user/.openclaw && \
    ln -s /workspace /root/.openclaw/workspace && \
    ln -s /workspace/.openclaw/cron /root/.openclaw/cron && \
    ln -s /workspace /home/user/.openclaw/workspace && \
    ln -s /workspace/.openclaw/cron /home/user/.openclaw/cron && \
    chown -h user:user /home/user/.openclaw/workspace /home/user/.openclaw/cron

RUN git config --system --add safe.directory '*'

CMD ["tail", "-f", "/dev/null"]
