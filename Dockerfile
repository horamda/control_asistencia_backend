# syntax=docker/dockerfile:1

ARG PYTHON_VERSION=3.12.13

FROM python:${PYTHON_VERSION}-slim

# Logs sin buffer (Railway los lee de stdout) y sin .pyc en la imagen.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /code

COPY requirements.txt requirements.txt
RUN pip3 install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

CMD ["python", "scripts/start_server.py"]
