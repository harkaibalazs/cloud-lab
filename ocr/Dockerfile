FROM python:3.14-bookworm-slim

RUN pip install --upgrade pip

WORKDIR /app

COPY requirements.txt requirements.txt

RUN pip install -r "requirements.txt"

COPY app.py app.py

CMD ["python3", "app.py"]