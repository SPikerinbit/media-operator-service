FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libgomp1 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY app /app/app
COPY scripts/serve_api.sh /app/serve_api.sh
RUN chmod +x /app/serve_api.sh

EXPOSE 8090

# Listens on 127.0.0.1 inside the container unless MEDIA_BIND_HOST is set.
# A non-loopback host is refused until MEDIA_API_TOKEN is set.
CMD ["/app/serve_api.sh"]
