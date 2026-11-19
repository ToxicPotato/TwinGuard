FROM python:3.11-slim
WORKDIR /app
COPY report-service/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY python ./python
COPY report-service ./reportservice
RUN mkdir -p /app/reportservice/output
CMD ["uvicorn", "reportservice.app.main:app", "--host", "0.0.0.0", "--port", "8002"]
