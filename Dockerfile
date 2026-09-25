FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PORT=8000 \
    RUNNING_IN_DOCKER=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY fixtures ./fixtures

RUN mkdir -p /data/uploads

EXPOSE 8000

CMD ["python", "-m", "dogfood.entrypoint"]
