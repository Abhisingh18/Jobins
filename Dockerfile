FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Default: run the full 5-task evaluation suite.
# Override with: docker compose run agent python main.py "your task"
CMD ["python", "main.py", "--all-tests"]
