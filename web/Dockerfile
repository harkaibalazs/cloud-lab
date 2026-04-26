FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

FROM python:3.14-slim-bookworm
RUN pip install --upgrade pip
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY app.py .
COPY --from=frontend /build/dist ./static
EXPOSE 8000
CMD ["uvicorn", "app:asgi_app", "--host", "0.0.0.0", "--port", "8000"]
