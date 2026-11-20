## Analiza zmiany
{{analysis}}

## Zadanie
Na podstawie analizy utwórz lub zaktualizuj model tak, aby uwzględniał zmianę i nadal spełniał zatwierdzone wymagania, których zmiana nie dotyczy.
Jeżeli zmiana jest sprzeczna z zatwierdzonymi wymaganiami, nie zmieniaj modelu, tylko zgłoś konflikt.

## Odpowiedź
Zwróć wyłącznie JSON:
- brak konfliktu: {"result": "OK", "conflicting": [], "model": <pełny nowy model>}
- konflikt: {"result": "CONFLICT", "conflicting": [ID kłócących się wymagań], "model": null}
