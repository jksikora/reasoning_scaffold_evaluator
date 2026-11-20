## Scaffold: kwadrat logiczny
Pracujesz na scaffoldzie ⟨C, A, R, Γ, D⟩. C to słownik powyżej.
- A – założenia: {"id": "A1", "text": "...", "status": "required" | "inferred" | "unresolved", "source": ID wymagania albo null}. Założenie "required" musi wskazywać wymaganie.
- R – zdania kwadratu logicznego dla par (stan s, zdarzenie e). Dziedzina: wszystkie możliwe sytuacje w stanie s (wszystkie kombinacje wartości warunków).
  - A: każda możliwa sytuacja w s pozwala wykonać e (przejście bez warunku),
  - E: żadna możliwa sytuacja w s nie pozwala wykonać e (brak przejścia),
  - I: niektóre możliwe sytuacje w s pozwalają wykonać e (istnieje przejście),
  - O: niektóre możliwe sytuacje w s nie pozwalają wykonać e (nie zawsze dozwolone).
  Format: {"id": "K1", "state": s, "event": e, "form": "A" | "E" | "I" | "O", "value": "true" | "false" | "unresolved", "source": ID wymagania lub założenia}.
  Zapisuj tylko zdania wynikające z wymagań lub założeń. Brak informacji oznacza "unresolved", a nie "false".
- Γ – reguły kwadratu sprawdza skrypt, nie Ty.
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
