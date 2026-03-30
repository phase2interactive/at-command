FROM python:3.12-slim

# Install shells and utilities
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        bash \
        zsh \
        fish \
        jq \
    && rm -rf /var/lib/apt/lists/*

# Install at-cmd
COPY . /app
WORKDIR /app
RUN pip install --no-cache-dir .

# Copy test scripts and mock binary
COPY tests/shells/mock-at-cmd /usr/local/bin/mock-at-cmd
RUN chmod +x /usr/local/bin/mock-at-cmd

COPY tests/shells/*.sh /tests/
RUN chmod +x /tests/*.sh

ENTRYPOINT ["/tests/run_all.sh"]
