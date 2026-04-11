import os
import json
import logging
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

# Пользователи, которые сейчас общаются с оператором
# {user_id: True}
operator_sessions = {}


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


def back_keyboard():
    kb = VkKeyboard(one_time=False)
    kb.add_button("⬅ Назад в меню", color=VkKeyboardColor.SECONDARY)
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


# ── Обработка сообщений ──────────────────────────────────────

def handle_message(vk, user_id, text):
    lower = text.lower().strip()

    # --- Выход из режима оператора ---
    if lower in ("⬅ назад в меню", "назад в меню", "/menu", "/start"):
        operator_sessions.pop(user_id, None)
        send(vk, user_id,
             "🏠 Главное меню Atlas Secure | Поддержка\n\n"
             "Выберите действие:",
             main_keyboard())
        return

    # --- Режим оператора: пересылка сообщений ---
    if user_id in operator_sessions:
        if ADMIN_ID == 0:
            send(vk, user_id,
                 "⚠ Оператор временно недоступен. Попробуйте позже.",
                 back_keyboard())
            return
        # Пересылаем сообщение админу
        send(vk, ADMIN_ID,
             f"📩 Сообщение от пользователя [id{user_id}|#{user_id}]:\n\n{text}")
        send(vk, user_id,
             "✅ Сообщение отправлено оператору. Ожидайте ответа.\n\n"
             "Продолжайте писать — все сообщения будут переданы.",
             back_keyboard())
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
        operator_sessions[user_id] = True
        send(vk, user_id,
             "👨‍💻 Вы подключены к оператору.\n\n"
             "Напишите ваш вопрос — мы передадим его нашему специалисту.\n"
             "Для возврата в меню нажмите «⬅ Назад в меню».",
             back_keyboard())
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


# ── Ответы админа пользователям ──────────────────────────────

def handle_admin_reply(vk, text):
    """Админ отвечает формата: #ID сообщение"""
    if not text.startswith("#"):
        return False
    parts = text.split(" ", 1)
    if len(parts) < 2:
        return False
    try:
        target_id = int(parts[0][1:])
    except ValueError:
        return False
    reply_text = parts[1]
    send(vk, target_id,
         f"💬 Ответ оператора:\n\n{reply_text}",
         back_keyboard())
    send(vk, ADMIN_ID, f"✅ Ответ доставлен пользователю #{target_id}.")
    return True


# ── Запуск бота ──────────────────────────────────────────────

def main():
    if not VK_TOKEN:
        log.error("VK_TOKEN не задан в .env!")
        return

    vk_session = vk_api.VkApi(token=VK_TOKEN)
    vk = vk_session.get_api()

    # Получаем ID группы
    group_info = vk.groups.getById()
    group_id = group_info[0]["id"]
    log.info("Бот запущен! Группа ID: %s", group_id)

    if ADMIN_ID == 0:
        log.warning(
            "ADMIN_ID не задан! Функция оператора не будет работать. "
            "Укажите ваш VK ID в .env файле."
        )

    longpoll = VkBotLongPoll(vk_session, group_id)

    for event in longpoll.listen():
        if event.type == VkBotEventType.MESSAGE_NEW:
            msg = event.obj.message
            user_id = msg["from_id"]
            text = msg.get("text", "")

            if not text:
                continue

            log.info("Сообщение от %s: %s", user_id, text)

            # Если пишет админ — проверяем, не ответ ли это пользователю
            if user_id == ADMIN_ID and handle_admin_reply(vk, text):
                continue

            handle_message(vk, user_id, text)


if __name__ == "__main__":
    main()
