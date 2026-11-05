FROM python:3.12-slim-bookworm
WORKDIR /app
COPY hw5/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY hw3/config.json /app/hw3/config.json
COPY hw3/frontend_lake/__init__.py hw3/frontend_lake/common.py hw3/frontend_lake/validation.py /app/hw3/frontend_lake/
COPY hw5/src/app.py /app/app.py
ENV PYTHONPATH=/app/hw3 PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER 1000:1000
ENTRYPOINT ["python", "/app/app.py"]
