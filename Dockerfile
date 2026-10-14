FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY diemrenluyen_v2 ./diemrenluyen_v2

# Database lives on a mounted volume so subscriptions and seen-post
# history survive container restarts.
ENV DATABASE_FILE=/data/bot.db
VOLUME /data

CMD ["python", "-m", "diemrenluyen_v2.main"]
