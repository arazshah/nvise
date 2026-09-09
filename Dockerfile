FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# All current Python dependencies provide wheels for Python 3.12.
# psycopg is installed with the binary extra, so gcc/build-essential/libpq-dev
# are not required in the runtime image.
COPY . .

RUN python -m pip install --upgrade pip \
    && python -m pip install .

EXPOSE 8000

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
