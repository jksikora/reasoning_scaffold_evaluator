# Reasoning Scaffolds for Evolving Requirements

Stanowisko eksperymentalne do projektu opisanego w `konspekt.txt`. Sprawdzamy, czy jawne scaffoldy
(kwadrat logiczny – M1, graf ograniczeń – M2) pomagają LLM-owi aktualizować maszynę stanów przy
zmieniających się wymaganiach. Punktem odniesienia są B1 (zwykły LLM) i B2 (swobodna analiza + model).

**Konwencja językowa:**
- Po angielsku: identyfikatory w kodzie, nazwy w słowniku systemów (stany, zdarzenia, warunki),
  wartości wyliczeniowe w danych i odpowiedziach LLM-a oraz nazwy metryk w CSV.
- Po polsku: raport (`report.md`), README, komentarze, komunikaty, treść wymagań i promptów.

## Struktura

```
konspekt.txt            plan projektu
prompts/                wspólny szablon (template.md) i środkowe sekcje wariantów
data/example/           JEDEN przykładowy system (orders) – wzór formatu, NIE wchodzi do eksperymentu
data/pilot/             3 systemy pilotażowe, po 6 kroków i 4 przypadki Z
data/main/              dataset właściwy (10 systemów) – do uzupełnienia przez zespół
src/
  model.py              maszyna stanów: walidacja, determinizm, osiągalność, testy wymagań
  dataset.py            wczytywanie i walidacja datasetu, wzorzec W/P dla każdego kroku
  scaffold.py           wspólna część scaffoldu: diff po ID, odnośniki w D, źródła konfliktów
  square.py             Γ kwadratu logicznego (tabela trzech stanów)
  graph.py              Γ grafu ograniczeń (requires⁺, wykluczenia, cykle) i strefa wpływu
  prompts.py            składanie promptów, schematy JSON odpowiedzi
  llm.py                jedyne miejsce wywołania LLM (Ollama)
  experiment.py         manifest, snapshot danych i kontrola zgodności wznowienia
  demo.py               demonstracja offline na podstawionych odpowiedziach
  run.py                runner: sekwencje zmian i zestaw Z → results/<nazwa>/*.jsonl
  metrics.py            metryki jednego kroku
  analysis.py           CSV, Wilcoxon + Holm, wykresy, report.md
tests/                  testy jednostkowe i integracyjne (LLM podstawiony)
results/proba_phi3/     częściowy wynik pierwszego próbnego przebiegu (patrz niżej)
```

## Uruchomienie

Wymagania: Python 3.12+ (wymagany przez przypiętą wersję SciPy) i działająca [Ollama](https://ollama.com) z pobranym modelem.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
ollama pull phi3:mini                       # albo inny model, patrz zmienne niżej

python -m pytest -q                         # testy (nie wymagają Ollamy)
python -m src.dataset data/main             # walidacja datasetu przed eksperymentem

# próba integracyjna na przykładzie (1 powtórzenie, kroki 0-1)
python -m src.run --data data/example --out results/proba --reps 1 --steps 2

# pełny eksperyment (sekwencje + zestaw Z, 4 warianty, 5 powtórzeń)
python -m src.run --data data/main --out results/glowny
# opcjonalna ablacja bez skryptu na wybranych systemach
python -m src.run --data data/main --out results/ablacja --variants M1_noscript M2_noscript --systems <s1> <s2> <s3> --part sequences

python -m src.analysis results/glowny       # steps.csv, z.csv, report.md, plot_*.png
```

Zmienne środowiskowe: `OLLAMA_MODEL` (domyślnie `phi3:mini`), `OLLAMA_BASE_URL`
(`http://localhost:11434`), `OLLAMA_TEMPERATURE` (`0.2`), `OLLAMA_NUM_CTX` (`8192`),
`OLLAMA_NUM_PREDICT` (`4096`). Dokładna wersja modelu (digest) jest zapisywana w `config.json` przebiegu.

Przed wywołaniem Ollamy runner waliduje wybrane dane. Pusty dataset, nieznany system,
błędne dane lub niedodatnie `--reps`/`--steps` kończą się błędem bez utworzenia przebiegu.

Przerwany przebieg wznawia się **identycznym poleceniem**. Sekwencje niekompletne są powtarzane
od kroku 0; analiza wybiera ostatni rekord dla danego klucza. Manifest `config.json` zapisuje
wersję formatu, parametry, digest modelu, `num_predict`, skróty kodu/promptów/zależności i danych
oraz wersje środowiska. Dane są zamrożone w `dataset_snapshot.json`. Zmiana konfiguracji,
modelu, kodu, promptów lub danych wymaga **nowego katalogu `--out`**. Konfiguracja nie jest
nadpisywana. Samo przeniesienie danych bez zmiany ich treści nie blokuje wznowienia.

Analiza nowych przebiegów korzysta ze snapshotu, więc katalog wyników można przenieść i analizować
bez oryginalnego datasetu. Starsze przebiegi bez manifestu można analizować wyłącznie z odpowiednią
historyczną wersją danych i ostrzeżeniem o braku gwarancji zgodności; nie można ich wznawiać.

Każdy rekord w `sequences.jsonl` / `z.jsonl` zawiera pełne prompty i odpowiedzi, tokeny, czas,
liczbę prób, diff scaffoldu, wykryte konflikty i zatwierdzony model. Dzięki temu metryki można
przeliczyć bez ponownego wywoływania LLM-a.

Wynik kroku (`result`):

| wartość | znaczenie |
|---|---|
| `OK` | zmiana przyjęta |
| `CONFLICT` | wariant albo skrypt zgłosił konflikt |
| `REJECTED` | skrypt odrzucił diff scaffoldu |
| `ERROR` | niepoprawna odpowiedź mimo ponowienia |
| `SCAFFOLD_ERROR` | tylko w zestawie Z: nie udało się zbudować scaffoldu bazowego |

## Minimalny setup: pilotaż i wizualizacje

To eksperyment z gotowym LLM-em, nie trening wag modelu. `data/main` jest nadal pusty;
próba jego uruchomienia poprawnie kończy się błędem. Na start użyj `data/pilot`:

- `reservations`: rezerwacje i obsługa pobytu;
- `library`: rezerwacja i wypożyczenie książki;
- `access`: weryfikacja i cykl życia uprawnienia dostępu.

Każdy system ma krok początkowy i pięć zmian (reguła, zależność, zmiana przejścia, usunięcie,
sprzeczność), w różnej kolejności. Każdy ma też 4 przypadki Z: stanowy, przechodni, kolejności
oraz pułapkę. Wzorce mieszczą się w ograniczeniu jednego warunku na przejście. Wszystkie
wymagania mają testy, w tym zakazy dla przeciwnych warunków w regułach „tylko gdy”.
To mały zestaw do sprawdzenia integracji, nie zbiór do potwierdzania hipotez badawczych.

### Raport demonstracyjny bez Ollamy

```bash
source .venv/bin/activate
python -m pytest -q
python -m src.dataset data/pilot
python -m src.demo --out results/demo_mock
```

Demonstracja tworzy 240 rekordów (3 systemy × 4 warianty × 2 powtórzenia × 10 kroków/przypadków),
CSV, `report.md` i sześć wykresów PNG. Używa zaplanowanych odpowiedzi, w tym celowych błędów,
aby pokazać walidację oraz różnice na wykresach. **To nie są wyniki rzeczywistego LLM.**
Ponowne wykonanie tego samego polecenia pomija ukończone rekordy. Po zmianie kodu użyj nowego `--out`.

### Pilotaż z rzeczywistym LLM

Uruchom Ollamę (`ollama serve`, jeśli usługa jeszcze nie działa), pobierz wybrany model i ustaw
`OLLAMA_MODEL`. Domyślny `phi3:mini` służy jedynie do sprawdzenia integracji — historyczna próba
pokazała problemy z jakością. Po wybraniu modelu:

```bash
python -m src.dataset data/pilot

# Krótka próba; do wznowienia użyj dokładnie tego samego polecenia.
python -m src.run --data data/pilot --out results/pilot_krotki_01 --reps 1 --steps 2 --part sequences
python -m src.analysis results/pilot_krotki_01

# Pełny pilotaż w osobnym katalogu.
python -m src.run --data data/pilot --out results/pilot_pelny_01 --reps 1
python -m src.analysis results/pilot_pelny_01
```

Nie zmieniaj parametrów ani modelu przy tym samym `--out`. Przed dużym eksperymentem przejrzyj
surowe odpowiedzi oraz poprawność maszyn; samo `result=OK` oznacza przyjęcie odpowiedzi,
a nie jej poprawność.

### Jak czytać raport

- `requirement_satisfaction`: surowy odsetek zaliczonych testów wymagań, także dla niepoprawnej maszyny.
- `model_valid`: poprawność deklaracji stanów, stanu początkowego i końcowych, słownika przejść
  oraz determinizmu. Nieosiągalność stanów jest ostrzeżeniem i nie zeruje tej metryki.
- `model_validation_errors`: liczba błędów walidacji; w JSONL pole zawiera szczegółową listę błędów.
- `fully_correct`: poprawna maszyna **i** zgodność przejść z W/P. Niepoprawny model pozostaje
  w historii wariantu, a jego testy wymagań nadal są liczone bez kary za walidację.
- Nagłówek pokazuje kompletność planowanych rekordów, zakres kroków i powtórzeń. Pilotaż, niepełny
  przebieg i stare formaty otrzymują wyłącznie analizę eksploracyjną. Część potwierdzająca wymaga
  co najmniej 10 systemów, czterech wariantów i wszystkich sześciu kroków oraz kompletnego manifestu.
- Średnie tabelaryczne mają liczebności `n`. Wykresy po krokach pokazują średnie po systemach
  i ±SD między systemami przy co najmniej dwóch systemach; pasma przycięto do zakresu 0–1.
- Wykrywanie konfliktów jest oddzielne dla sekwencji i Z, z licznikami i mianownikami. Brak danych
  to „–”, a nie zero. Statusy `ERROR`, `REJECTED`, `SCAFFOLD_ERROR` nie są wykryciem konfliktu.
- Koszt dotyczy ocenionych rekordów po deduplikacji, wraz z ponowieniami odpowiedzi. Nie obejmuje
  wszystkich wcześniejszych rekordów zastąpionych przy wznowieniu ani przerwanych wywołań bez zapisu.

## Format datasetu

Katalog danych zawiera `systems/<system>.json` i (opcjonalnie) `conflicts/<system>.json`.
Pełny przykład: `data/example/`. Nazwy w słowniku powinny być angielskie i bez znaków
diakrytycznych (patrz „Próbny przebieg”).

### System i sekwencja zmian

```json
{
  "system": "orders",
  "vocabulary": {
    "states": [...], "events": [...], "guards": [...],
    "exclusive": [["before_24h", "after_24h"], ["in_stock", "out_of_stock"]]
  },
  "initial": "New",
  "steps": [ krok 0, krok 1, ..., krok 5 ]
}
```

Krok:

| pole | znaczenie |
|---|---|
| `type` | `initial` (krok 0), `new_rule`, `new_dependency`, `transition_change`, `removal`, `contradiction` |
| `description` | opis zmiany pokazywany LLM-owi (w kroku 0 pomijany) |
| `add` | nowe wymagania; wymaganie o istniejącym ID **zastępuje** stare (zmiana wymagania) |
| `remove` | ID usuwanych wymagań |
| `affects` | (opcjonalnie) dodatkowe ID wymagań, których dotyczy zmiana, oprócz dodanych/zmienionych/usuniętych |
| `W`, `P` | pełne zbiory przejść wymaganych i dopuszczalnych **po** kroku: `[skąd, zdarzenie, warunek albo null, dokąd]` |
| `conflicting`, `kind` | tylko dla `contradiction`: lista kłócących się wymagań i rodzaj konfliktu (`state`/`transitive`/`ordering`); taki krok nie ma `W`/`P` |

Wymaganie: `{"id": "R3", "text": "...", "tests": [...]}`. Wymaganie jest spełnione, gdy przechodzą
wszystkie jego testy. Typy testów:

| test | znaczenie |
|---|---|
| `{"type": "has_transition", "from": s, "event": e}` | w stanie s istnieje jakieś przejście na e |
| `... "guard": "g"` | e jest dozwolone w sytuacji, gdy zachodzi g (przejście z g albo bez warunku) |
| `... "guard": null` | e jest dozwolone w każdej sytuacji (patrz U3) |
| `... "to": d` | (opcjonalnie) uwzględniamy tylko przejścia do stanu d |
| `{"type": "no_transition", ...}` | zaprzeczenie `has_transition` z tymi samymi polami |
| `{"type": "reachable", "state": s}` | s jest osiągalny ze stanu początkowego |
| `{"type": "always_before", "state": s, "before": b}` | każda droga do s przechodzi przez b |

`python -m src.dataset <katalog>` sprawdza m.in. słownik, typy, ID, rozłączność W i P oraz to, czy
model złożony z samego `W` spełnia testy wszystkich zatwierdzonych wymagań. Ta ostatnia kontrola
wyłapuje większość pomyłek we wzorcu.

### Zestaw sprzeczności Z

```json
{"system": "orders", "cases": [
  {"id": "Z1", "kind": "state", "description": "...", "add": [...], "remove": [...], "conflicting": ["R5", "R9"]},
  {"id": "Z4", "kind": "trap", "description": "...", "add": [...]}
]}
```

`kind`: `state` (stanowy), `transitive` (przechodni), `ordering` (kolejności) albo `trap` (pułapka).
Bazą każdego przypadku są wymagania i wzorzec `W` kroku 0 tego systemu. Pułapki nie mają pola `conflicting`.

## Scaffold w implementacji

* `C` to słownik systemu. Jest stały, więc LLM go nie buduje.
* `A`: `{"id": "A1", "text": ..., "status": "required|inferred|unresolved", "source": "R1"|null}`.
* `R` w M1: `{"id": "K1", "state", "event", "form": "A|E|I|O", "value": "true|false|unresolved", "source"}`.
* `R` w M2: `{"id": "G1", "type": "requires|excludes|precedes", "from", "to", "source"}`.
* `D`: `{"id": "D1", "transition": [s, e, g, t], "justified_by": ["A1", "K3"]}`.
* LLM zawsze zwraca **różnicę**: `{"add": {"A","R","D"}, "modify": {"A","R","D"}, "remove": [ID]}`.

Przebieg kroku M1/M2:
1. Wywołanie 1: diff scaffoldu.
2. Skrypt sprawdza ID i słownik, stosuje diff i sprawdza Γ.
3. Wynik:
   * konflikt → `CONFLICT` (zmiana pending, scaffold i model bez zmian);
   * błędny diff → `REJECTED`;
   * w przeciwnym razie wywołanie 2 generuje model.

## Ustalenia interpretacyjne

Konspekt nie rozstrzyga poniższych kwestii jednoznacznie. Przyjęte rozstrzygnięcia można zmienić
w miejscach wskazanych w kolumnie „Gdzie w kodzie”.

| # | Ustalenie | Gdzie w kodzie |
|---|---|---|
| U1 | „Ostatni zatwierdzony model” w kroku k to **własny** model danego wariantu z kroku k-1, a nie wzorzec. Dlatego jedno powtórzenie obejmuje całą sekwencję 0–5. Bez tego nie da się zmierzyć kumulacji błędów (P2). | `run.run_sequence` |
| U2 | Ponowienie (najwyżej 1) następuje tylko przy niepoprawnej **strukturze** odpowiedzi (JSON nie parsuje się, brak wymaganych pól). Jeśli po ponowieniu odpowiedź nadal jest zła, krok ma wynik `ERROR`, a model się nie zmienia. Błędy merytoryczne modelu (nazwy spoza słownika, niedeterminizm) nie powodują ponowienia. Model jest wtedy przyjmowany, a problemy trafiają do metryki `model_issues`. | `run.ask_json`, `model.semantic_issues` |
| U3 | Przejścia z kompletem warunków jednej pary wykluczającej się (np. `before_24h` i `after_24h`) traktujemy w testach wymagań jak „zawsze dozwolone”, tak samo jak przejście bez warunku. | `model._allowed` |
| U4 | Założenie egzystencjalne kwadratu (osiągalność stanów) jest sprawdzane na **modelu** po jego wygenerowaniu i logowane jako ostrzeżenie (`model_issues`), a nie jako blokada. Przy walidacji scaffoldu modelu jeszcze nie ma. | `model.semantic_issues` |
| U5 | „Poprawne uzasadnienie” w D: istnieje wpis z identycznym przejściem, niepustym `justified_by` i wszystkimi odnośnikami wskazującymi istniejące elementy A lub R. Automatycznie sprawdzamy tylko istnienie odnośników, a nie ich sens. | `scaffold.unjustified` |
| U6 | Lista kłócących się wymagań w M1/M2 to źródła (`source`) elementów R biorących udział w konflikcie. Źródło może wskazywać wymaganie bezpośrednio albo przez założenie A. | `scaffold.requirements_of` |
| U7 | „Wymaganie, którego zmiana k nie dotyczyła” (regresja funkcjonalna): wymagania dodane, zmienione lub usunięte w kroku k oraz te wpisane w opcjonalne pole `affects` są wyłączone. | `dataset.gold_steps` |
| U8 | Testy wymagań mają 4 typy (tabela wyżej). Dodanie nowego typu wymaga zmiany w `model.run_test`. | `model.run_test` |
| U9 | W zestawie Z oceniamy tylko wykrywanie, dlatego M1/M2 nie generują modelu. Wykonują budowę scaffoldu i diff zmiany, czyli 2 wywołania zamiast 3. Jeśli scaffold bazowy się nie powiedzie, wynikiem jest `SCAFFOLD_ERROR`, liczony jako niewykrycie. | `run.run_z_case` |
| U10 | Krok 0 w M1/M2 to diff od pustego scaffoldu (same operacje `add`). Dzięki temu budowa i aktualizacja przechodzą tę samą ścieżkę. W B1/B2 krok 0 to model z pustego modelu. | `run.run_step` |
| U11 | Diff z nieistniejącym ID lub elementem spoza słownika jest **odrzucany bez ponowienia** (wynik `REJECTED`, skrypt „zablokował zmianę”). Konspekt: „sprawdza, czy wskazane ID istnieją … zatwierdza wynik albo go odrzuca”. | `scaffold.apply_diff` |
| U12 | Prefiksy ID: `A` założenia, `K` zdania kwadratu, `G` krawędzie grafu, `D` decyzje. Konspekt używa w przykładzie „R7” dla relacji, co kolidowałoby z ID wymagań. | `scaffold.R_PREFIX` |
| U13 | W M2 pary warunków wykluczających się ze słownika LLM zapisuje jako krawędzie `excludes` ze źródłem `"vocabulary"`. Prosi o to prompt, ale skrypt nie dodaje ich automatycznie. | `prompts/m2_scaffold.md` |
| U14 | Decyzja „brak przejścia” dla pary nierozstrzygniętej w kwadracie nie jest zapisywana w D. D zawiera tylko przejścia obecne w modelu, a brak przejścia wynika z zamkniętego świata. | – |
| U15 | Lista „zatwierdzonych wymagań” w prompcie pochodzi z datasetu i jest identyczna dla wszystkich wariantów, niezależnie od tego, czy wariant przyjął poprzednią zmianę. Konspekt: „identyczne wymagania i zmiany”. | `run.run_sequence` |
| U16 | Scaffold zatwierdzony przez Γ zostaje przyjęty także wtedy, gdy wygenerowanie modelu (wywołanie 2) się nie powiodło. | `run.run_step` |
| U17 | W M1/M2 konflikt zgłasza wyłącznie skrypt (Γ). LLM w tych wariantach nie ma odpowiedzi `CONFLICT`. W ablacji `*_noscript` Γ nie jest sprawdzane, a błędne operacje diffu są pomijane zamiast odrzucać cały diff. | `run.run_step` |
| U18 | Fałszywe alarmy w sekwencjach liczymy na wszystkich krokach bez konfliktu, łącznie z krokiem 0. | `analysis.detection_counts` |
| U19 | Wielkość efektu: mediana różnic per system i korelacja rangowo-dwuseryjna. Metryki o zerowym mianowniku (np. pokrycie dodań, gdy nic nie dodano) mają wartość pustą i nie wchodzą do średnich. | `analysis`, `metrics.ratio` |
| U20 | LLM: Ollama, domyślnie `phi3:mini`, temperatura 0,2, bez stałego ziarna (powtórzenia mają się różnić). Format odpowiedzi jest wymuszany schematem JSON (`format` w Ollamie). | `llm.py`, `prompts.py` |
| U21 | F1 = 0, gdy precyzja i czułość są zerowe albo model jest pusty (precyzja nieokreślona, czułość = 0). F1 jest puste tylko wtedy, gdy W jest puste. Wcześniej F1 wychodziło puste także dla całkowicie błędnego modelu, przez co takie kroki znikały ze średnich. Wykrył to próbny przebieg. | `metrics.step_metrics` |
| U22 | Walidacja maszyny jest osobna od spełnienia wymagań. Błędny model zostaje przyjęty; `fully_correct` wymaga poprawnej maszyny i zgodności W/P. | `model.validation_errors`, `metrics.step_metrics` |

## Próbny przebieg (smoke run) – 20.11.2026

Pierwsze uruchomienie z prawdziwym LLM-em, wykonane przed zmianą nazw na angielskie.

**Konfiguracja:**
- polecenie: `python -m src.run --data data/example --out results/proba_phi3 --variants B1 B2 M1 M2 --reps 1 --steps 2 --part sequences`;
- model: `phi3:mini` (digest `4f222292793889a9…`), temperatura 0,2, `num_ctx` 8192;
- sprzęt: CPU, 8 GB RAM, GTX 760 nieużywana przez Ollamę.

**Przebieg:** zapisano 6 z 8 planowanych kroków (B1, B2 i M1 po dwa kroki). Proces został zatrzymany podczas M2, krok 0, z powodu
braku pamięci RAM: Ollama z `phi3:mini` i kontekstem 8192 zajmuje ok. 5,6 GB.

| wariant | krok | wynik | czas | spełnienie wymagań | uwagi |
|---|---|---|---|---|---|
| B1 | 0 | OK | 280 s | 0,00 | stan „Opłacone” zamiast „Oplacone” |
| B1 | 1 | OK | 76 s | 0,00 | jw. |
| B2 | 0 | OK | 172 s | 0,17 | jw. + zdarzenie „dostarcze” |
| B2 | 1 | OK | 4680 s | 0,14 | jw. + puste zdarzenie; czas przez swap przy braku RAM |
| M1 | 0 | REJECTED | 648 s | 0,17* | diff: elementy w złych sekcjach, `modify` nieistniejących ID |
| M1 | 1 | REJECTED | 388 s | 0,14* | jw. |

\* Spełnione były tylko testy typu „brak przejścia” na pustym modelu.

**Wnioski:**
1. **Integracja działa.** Prompty, wymuszony JSON (0 ponowień), walidacja modelu, odrzucanie
   błędnego diffu i zapis logów zachowały się zgodnie z projektem.
2. **`phi3:mini` jest za słaby.** Konsekwentnie dodawał polskie znaki do nazw ze słownika
   („Opłacone”), więc każde przejście wypadało poza słownik. Nie radził sobie też z formatem diffu M1.
3. **Reakcja:** nazwy w słowniku i wszystkie wartości wyliczeniowe zmieniono na angielskie
   (`Paid`, `cancel`, `before_24h`, …). Naprawiono też F1 (U21).
4. **Sprzęt:** pełny eksperyment (~3000 wywołań po kilka minut) jest na tej maszynie praktycznie
   niewykonalny.

Pliki w `results/proba_phi3/` mają stare (polskie) nazwy, więc obecna wersja `src.analysis` ich nie
przetworzy. Zostają jako zapis surowych odpowiedzi.

## Znane ograniczenia

* **W/P porównują przejścia dosłownie.** Przejście bez warunku i komplet `before_24h` + `after_24h`
  są semantycznie równoważne, ale strukturalnie różne. Metryka główna (testy wymagań) jest
  semantyczna, więc tego problemu nie ma. Metryki strukturalne (precyzja, czułość, regresje
  strukturalne, halucynacje) mogą natomiast karać poprawne, inaczej zapisane rozwiązania.
  Zbiór P łagodzi to tylko wtedy, gdy autor wzorca przewidzi alternatywę.
* Uproszczenia eksperymentu z konspektu: pary warunków wyczerpujące i niezależne, jeden warunek
  na przejście, zamknięty świat.
* Mały model na CPU jest bardzo wolny i słaby jakościowo (patrz próbny przebieg).
* W zestawie Z scaffold bazowy jest budowany osobno dla każdego przypadku i powtórzenia (zgodnie
  z konspektem). To kosztowne, ale niezależne.
* Część teoretyczna raportu (typologia, przykłady dodatkowych typów scaffoldów) nie jest częścią kodu.

## TODO – co zostało do zakończenia projektu

Kolejność odpowiada kamieniom milowym K1–K6 z konspektu.

1. **Wybór modelu i sprzętu.** Wybrać model LLM mocniejszy niż `phi3:mini` i maszynę, która go
   uciągnie (GPU albo co najmniej 16 GB RAM). Ustawić `OLLAMA_MODEL`, ewentualnie zmniejszyć
   `OLLAMA_NUM_CTX` przy braku pamięci. Rozstrzygnąć z prowadzącym, czy drugi model ma objąć cały
   dataset (pytanie z konspektu).
2. **Powtórzyć próbny przebieg na przykładzie** (`data/example`, `--reps 1`, wszystkie warianty,
   pełna sekwencja i zestaw Z), a potem uruchomić `src.analysis`. Ręcznie przejrzeć kilka odpowiedzi
   w `sequences.jsonl` i sprawdzić, czy model trzyma się słownika i formatu diffu. Jeśli nie,
   poprawić prompty, zanim powstanie dataset właściwy.
3. **Dataset właściwy (K1).** Napisać 10 systemów w `data/main/systems/`:
   - słownik po angielsku;
   - kroki 0–5 z typami zmian, każda sekwencja z dokładnie jednym `contradiction` z `kind`;
   - pełne W/P po każdym kroku i testy dla każdego wymagania;
   - typy zmian rozłożyć tak, by na każdy typ przypadało ok. 10 przypadków.
4. **Zestaw Z (K1).** Przygotować 20–30 przypadków konfliktowych (po 2–3 na system, możliwie
   równo między `state`/`transitive`/`ordering`) oraz 6–10 pułapek w `data/main/conflicts/`.
5. **Walidacja datasetu:** `python -m src.dataset data/main` musi zwrócić OK dla wszystkich systemów.
   Warto też, żeby druga osoba z zespołu przejrzała wzorce W/P.
6. **Zamrożenie ustaleń.** Przed eksperymentem zatwierdzić prompty, ustalenia U1–U22 i część
   potwierdzającą (metryka, 5 porównań, Holm). Oznaczyć wersję w istniejącym repozytorium git
   tagiem, bo konspekt wymaga, by część potwierdzająca była ustalona przed eksperymentem.
7. **Krótki przebieg na `data/main`** (`--reps 1`, 1–2 systemy): oszacować czas i wyłapać błędy w danych.
8. **Eksperyment główny (K5):** `python -m src.run --data data/main --out results/glowny`.
   Opcjonalnie dodać ablację `*_noscript` na 3 systemach i drugi model LLM.
9. **Analiza (K6):** `python -m src.analysis results/glowny`, a następnie przegląd `report.md`,
   wykresów i kilku przykładowych odpowiedzi (jakościowe przykłady do raportu).
10. **Raport końcowy (po polsku):**
    - wyniki części potwierdzającej i eksploracyjnej;
    - część teoretyczna (typologia, 2–3 dodatkowe typy scaffoldów w formalizacji ⟨C, A, R, Γ, D⟩ –
      sekcje zakomentowane w konspekcie);
    - ograniczenia (sekcja wyżej i ustalenia U1–U22);
    - odpowiedź na uwagi profesora.
