FROM python:3.11-slim

WORKDIR /app

# Install system dependencies including coin-or-cbc for PuLP LP solver
RUN apt-get update && apt-get install -y --no-install-recommends \
    coinor-cbc \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

ENV HOST=0.0.0.0
ENV PORT=8000

CMD ["python", "main.py"]
