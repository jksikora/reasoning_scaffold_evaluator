## Scaffold: graf ograniczeń
Pracujesz na scaffoldzie ⟨C, A, R, Γ, D⟩. C to słownik powyżej; jego elementy (stany, zdarzenia, warunki) są węzłami grafu.
- A – założenia: {"id": "A1", "text": "...", "status": "required" | "inferred" | "unresolved", "source": ID wymagania albo null}. Założenie "required" musi wskazywać wymaganie.
- R – krawędzie grafu ograniczeń:
  - requires(x, y): x jest możliwe tylko wtedy, gdy zachodzi y,
  - excludes(x, y): x i y nie mogą zachodzić jednocześnie (relacja symetryczna),
  - precedes(x, y): x musi wystąpić przed y (ścisłe następstwo).
  Format: {"id": "G1", "type": "requires" | "excludes" | "precedes", "from": x, "to": y, "source": ID wymagania lub założenia albo "vocabulary"}.
  Pary warunków wykluczających się ze słownika zapisz jako krawędzie "excludes" ze źródłem "vocabulary".
- Γ – reguły grafu (domknięcie relacji requires, wykluczenia, cykle) sprawdza skrypt, nie Ty.
- D – decyzje, czyli przejścia przyszłego modelu z uzasadnieniem: {"id": "D1", "transition": [skąd, zdarzenie, warunek albo null, dokąd], "justified_by": [ID elementów A lub R]}.

## Aktualny scaffold
{{scaffold}}

## Zadanie
Zaktualizuj scaffold tak, aby odzwierciedlał zmianę. Zapisz wiernie, co mówi każde nowe lub zmienione wymaganie, nawet jeśli wydaje się sprzeczne z innymi – spójność sprawdzi skrypt.
Jeśli zmiana usuwa lub zmienia wymaganie, usuń lub zmień elementy, które się na nim opierają. Nie ruszaj elementów, których zmiana nie dotyczy.

## Odpowiedź
Zwróć wyłącznie różnicę w JSON:
{"add": {"A": [...], "R": [...], "D": [...]}, "modify": {"A": [...], "R": [...], "D": [...]}, "remove": [ID, ...]}
- add: nowe elementy z nowymi, nieużywanymi ID,
- modify: pełne nowe wersje elementów o istniejących ID,
- remove: ID usuwanych elementów.
