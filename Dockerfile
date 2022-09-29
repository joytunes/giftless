# Dockerfile for uWSGI wrapped Giftless Git LFS Server

### --- Build Depdendencies ---

FROM python:3.7 as builder
MAINTAINER "Shahar Evron <shahar.evron@datopian.com>"

# Build wheels for uWSGI and all requirements
RUN DEBIAN_FRONTEND=noninteractive apt-get update \
    && apt-get install -y build-essential libpcre3 libpcre3-dev git
RUN pip install -U pip
RUN mkdir /wheels

ARG UWSGI_VERSION=2.0.18
RUN pip wheel -w /wheels uwsgi==$UWSGI_VERSION

COPY requirements.txt /
RUN pip wheel -w /wheels -r /requirements.txt

### --- Build Final Image ---

FROM python:3.7-slim

RUN DEBIAN_FRONTEND=noninteractive apt-get update \
    && apt-get install -y libpcre3 libxml2 tini \
    && apt-get clean \
    && apt -y autoremove

RUN mkdir /app

# Install dependencies
COPY --from=builder /wheels /wheels
RUN pip install /wheels/*.whl

# Copy project code
COPY . /app
RUN pip install -e /app

ARG USER_NAME=giftless

RUN useradd -d /app $USER_NAME

# Pip-install some common WSGI middleware modules
# These are not required in every Giftless installation but are common enough
ARG EXTRA_PACKAGES="wsgi_cors_middleware"
RUN pip install ${EXTRA_PACKAGES}

USER $USER_NAME

WORKDIR /app

ENV UWSGI_MODULE "giftless.wsgi_entrypoint"

ENTRYPOINT ["tini", "uwsgi", "--"]

CMD ["--http", "0.0.0.0:80", "-M", "-T", "--threads", "2", "-p", "2", \
     "--manage-script-name", "--callable", "app"]
