FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install chromium
COPY . .
RUN mkdir -p /app/data/logs /app/logs
CMD ["python", "main.py"]
