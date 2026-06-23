FROM odoo:18.0

USER root

# Install additional system dependencies needed by the custom module
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        build-essential \
        libldap2-dev \
        libsasl2-dev \
        node-less \
        postgresql-client; \
    rm -rf /var/lib/apt/lists/*; \
    \
# Install gosu for step-down from root
    curl -fsSLo /usr/local/bin/gosu "https://github.com/tianon/gosu/releases/download/1.17/gosu-amd64"; \
    chmod +x /usr/local/bin/gosu; \
    gosu --version; \
    gosu nobody true

# Install additional Python packages required by nn_fund_management
RUN pip install --no-cache-dir --break-system-packages \
    pandas \
    num2words \
    phonenumbers \
    vobject \
    polib \
    freezegun \
    pyotp \
    qrcode

# Create required directories (matches docker-compose volume mounts)
RUN mkdir -p /opt/odoo/data /var/log/odoo

# Copy custom entrypoint (extends official image with secrets + db creation + migrations)
COPY docker/entrypoint.sh /entrypoint.sh
COPY docker/wait-for-psql.py /wait-for-psql.py
RUN chmod +x /entrypoint.sh

# Copy custom Odoo configuration
COPY docker/odoo.conf /etc/odoo/odoo.conf

# Copy custom addon into the standard extra-addons path
COPY . /mnt/extra-addons/nn_fund_management

# Fix ownership for the odoo user (uid 1000 in official image)
RUN chown -R odoo:odoo \
    /mnt/extra-addons \
    /etc/odoo/odoo.conf \
    /opt/odoo/data \
    /var/log/odoo

ENTRYPOINT ["/entrypoint.sh"]
CMD ["odoo", "--config=/etc/odoo/odoo.conf"]

LABEL org.opencontainers.image.title="NN Fund Management - Odoo 18" \
      org.opencontainers.image.description="Production Odoo 18 module for enterprise fund management" \
      org.opencontainers.image.version="18.0.4.0.0" \
      org.opencontainers.image.vendor="NN Systems"
