import logging
import os
from uuid import uuid4

from dotenv import load_dotenv
from openai import AsyncOpenAI, APIError, RateLimitError
from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from memory_store import (
    clear_user_history,
    initialize,
    recent_messages,
    relevant_messages,
    save_message,
)

load_dotenv()

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
DEFAULT_MODEL = "gemini-3.8-flash"
MAX_HISTORY_MESSAGES = 20
MAX_RELEVANT_TURNS = 6
TELEGRAM_MESSAGE_LIMIT = 4000
SYSTEM_PROMPT = (
    "Odpowiadaj po polsku, jasno i pomocnie. W kontekście mogą znajdować się "
    "ostatnie wiadomości oraz wybrane pasujące fragmenty wcześniejszych rozmów; "
    "korzystaj z nich, gdy są istotne dla pytania."
)

logger = logging.getLogger(__name__)


def split_message(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> list[str]:
    return [text[index : index + limit] for index in range(0, len(text), limit)]


async def start(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if update.effective_message and is_allowed(update, context):
        await update.effective_message.reply_text(
            "Cześć! Jestem botem AI. Napisz do mnie, a odpowiem.\n"
            "Użyj /reset, aby wyczyścić historię rozmowy."
        )
    elif update.effective_message:
        await update.effective_message.reply_text("Ten bot nie jest dla Ciebie dostępny.")


async def help_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if update.effective_message and is_allowed(update, context):
        await update.effective_message.reply_text(
            "Wyślij wiadomość, aby porozmawiać z AI.\n"
            "/reset — wyczyść historię rozmowy\n"
            "/help — pokaż tę pomoc"
        )
    elif update.effective_message:
        await update.effective_message.reply_text("Ten bot nie jest dla Ciebie dostępny.")


async def reset(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    user = update.effective_user
    if not is_allowed(update, context):
        if update.effective_message:
            await update.effective_message.reply_text("Ten bot nie jest dla Ciebie dostępny.")
        return
    if user:
        clear_user_history(context.application.bot_data["database_path"], user.id)
    if update.effective_message:
        await update.effective_message.reply_text("Historia rozmowy została wyczyszczona.")


async def handle_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not is_allowed(update, context):
        if update.effective_message:
            await update.effective_message.reply_text("Ten bot nie jest dla Ciebie dostępny.")
        return
    user = update.effective_user
    message = update.effective_message
    if not user or not message or not message.text:
        return

    database_path = context.application.bot_data["database_path"]
    turn_id = str(uuid4())
    save_message(database_path, user.id, turn_id, "user", message.text)

    remembered_messages = recent_messages(
        database_path, user.id, MAX_HISTORY_MESSAGES, exclude_turn_id=turn_id
    )
    recent_ids = {item["id"] for item in remembered_messages}
    matching_messages = relevant_messages(
        database_path,
        user.id,
        message.text,
        exclude_turn_id=turn_id,
        recent_message_limit=MAX_HISTORY_MESSAGES,
        turn_limit=MAX_RELEVANT_TURNS,
    )
    recalled_messages = [
        item for item in matching_messages if item["id"] not in recent_ids
    ]
    previous_messages = sorted(
        [*recalled_messages, *remembered_messages], key=lambda item: item["id"]
    )
    messages: list[dict[str, str]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *[
            {"role": item["role"], "content": item["content"]}
            for item in previous_messages
        ],
        {"role": "user", "content": message.text},
    ]

    try:
        response = await context.application.bot_data["ai_client"].chat.completions.create(
            model=context.application.bot_data["model"],
            messages=messages,
        )
    except RateLimitError:
        logger.info("Gemini free-tier rate limit reached for Telegram user %s", user.id)
        await message.reply_text(
            "Osiągnięto chwilowy limit darmowego modelu. Spróbuj ponownie później."
        )
        return
    except APIError:
        logger.exception("Gemini API request failed for Telegram user %s", user.id)
        await message.reply_text(
            "Nie udało mi się teraz uzyskać odpowiedzi od modelu. Spróbuj ponownie później."
        )
        return

    answer = response.choices[0].message.content
    if not answer or not answer.strip():
        logger.warning("Gemini returned an empty response for Telegram user %s", user.id)
        await message.reply_text("Model zwrócił pustą odpowiedź. Spróbuj zadać pytanie ponownie.")
        return

    save_message(database_path, user.id, turn_id, "assistant", answer)

    for part in split_message(answer):
        await message.reply_text(part)


def is_allowed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    allowed_user_ids: set[int] = context.application.bot_data["allowed_user_ids"]
    return bool(user and (not allowed_user_ids or user.id in allowed_user_ids))


async def close_ai_client(application: Application) -> None:
    await application.bot_data["ai_client"].close()


def create_application() -> Application:
    telegram_token = os.getenv("TELEGRAM_TOKEN")
    gemini_api_key = os.getenv("GEMINI_API_KEY")
    if not telegram_token:
        raise RuntimeError("Missing TELEGRAM_TOKEN environment variable.")
    if not gemini_api_key:
        raise RuntimeError("Missing GEMINI_API_KEY environment variable.")

    allowed_user_ids = {
        int(user_id.strip())
        for user_id in os.getenv("ALLOWED_TELEGRAM_USER_IDS", "").split(",")
        if user_id.strip()
    }
    database_path = os.getenv("BOT_DATABASE_PATH", "bot.sqlite3")
    initialize(database_path)
    client = AsyncOpenAI(
        api_key=gemini_api_key,
        base_url=GEMINI_BASE_URL,
        timeout=60.0,
        max_retries=2,
    )
    application = (
        ApplicationBuilder()
        .token(telegram_token)
        .post_shutdown(close_ai_client)
        .build()
    )
    application.bot_data["ai_client"] = client
    application.bot_data["database_path"] = database_path
    application.bot_data["model"] = os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
    application.bot_data["allowed_user_ids"] = allowed_user_ids

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("reset", reset))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )
    return application


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    application = create_application()
    application.run_polling()


if __name__ == "__main__":
    main()
