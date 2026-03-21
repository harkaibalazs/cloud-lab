FROM python:3.14-slim-bookworm

RUN pip install --upgrade pip

WORKDIR /app

COPY requirements.txt requirements.txt

RUN pip install -r "requirements.txt"

COPY app.py app.py

EXPOSE 8000

CMD ["uvicorn", "app:asgi_app", "--host", "0.0.0.0", "--port", "8000"]
