FROM registry.access.redhat.com/ubi9/ubi-minimal:latest

ARG PYTHON_VERSION
ARG BUILD_DATE
ARG IMAGE_VERSION
ARG IMAGE_TITLE
ARG IMAGE_DESCRIPTION

USER root

RUN useradd -m -s /bin/bash -U denodo \
    && microdnf install -y python${PYTHON_VERSION} python${PYTHON_VERSION}-pip \
    && microdnf clean all \
    && ln -s "/usr/bin/python${PYTHON_VERSION}" /usr/bin/python3 \
    && ln -s "/usr/bin/python${PYTHON_VERSION}" /usr/bin/python \
    && "pip${PYTHON_VERSION}" install --upgrade pip

WORKDIR /opt/ai-sdk

RUN chown denodo:denodo /opt/ai-sdk

USER denodo

COPY  --chown=denodo:denodo . .
COPY --chown=denodo:denodo --chmod=544 ./entrypoint.sh ./entrypoint.sh
RUN pip install --no-cache-dir --no-warn-script-location -r requirements.txt

LABEL org.opencontainers.image.vendor="Denodo Technologies" \
    org.opencontainers.image.authors="Denodo Technologies <support@denodo.com>" \
    org.opencontainers.image.created=$BUILD_DATE \
    org.opencontainers.image.version=$IMAGE_VERSION \
    org.opencontainers.image.title="$IMAGE_TITLE" \
    org.opencontainers.image.description="$IMAGE_DESCRIPTION"

CMD [ "/opt/ai-sdk/entrypoint.sh" ]