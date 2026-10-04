FROM python:3.12-slim
WORKDIR /project
RUN pip install --no-cache-dir Flask==3.1.2 SQLAlchemy==2.0.44 psycopg2-binary==2.9.11
EXPOSE 8090
CMD ["python", "-m", "web.app"]
