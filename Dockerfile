# Portable image voor de BeBetter PWA-backend (werkt op Render, Railway en Fly.io).
# Bouwt vanaf de repo-root omdat de app (pwa/) het gedeelde intake_store.py uit de
# root hergebruikt -> zelfde opslag als Streamlit.
FROM python:3.12-slim

WORKDIR /app

# Eerst alleen de deps -> snellere herbouw bij codewijzigingen
COPY pwa/requirements.txt pwa/requirements.txt
RUN pip install --no-cache-dir -r pwa/requirements.txt

# Dan de rest van de repo (intake_store.py in de root + de pwa/-map)
COPY . .

WORKDIR /app/pwa

# Hosting geeft de poort via $PORT; lokaal valt hij terug op 8000.
ENV PORT=8000
CMD ["sh", "-c", "uvicorn api:app --host 0.0.0.0 --port ${PORT:-8000}"]
