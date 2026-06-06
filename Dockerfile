FROM python:3.12-alpine

WORKDIR /app
COPY server.py index.html ./

ENV ESTKME_HOST=0.0.0.0
ENV ESTKME_PORT=8765
ENV ESTKME_DATA_DIR=/data

EXPOSE 8765
VOLUME ["/data"]

CMD ["python", "/app/server.py"]
