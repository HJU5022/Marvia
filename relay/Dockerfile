FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py .
RUN useradd --no-create-home relay
USER relay
# Cloud Run이 PORT를 넣어준다 (기본 8080)
CMD ["python", "main.py"]
