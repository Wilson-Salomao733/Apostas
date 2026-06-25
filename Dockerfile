FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    openssl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY betfair_api.py betfair_login.py api_football.py \
     combo_definitions.py opportunity_scanner.py config_loader.py \
     risk_manager.py auto_worker.py betting_bot.py bet_placement.py /app/

ENV PYTHONUNBUFFERED=1
ENV TZ=America/Sao_Paulo

CMD ["python", "betting_bot.py"]
