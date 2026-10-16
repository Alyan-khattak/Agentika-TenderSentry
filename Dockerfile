FROM python:3.12-slim

WORKDIR /app

COPY tendersentry/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY tendersentry/ .

ENV PORT=8000
EXPOSE $PORT

CMD uvicorn main:app --host 0.0.0.0 --port $PORT
