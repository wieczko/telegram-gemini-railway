# telegram-gemini-railway

Lekki bot Telegrama działający w trybie long polling. Do generowania odpowiedzi
używa Gemini API przez zgodny interfejs OpenAI; domyślny model to
`gemini-3.8-flash`, który obecnie ma bezpłatny limit w Google AI Studio.
Bot trwale archiwizuje wszystkie wiadomości użytkownika i odpowiedzi oraz
przygotowuje kontekst z ostatnich 10 wymian i do 6 pasujących wcześniejszych
rozmów. To model Gemini, nie model OpenAI GPT; bezpłatny dostęp do API OpenAI
GPT nie jest wymagany ani używany.

## Wymagania

- Konto Telegram i token utworzony przez [@BotFather](https://t.me/BotFather).
- Klucz Gemini API utworzony w [Google AI Studio](https://aistudio.google.com/apikey).
- Repozytorium GitHub oraz konto Railway.

Gemini API ma ograniczenia bezpłatnego planu, które Google może zmieniać.
W bezpłatnym planie Google może wykorzystywać przesłane treści do ulepszania
swoich usług — nie wysyłaj przez bota poufnych danych. Railway musi utrzymywać
proces online; ciągła praca może wymagać płatnego planu lub zużywać dostępne
środki/limity Railway. Sam model AI nie wymaga płatnego klucza OpenAI.

## Publikacja kodu na GitHub

1. Utwórz na GitHubie nowe, puste repozytorium (bez README i bez `.gitignore`).
2. W terminalu, w katalogu projektu, wykonaj poniższe polecenia:

   ```bash
   git add .
   git commit -m "Prepare telegram-gemini-railway for deployment"
   git branch -M main
   git remote add origin https://github.com/wieczko/telegram-gemini-railway.git
   git push -u origin main
   ```

Plik `.env` zawierający sekrety jest ignorowany przez Git. Do repozytorium
dodawaj wyłącznie `.env.example`, nigdy prawdziwe klucze.

## Wdrożenie na Railway

1. W Railway wybierz **New Project → Deploy from GitHub repo** i wskaż
   utworzone repozytorium. Railway wykryje `Dockerfile`.
2. W ustawieniach usługi dodaj **Volume** zamontowany pod `/data`. Dzięki temu
   baza rozmów przetrwa restarty i nowe wdrożenia. Ustaw jedną replikę — Telegram
   long polling nie może być uruchomiony jednocześnie w kilku replikach z tym
   samym bot tokenem.
3. Włącz automatyczny restart **Always**.
4. W **Variables** dodaj:

   | Zmienna | Wartość |
   | --- | --- |
   | `TELEGRAM_TOKEN` | Token otrzymany od @BotFather |
   | `GEMINI_API_KEY` | Klucz z Google AI Studio |
   | `GEMINI_MODEL` | `gemini-3.8-flash` (opcjonalne; to wartość domyślna) |
   | `BOT_DATABASE_PATH` | `/data/bot.sqlite3` |
   | `ALLOWED_TELEGRAM_USER_IDS` | Opcjonalna lista numerycznych ID, oddzielona przecinkami |

5. Po dodaniu zmiennych Railway zbuduje i uruchomi usługę.
   W logach sprawdź, czy proces wystartował bez błędu. Otwórz bota w Telegramie,
   wyślij `/start`, a następnie zwykłą wiadomość.

Po włączeniu restartu Railway będzie ponownie uruchamiać proces po awarii.
Nie ustawiaj harmonogramu Cron ani healthchecka HTTP — bot utrzymuje połączenie
przez polling Telegrama i nie udostępnia serwera HTTP.

### Ograniczenie dostępu

Domyślnie bot przyjmuje wiadomości od każdego użytkownika Telegrama, który go
odnajdzie. Aby ograniczyć dostęp i chronić darmowy limit Gemini, ustaw
`ALLOWED_TELEGRAM_USER_IDS`, np. `123456789,987654321`. Swoje numeryczne ID
Telegrama możesz sprawdzić, kontaktując się z botem typu `@userinfobot`.
Pozostawienie tej zmiennej pustej oznacza dostęp publiczny.

## Uruchomienie lokalne

Wymagany jest Python 3.11 lub nowszy.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Wpisz prawdziwe wartości `TELEGRAM_TOKEN` i `GEMINI_API_KEY` do `.env`, a potem:

```bash
python bot.py
```

## Pamięć i dane

- `/start` — rozpocznij rozmowę
- `/help` — pomoc
- `/reset` — usuń całą trwale zapisaną historię swoich rozmów

Wszystkie wiadomości i odpowiedzi są przechowywane w bazie SQLite, osobno dla
każdego ID użytkownika. Przy nowej wiadomości bot używa ostatnich 10 wymian oraz
do 6 wcześniejszych rozmów dobranych po pasujących słowach. Pełne archiwum
pozostaje zapisane na wolumenie, ale nie jest w całości wysyłane do modelu, aby
nie przekraczać limitu kontekstu. `/reset` usuwa zarówno archiwum, jak i indeks
wyszukiwania danego użytkownika. Usunięcie wolumenu Railway bez kopii zapasowej
skasuje wszystkie zapisane rozmowy. Dane pozostają na wolumenie bezterminowo,
do momentu użycia `/reset` lub usunięcia wolumenu.
