FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for PostgreSQL client and Oracle Instant Client
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    libaio1t64 \
    wget \
    unzip \
    && rm -rf /var/lib/apt/lists/* \
    && ln -s /usr/lib/x86_64-linux-gnu/libaio.so.1t64 /usr/lib/x86_64-linux-gnu/libaio.so.1

# Install Oracle Instant Client (required for thick mode / network encryption)
RUN wget -q https://download.oracle.com/otn_software/linux/instantclient/2350000/instantclient-basic-linux.x64-23.5.0.24.07.zip -O /tmp/instantclient.zip \
    && unzip -q /tmp/instantclient.zip -d /opt/oracle \
    && rm /tmp/instantclient.zip \
    && echo /opt/oracle/instantclient_23_5 > /etc/ld.so.conf.d/oracle-instantclient.conf \
    && ldconfig

ENV LD_LIBRARY_PATH=/opt/oracle/instantclient_23_5:${LD_LIBRARY_PATH}

# Copy project files
COPY pyproject.toml README.md ./
COPY src/ src/
COPY bin/ bin/

# Install the package with postgres and oracle support
RUN pip install --no-cache-dir -e ".[postgres,oracle]"

# Create directories for config and output
RUN mkdir -p /app/conf /app/output

# Copy example config
COPY conf/ conf/

# Add bin to PATH
ENV PATH="/app/bin:${PATH}"

# Default command
ENTRYPOINT ["eda-to-stf"]
CMD ["--config", "/app/conf/config.yaml"]
