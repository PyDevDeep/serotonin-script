SLACK_UI = {
    # Success Notifications
    "draft_ready_fallback": "✅ Драфт готовий: {topic}",
    "draft_ready_header": "📝 Новий драфт: {topic}",
    "ordered_by": "👤 Замовлено: <@{user_id}>",
    "btn_publish": "Опублікувати",
    "btn_reject": "Відхилити",
    # Error Notifications
    "error_fallback": "❌ Помилка задачі: {topic}",
    "error_header": "🚨 Сталася помилка",
    "error_details": "*Тема/Задача:* {topic}\n*Замовник:* <@{user_id}>\n\n*Деталі помилки:*\n```{error_msg}```",
    # --- НОВІ КЛЮЧІ: Slash Commands ---
    "cmd_unknown": "Невідома команда.",
    "cmd_missing_args": "Вкажіть тему та платформу. Формат: `/draft Тема | платформа`\nНаприклад: `/draft Тривога і кава | telegram`",
    "cmd_invalid_platform": "Невідома платформа '{platform}'. Доступні: {valid_platforms}",
    "cmd_accepted": "⏳ Прийнято в роботу! Починаю RAG-пошук та генерацію на тему: *{topic}* для {platform}...",
}
