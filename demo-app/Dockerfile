FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY demo_app.py ./

RUN useradd --create-home --uid 10001 demo
USER demo

EXPOSE 8000
CMD ["uvicorn", "demo_app:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
