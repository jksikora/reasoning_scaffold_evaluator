"""Jedyne miejsce, w którym wywoływany jest model językowy (Ollama).

Konfiguracja przez zmienne środowiskowe:
  OLLAMA_MODEL (domyślnie phi3:mini), OLLAMA_BASE_URL (domyślnie http://localhost:11434),
  OLLAMA_TEMPERATURE (0.2), OLLAMA_NUM_CTX (8192).
"""
import os
import time

import ollama

MODEL = os.getenv("OLLAMA_MODEL", "phi3:mini")
TEMPERATURE = float(os.getenv("OLLAMA_TEMPERATURE", "0.2"))
# Domyślny kontekst Ollamy (2-4 tys. tokenów) po cichu ucina długie prompty, stąd jawna wartość.
NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "8192"))
# Ograniczenie długości odpowiedzi: przy wymuszonym JSON-ie mały model potrafi się zapętlić.
NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "4096"))

_client = ollama.Client(host=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"))


def model_info():
    """Dokładna wersja modelu (nazwa i skrót pliku) do zapisania w wynikach."""
    for m in _client.list().models:
        if m.model == MODEL:
            return {"model": MODEL, "digest": m.digest, "temperature": TEMPERATURE, "num_ctx": NUM_CTX}
    raise RuntimeError(f"Model {MODEL} nie jest dostępny w Ollamie (ollama pull {MODEL})")


def chat(prompt, schema=None):
    """Jedno wywołanie. schema: schemat JSON wymuszający format odpowiedzi albo None (tekst)."""
    start = time.time()
    response = _client.chat(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        format=schema,
        options={"temperature": TEMPERATURE, "num_ctx": NUM_CTX, "num_predict": NUM_PREDICT},
    )
    return {
        "text": response.message.content,
        "prompt_tokens": response.prompt_eval_count or 0,
        "output_tokens": response.eval_count or 0,
        "seconds": round(time.time() - start, 2),
    }
