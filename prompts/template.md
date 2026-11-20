Modelujesz zachowanie systemu „{{system}}” jako uproszczoną maszynę stanów UML zapisaną w JSON.

## Słownik (wolno używać wyłącznie tych nazw)
Stany: {{states}}
Zdarzenia: {{events}}
Warunki: {{guards}}
Pary warunków wykluczających się (zawsze zachodzi dokładnie jeden warunek z pary): {{exclusive}}
Stan początkowy: {{initial}}

## Semantyka maszyny stanów
- Format modelu: {"states": [...], "initial": "...", "final": [...], "transitions": [...]}.
- Przejście: {"from": stan, "event": zdarzenie, "guard": warunek albo null, "to": stan}.
- Każde przejście ma co najwyżej jeden warunek (guard to jedna nazwa ze słownika albo null).
- Zamknięty świat: zdarzenie, dla którego w danym stanie nie ma przejścia, jest zabronione.
- Determinizm: dwa przejścia z tego samego stanu na to samo zdarzenie są dozwolone tylko wtedy, gdy ich warunki tworzą parę wykluczającą się.

## Zatwierdzone wymagania
{{requirements}}

## Ostatni zatwierdzony model
{{model}}

## Zmiana
{{change}}

{{section}}
