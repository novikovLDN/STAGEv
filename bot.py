import os
import time
import logging
import requests
from dotenv import load_dotenv
import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
from vk_api.keyboard import VkKeyboard, VkKeyboardColor

from faq import FAQ

load_dotenv()

VK_TOKEN = os.getenv("VK_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("atlas-support")

# {user_id: True} — пользователи в режиме оператора
user_sessions = {}

# ID пользователя, с которым админ сейчас ведёт диалог (или None)
admin_chat_with = None


# ── Клавиатуры ────────────────────────────────────────────────

def main_keyboard():
    kb = VkKeyboard(one_time=False)
    kb.add_button("❓ FAQ", color=VkKeyboardColor.PRIMARY)
    kb.add_button("👨‍💻 Оператор", color=VkKeyboardColor.POSITIVE)
    return kb.get_keyboard()


def faq_keyboard():
    kb = VkKeyboard(one_time=False)
    for key, item in FAQ.items():
        kb.add_button(item["question"], color=VkKeyboardColor.PRIMARY)
        kb.add_line()
    kb.add_button("⬅ Назад", color=VkKeyboardColor.SECONDARY)
    return kb.get_keyboard()


def user_operator_keyboard():
    kb = VkKeyboard(one_time=False)
    kb.add_button("❌ Завершить чат", color=VkKeyboardColor.NEGATIVE)
    return kb.get_keyboard()


def admin_keyboard():
    kb = VkKeyboard(one_time=False)
    kb.add_button("/chats", color=VkKeyboardColor.PRIMARY)
    kb.add_button("/close", color=VkKeyboardColor.NEGATIVE)
    kb.add_line()
    kb.add_button("/help", color=VkKeyboardColor.SECONDARY)
    return kb.get_keyboard()


def admin_empty_keyboard():
    kb = VkKeyboard(one_time=False)
    kb.add_button("/chats", color=VkKeyboardColor.PRIMARY)
    kb.add_button("/help", color=VkKeyboardColor.SECONDARY)
    return kb.get_keyboard()


# ── Отправка сообщений ────────────────────────────────────────

def send(vk, user_id, message, keyboard=None):
    params = {
        "user_id": user_id,
        "message": message,
        "random_id": vk_api.utils.get_random_id(),
    }
    if keyboard:
        params["keyboard"] = keyboard
    vk.messages.send(**params)


# ── Админ-команды ─────────────────────────────────────────────

def handle_admin(vk, text):
    """Обработка сообщений от админа. Возвращает True если обработано."""
    global admin_chat_with
    lower = text.strip().lower()

    # /help — подсказка для админа
    if lower == "/help":
        send(vk, ADMIN_ID,
             "📖 Команды оператора:\n\n"
             "👥 Управление чатами:\n"
             "/chats — список активных чатов\n"
             "/chat ID — подключиться к пользователю\n"
             "/close — завершить текущий чат\n"
             "/close ID — завершить конкретный чат\n\n"
             "💬 Ответы пользователям:\n"
             "1. /chat ID → потом просто пишете текст\n"
             "2. #ID текст — быстрый ответ без подключения\n\n"
             "📌 Как это работает:\n"
             "• Пользователь нажимает «Оператор» → вам приходит 🟢\n"
             "• Вы пишете /chat ID → подключаетесь к диалогу\n"
             "• Пишете сообщения — они уходят пользователю\n"
             "• Когда решили вопрос — /close\n"
             "• Пользователь получит уведомление о закрытии",
             admin_empty_keyboard())
        return True

    # /chats — список активных чатов
    if lower == "/chats":
        if not user_sessions:
            send(vk, ADMIN_ID,
                 "📭 Нет активных чатов.",
                 admin_empty_keyboard())
            return True
        lines = ["📋 Активные чаты:\n"]
        for uid in user_sessions:
            marker = " ← текущий" if uid == admin_chat_with else ""
            lines.append(f"• [id{uid}|#{uid}]{marker}")
        lines.append(f"\nВсего: {len(user_sessions)}")
        lines.append("\n/chat ID — подключиться к чату")
        lines.append("/close — завершить текущий чат")
        send(vk, ADMIN_ID, "\n".join(lines), admin_keyboard())
        return True

    # /chat ID — подключиться к конкретному пользователю
    if lower.startswith("/chat "):
        parts = text.strip().split(" ", 1)
        try:
            target_id = int(parts[1])
        except (ValueError, IndexError):
            send(vk, ADMIN_ID, "⚠ Формат: /chat ID_пользователя")
            return True
        if target_id not in user_sessions:
            send(vk, ADMIN_ID,
                 f"⚠ Пользователь #{target_id} не в режиме оператора.\n"
                 f"Активные чаты: /chats")
            return True
        admin_chat_with = target_id
        send(vk, ADMIN_ID,
             f"💬 Вы подключились к чату с [id{target_id}|#{target_id}].\n\n"
             f"Теперь просто пишите сообщения — они уйдут пользователю.\n"
             f"/close — завершить чат",
             admin_keyboard())
        return True

    # /close — завершить текущий чат или /close ID
    if lower.startswith("/close"):
        parts = text.strip().split(" ", 1)
        if len(parts) == 2:
            try:
                target_id = int(parts[1])
            except ValueError:
                send(vk, ADMIN_ID, "⚠ Формат: /close или /close ID")
                return True
        elif admin_chat_with:
            target_id = admin_chat_with
        else:
            send(vk, ADMIN_ID,
                 "⚠ Нет активного чата. Укажите ID: /close 123456",
                 admin_empty_keyboard())
            return True

        if target_id in user_sessions:
            user_sessions.pop(target_id)
            send(vk, target_id,
                 "✅ Чат с оператором завершён.\n\n"
                 "Спасибо за обращение! Если возникнут вопросы — "
                 "мы всегда на связи.",
                 main_keyboard())
        if admin_chat_with == target_id:
            admin_chat_with = None
        send(vk, ADMIN_ID,
             f"✅ Чат с #{target_id} завершён.",
             admin_empty_keyboard())
        return True

    # #ID текст — быстрый ответ конкретному пользователю
    if text.startswith("#"):
        parts = text.split(" ", 1)
        if len(parts) == 2:
            try:
                target_id = int(parts[0][1:])
                reply_text = parts[1]
                send(vk, target_id,
                     f"💬 Оператор:\n\n{reply_text}",
                     user_operator_keyboard())
                send(vk, ADMIN_ID, f"✅ → #{target_id}")
                return True
            except ValueError:
                pass

    # Если админ подключён к чату — отправить сообщение напрямую
    if admin_chat_with:
        if admin_chat_with in user_sessions:
            send(vk, admin_chat_with,
                 f"💬 Оператор:\n\n{text}",
                 user_operator_keyboard())
            send(vk, ADMIN_ID, f"✅ → #{admin_chat_with}")
            return True
        else:
            admin_chat_with = None
            send(vk, ADMIN_ID,
                 "⚠ Пользователь уже покинул чат.",
                 admin_empty_keyboard())
            return True

    return False


# ── Обработка сообщений пользователей ────────────────────────

def handle_message(vk, user_id, text):
    global admin_chat_with
    lower = text.lower().strip()

    # --- Завершить чат с оператором (пользователь) ---
    if lower in ("❌ завершить чат", "завершить чат"):
        if user_id in user_sessions:
            user_sessions.pop(user_id)
            if admin_chat_with == user_id:
                admin_chat_with = None
            send(vk, ADMIN_ID,
                 f"🔴 Пользователь [id{user_id}|#{user_id}] завершил чат.",
                 admin_empty_keyboard())
        send(vk, user_id,
             "✅ Чат с оператором завершён.\n\n"
             "Спасибо за обращение! Если возникнут вопросы — "
             "мы всегда на связи.",
             main_keyboard())
        return

    # --- Выход в меню ---
    if lower in ("⬅ назад в меню", "назад в меню", "/menu", "/start"):
        if user_id in user_sessions:
            user_sessions.pop(user_id)
            if admin_chat_with == user_id:
                admin_chat_with = None
            send(vk, ADMIN_ID,
                 f"🔴 Пользователь [id{user_id}|#{user_id}] покинул чат.",
                 admin_empty_keyboard())
        send(vk, user_id,
             "🏠 Главное меню Atlas Secure | Поддержка\n\n"
             "Выберите действие:",
             main_keyboard())
        return

    # --- Режим оператора: пересылка сообщений ---
    if user_id in user_sessions:
        if ADMIN_ID == 0:
            send(vk, user_id,
                 "⚠ Оператор временно недоступен. Попробуйте позже.",
                 user_operator_keyboard())
            return
        send(vk, ADMIN_ID,
             f"📩 [id{user_id}|#{user_id}]:\n{text}",
             admin_keyboard())
        # Если админ ещё не подключён к этому чату — подсказка
        if admin_chat_with != user_id:
            send(vk, ADMIN_ID,
                 f"💡 /chat {user_id} — подключиться и отвечать напрямую",
                 admin_keyboard())
        send(vk, user_id,
             "✅ Сообщение передано оператору.",
             user_operator_keyboard())
        return

    # --- Приветствие ---
    if lower in ("начать", "start", "/start", "привет", "здравствуйте"):
        send(vk, user_id,
             "👋 Привет! Я бот поддержки Atlas Secure.\n\n"
             "Здесь вы можете:\n"
             "• Узнать ответы на частые вопросы\n"
             "• Связаться с оператором\n\n"
             "Выберите действие:",
             main_keyboard())
        return

    # --- FAQ меню ---
    if lower in ("❓ faq", "faq", "вопросы", "❓ FAQ".lower()):
        send(vk, user_id,
             "📋 Часто задаваемые вопросы:\n\n"
             "Выберите интересующий вопрос:",
             faq_keyboard())
        return

    # --- Конкретный вопрос из FAQ ---
    for key, item in FAQ.items():
        if lower == item["question"].lower():
            send(vk, user_id, f"📌 {item['question']}\n\n{item['answer']}",
                 faq_keyboard())
            return

    # --- Связь с оператором ---
    if lower in ("👨‍💻 оператор", "оператор", "operator", "помощь", "help"):
        user_sessions[user_id] = True
        send(vk, user_id,
             "👨‍💻 Вы подключены к оператору.\n\n"
             "Напишите ваш вопрос — мы передадим его нашему специалисту.\n"
             "Среднее время ответа — до 30 минут.\n\n"
             "Нажмите «❌ Завершить чат» когда вопрос будет решён.",
             user_operator_keyboard())
        send(vk, ADMIN_ID,
             f"🟢 Новый чат! Пользователь [id{user_id}|#{user_id}] "
             f"ожидает ответа.\n\n"
             f"/chat {user_id} — подключиться к диалогу",
             admin_keyboard())
        return

    # --- Назад ---
    if lower in ("⬅ назад", "назад"):
        send(vk, user_id,
             "🏠 Главное меню Atlas Secure | Поддержка\n\n"
             "Выберите действие:",
             main_keyboard())
        return

    # --- Неизвестная команда ---
    send(vk, user_id,
         "🤔 Я не понял ваш запрос.\n\n"
         "Воспользуйтесь кнопками ниже или напишите «Оператор» "
         "для связи с поддержкой.",
         main_keyboard())


# ── Запуск бота ──────────────────────────────────────────────

def main():
    if not VK_TOKEN:
        log.error("VK_TOKEN не задан в .env!")
        return

    vk_session = vk_api.VkApi(token=VK_TOKEN)
    vk = vk_session.get_api()

    group_info = vk.groups.getById()
    group_id = group_info[0]["id"]
    log.info("Бот запущен! Группа ID: %s", group_id)

    if ADMIN_ID == 0:
        log.warning(
            "ADMIN_ID не задан! Функция оператора не будет работать. "
            "Укажите ваш VK ID в .env файле."
        )

    longpoll = VkBotLongPoll(vk_session, group_id, wait=25)

    while True:
        try:
            for event in longpoll.listen():
                if event.type == VkBotEventType.MESSAGE_NEW:
                    msg = event.obj.message
                    user_id = msg["from_id"]
                    text = msg.get("text", "")

                    if not text:
                        continue

                    log.info("Сообщение от %s: %s", user_id, text)

                    # Сообщения от админа
                    if user_id == ADMIN_ID:
                        if handle_admin(vk, text):
                            continue

                    handle_message(vk, user_id, text)
        except (requests.exceptions.ReadTimeout,
                requests.exceptions.ConnectionError,
                requests.exceptions.ChunkedEncodingError) as e:
            log.warning("Сетевая ошибка long poll: %s. Переподключение...", e)
            time.sleep(3)
        except Exception as e:
            log.exception("Неожиданная ошибка в long poll: %s", e)
            time.sleep(5)


if __name__ == "__main__":
    main()
