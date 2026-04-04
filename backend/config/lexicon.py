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
    # --- Slash Commands ---
    "cmd_unknown": "Невідома команда.",
    "cmd_missing_args": "Вкажіть тему та платформу. Формат: `/draft Тема | платформа`\nНаприклад: `/draft Тривога і кава | telegram`",
    "cmd_invalid_platform": "Невідома платформа '{platform}'. Доступні: {valid_platforms}",
    "cmd_accepted": "⏳ Прийнято в роботу! Починаю RAG-пошук та генерацію на тему: *{topic}* для {platform}...",
    # --- Interactions ---
    "interact_approved_text": "✅ Драфт схвалено!",
    "interact_approved_section": "✅ *Опубліковано!*\nДрафт відправлено в чергу на публікацію.",
    "interact_rejected_text": "❌ Драфт відхилено.",
    "interact_rejected_section": "❌ *Відхилено!*\nЦей варіант видалено. Можете спробувати іншу тему.",
    # --- Draft Card ---
    "btn_edit": "Редагувати",
    "btn_regenerate": "Перегенерувати",
    "fact_check_ok": "✅ Fact-check: Пройдено",
    "fact_check_failed": "❌ Fact-check: Провалено",
    "validation_failed_header": "⚠️ Валідацію не пройдено | 📢 {platform}",
    "validation_failed_warning": "🚨 *LLM-as-a-Judge забракував цей текст (галюцинації або стиль).* Ось найкращий згенерований варіант. Ви можете відредагувати його вручну або перегенерувати.",
    "fact_check_sources": "📚 Джерела: PubMed",
    # --- Modal ---
    "modal_title": "Редагування посту",
    "modal_submit": "Зберегти",
    "modal_cancel": "Скасувати",
    "modal_input_label": "Текст публікації",
    "modal_platform_label": "Платформа",
    "interact_regenerate_text": "⏳ Перегенерація...",
    "interact_regenerate_section": "⏳ *Перегенерація...*\nНовий варіант скоро з'явиться.",
    # --- Generation Modal ---
    "gen_modal_title": "Нова генерація",
    "gen_modal_submit": "Згенерувати",
    "gen_modal_topic_label": "Про що напишемо?",
    "gen_modal_topic_placeholder": "Наприклад: Вплив кави на тривожність",
    "gen_modal_platform_label": "Оберіть платформу",
    # --- App Home ---
    "home_welcome": "Вітаю у Seratonin Script! 🧠",
    "home_description": "Це твій центр керування медичним контентом. Натисни кнопку нижче, щоб почати.",
    "home_btn_create": "✨ Створити новий пост",
    "home_btn_upload": "📚 Завантажити гайдлайн",
    "home_drafts_header": "🗓 Останні драфти",
    "home_drafts_empty": "_Поки що немає жодного драфту._",
    "home_draft_card_text": "*{topic}*\nПлатформа: *{platform}* | Статус: {status_emoji} `{status}`",
    "home_draft_open_btn": "📝 Відкрити",
    # --- Upload Modal ---
    "upload_modal_title": "База знань",
    "upload_modal_submit": "Завантажити",
    "upload_modal_input_label": "Оберіть файл (PDF/TXT)",
    # --- Upload Notifications ---
    "upload_success": "✅ Гайдлайн *{file_name}* успішно завантажено та векторизовано у базу знань!",
    "upload_failure": "❌ *Помилка* обробки гайдлайну *{file_name}*.\n\nДеталі:\n```{error_msg}```",
}
