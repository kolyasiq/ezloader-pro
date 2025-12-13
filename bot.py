import os
import sys
import logging
import re
import asyncio
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
import yt_dlp
from dotenv import load_dotenv

# ========== НАСТРОЙКИ ДЛЯ RENDER ==========
# Проверяем что мы на Render
IS_RENDER = 'RENDER' in os.environ or 'PORT' in os.environ

if IS_RENDER:
    print("🌍 Запуск на Render...")
    # Принудительно добавляем пути к библиотекам для Render
    sys.path.append('/opt/render/.local/lib/python3.10/site-packages')
    sys.path.append('/opt/render/project/src')
    print(f"✅ Пути к библиотекам добавлены")
else:
    print("💻 Локальный запуск")

# Загружаем токен (сначала из .env, потом из переменных окружения Render)
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")

# Если токен не найден в .env, пробуем из переменных окружения Render
if not TOKEN:
    TOKEN = os.environ.get("TELEGRAM_TOKEN")

if not TOKEN:
    print("❌ ОШИБКА: Токен не найден!")
    print("На Render: добавьте TELEGRAM_TOKEN в Environment Variables")
    print("Локально: создайте .env с TELEGRAM_TOKEN=ваш_токен")
    exit(1)

print(f"✅ Токен получен: {TOKEN[:10]}...")

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Хранилище для данных о видео и сообщений о проблемах
user_data = {}
report_data = {}

# ДАННЫЕ ДЛЯ ДОНАТА
DONATE_INFO = {
    'crypto_wallets': {
        'usdt_trc20': 'TRJNHP8Jf93zU5CJ24VcUmi2tFfaddTuFi',
        'btc': '1PhhyScpMtns1MJVSJd7kLbb14hYas3kEn',
        'eth_erc20': '0x33639adb258dfc28ad4892d3e2507d3f280b4608'
    },
    'author_username': '@kolyasiqq',
    'author_user_id': 'kolyasiqq',
}

# ==================== УЛУЧШЕННЫЕ ФУНКЦИИ ====================

def get_available_formats(url: str):
    """Получает РЕАЛЬНЫЕ доступные форматы видео"""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'socket_timeout': 10,
        'extract_timeout': 15,
        'ignoreerrors': True,
        'no_color': True,
        
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web'],
            }
        },
        
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            if not info:
                return None, "Не удалось получить информацию о видео"
            
            all_formats = info.get('formats', [])
            video_formats = []
            audio_formats = []
            
            for fmt in all_formats:
                if not fmt.get('filesize') and not fmt.get('filesize_approx'):
                    continue
                
                has_video = fmt.get('vcodec') != 'none'
                has_audio = fmt.get('acodec') != 'none'
                
                format_info = {
                    'format_id': fmt.get('format_id'),
                    'ext': fmt.get('ext', 'mp4'),
                    'filesize': fmt.get('filesize') or fmt.get('filesize_approx', 0),
                    'height': fmt.get('height', 0),
                    'width': fmt.get('width', 0),
                    'resolution': fmt.get('resolution', 'N/A'),
                    'format_note': fmt.get('format_note', ''),
                    'vcodec': fmt.get('vcodec'),
                    'acodec': fmt.get('acodec'),
                }
                
                if format_info['filesize']:
                    format_info['filesize_mb'] = format_info['filesize'] / (1024 * 1024)
                else:
                    format_info['filesize_mb'] = 0
                
                if format_info['filesize_mb'] > 45:
                    continue
                
                if has_video and has_audio:
                    video_formats.append(format_info)
                elif has_audio and not has_video:
                    audio_formats.append(format_info)
            
            video_formats.sort(key=lambda x: x['height'] or 0, reverse=True)
            selected_video_formats = []
            
            # 1. Лучшее качество
            best_formats = [f for f in video_formats if f['height'] <= 720]
            if best_formats:
                best = best_formats[0]
                selected_video_formats.append({
                    'format_id': best['format_id'],
                    'name': f"🎬 Лучшее качество ({best['height']}p)",
                    'description': f"{best['height']}p • {best['ext'].upper()} • ~{best['filesize_mb']:.1f}MB",
                    'height': best['height'],
                })
            
            # 2. Среднее качество
            medium_formats = [f for f in video_formats if 360 <= f['height'] <= 540]
            if medium_formats:
                medium = medium_formats[0]
                selected_video_formats.append({
                    'format_id': medium['format_id'],
                    'name': f"📹 Среднее качество ({medium['height']}p)",
                    'description': f"{medium['height']}p • {medium['ext'].upper()} • ~{medium['filesize_mb']:.1f}MB",
                    'height': medium['height'],
                })
            
            # 3. Низкое качество
            low_formats = [f for f in video_formats if f['height'] <= 360]
            if low_formats:
                low = low_formats[0]
                selected_video_formats.append({
                    'format_id': low['format_id'],
                    'name': f"⚡️ Быстрое скачивание ({low['height']}p)",
                    'description': f"{low['height']}p • {low['ext'].upper()} • ~{low['filesize_mb']:.1f}MB",
                    'height': low['height'],
                })
            
            selected_audio_formats = []
            if audio_formats:
                audio_formats.sort(key=lambda x: x['filesize'] or 0, reverse=True)
                best_audio = audio_formats[0]
                selected_audio_formats.append({
                    'format_id': best_audio['format_id'],
                    'name': "🎵 Только аудио (MP3)",
                    'description': f"MP3 • ~{best_audio['filesize_mb']:.1f}MB",
                })
            
            if not selected_video_formats:
                selected_video_formats = [
                    {
                        'format_id': 'best[height<=720][filesize<45M]',
                        'name': "🎬 Лучшее качество (до 720p)",
                        'description': "720p • MP4 • Автовыбор",
                        'height': 720,
                    },
                    {
                        'format_id': 'best[height<=480][filesize<45M]',
                        'name': "📹 Среднее качество (480p)",
                        'description': "480p • MP4 • Быстрее",
                        'height': 480,
                    },
                    {
                        'format_id': 'best[height<=360][filesize<45M]',
                        'name': "⚡️ Быстрое скачивание (360p)",
                        'description': "360p • MP4 • Очень быстро",
                        'height': 360,
                    }
                ]
            
            if not selected_audio_formats:
                selected_audio_formats.append({
                    'format_id': 'bestaudio',
                    'name': "🎵 Только аудио (MP3)",
                    'description': "MP3 • 192kbps • ~3-10MB",
                })
            
            return {
                'info': info,
                'video_formats': selected_video_formats[:3],
                'audio_formats': selected_audio_formats[:1],
                'title': info.get('title', 'Без названия')[:100],
                'duration': info.get('duration', 0),
                'thumbnail': info.get('thumbnail', ''),
                'url': url,
            }, None
            
    except Exception as e:
        error_msg = str(e)
        if "403" in error_msg or "Forbidden" in error_msg:
            return None, "YouTube временно блокирует скачивание. Попробуйте через 10 минут или другую ссылку."
        elif "Unsupported URL" in error_msg:
            return None, "Неподдерживаемая ссылка."
        else:
            return None, f"Ошибка анализа: {error_msg[:100]}"

def download_selected_format(url: str, format_id: str, chat_id: str, is_audio: bool = False):
    """Скачивает выбранный формат"""
    download_dir = f"downloads/{chat_id}"
    os.makedirs(download_dir, exist_ok=True)
    
    try:
        files = os.listdir(download_dir)
        if len(files) > 3:
            files.sort(key=lambda x: os.path.getmtime(os.path.join(download_dir, x)))
            for old_file in files[:-3]:
                os.remove(os.path.join(download_dir, old_file))
    except:
        pass
    
    if is_audio:
        ydl_opts = {
            'format': 'bestaudio',
            'outtmpl': f'{download_dir}/%(title)s.%(ext)s',
            'quiet': True,
            'no_warnings': True,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'max_filesize': 45 * 1024 * 1024,
            'socket_timeout': 30,
            'retries': 3,
            'fragment_retries': 3,
            'extractor_args': {'youtube': {'player_client': ['android']}},
        }
    else:
        ydl_opts = {
            'format': format_id,
            'outtmpl': f'{download_dir}/%(title)s.%(ext)s',
            'quiet': True,
            'no_warnings': True,
            'max_filesize': 45 * 1024 * 1024,
            'socket_timeout': 30,
            'retries': 3,
            'fragment_retries': 3,
            'extractor_args': {'youtube': {'player_client': ['android']}},
        }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
            
            files = os.listdir(download_dir)
            if not files:
                return None, "Файл не был создан"
            
            files.sort(key=lambda x: os.path.getmtime(os.path.join(download_dir, x)), reverse=True)
            file_path = os.path.join(download_dir, files[0])
            
            file_size = os.path.getsize(file_path)
            if file_size > 45 * 1024 * 1024:
                os.remove(file_path)
                return None, f"Файл слишком большой ({file_size//1024//1024}MB)"
            
            return file_path, None
            
    except yt_dlp.utils.DownloadError as e:
        return None, f"Ошибка скачивания: {str(e)[:100]}"
    except Exception as e:
        return None, f"Ошибка: {str(e)[:100]}"

# ==================== TELEGRAM HANDLERS ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    keyboard = [
        [InlineKeyboardButton("❤️ Поддержать разработчика", callback_data="donate")],
        [InlineKeyboardButton("🛠 Сообщить о проблеме", callback_data="report_issue")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🎬 *ezLoader PRO v5.0*\n\n"
        "📹 *3 варианта видео + аудио:*\n"
        "• 🎬 Лучшее качество (до 720p)\n"
        "• 📹 Среднее качество (480p)\n"  
        "• ⚡️ Быстрое скачивание (360p)\n"
        "• 🎵 Только аудио MP3\n\n"
        "✨ *Новое: Возможность поддержать разработчика!*\n\n"
        "📋 *Как использовать:*\n"
        "1. Отправьте ссылку на видео\n"
        "2. Выберите формат кнопкой\n"
        "3. Получите файл за 10-60 сек\n\n"
        "✅ *Поддерживает:* YouTube, TikTok, Instagram\n"
        "⚡️ *Работает 24/7* на удаленном сервере",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

async def donate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /donate"""
    await show_donate_info(update, context)

async def show_donate_info(update: Update, context: ContextTypes.DEFAULT_TYPE, is_callback: bool = False):
    """Показывает информацию о донате с крипто-кошельками"""
    keyboard = [
        [InlineKeyboardButton("🔙 Назад в главное меню", callback_data="back_to_start")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = (
        "❤️ *Поддержать разработчика*\n\n"
        "Бот работает абсолютно бесплатно, если хотите поддержать развитие:\n\n"
        "₿ *Crypto ₿*\n\n"
        "🔹 *USDT (TRC-20):*\n"
        f"`{DONATE_INFO['crypto_wallets']['usdt_trc20']}`\n\n"
        "🔹 *Bitcoin (BTC):*\n"
        f"`{DONATE_INFO['crypto_wallets']['btc']}`\n\n"
        "🔹 *Ethereum (ERC-20):*\n"
        f"`{DONATE_INFO['crypto_wallets']['eth_erc20']}`\n\n"
        "💎 *За донат:*\n"
        "• Приоритетная поддержка\n"
        "• Искренняя благодарность!"
    )
    
    if is_callback:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(text, parse_mode='Markdown', reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, parse_mode='Markdown', reply_markup=reply_markup)

async def report_issue_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /report - начинает процесс отправки отчета"""
    chat_id = str(update.message.chat.id)
    
    # Сохраняем состояние "ожидаем описание проблемы"
    report_data[chat_id] = {
        'step': 'waiting_description',
        'messages': []
    }
    
    keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data="cancel_report")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🛠 *Сообщить о проблеме*\n\n"
        "Опишите проблему подробно:\n\n"
        "1. Что произошло?\n"
        "2. Какая ссылка не работает? (если есть)\n"
        "3. Какая ошибка появляется?\n\n"
        "📝 *Просто напишите сообщение с описанием проблемы*",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

async def handle_report_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает сообщения в режиме отчетов"""
    chat_id = str(update.message.chat.id)
    
    if chat_id not in report_data:
        # Не в режиме отчета, обрабатываем как обычно
        # Вместо вызова handle_message, создадим общий обработчик
        return await handle_text_message(update, context)
    
    report_info = report_data[chat_id]
    
    if report_info['step'] == 'waiting_description':
        # Сохраняем описание проблемы
        report_info['description'] = update.message.text
        report_info['step'] = 'waiting_confirmation'
        report_info['user_id'] = update.message.from_user.id
        report_info['username'] = update.message.from_user.username or f"id{update.message.from_user.id}"
        
        keyboard = [
            [InlineKeyboardButton("✅ Отправить отчет", callback_data="send_report")],
            [InlineKeyboardButton("❌ Отмена", callback_data="cancel_report")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "📋 *Ваш отчет:*\n\n"
            f"*Описание:*\n{update.message.text[:500]}\n\n"
            f"*От:* @{report_info['username']} (ID: {report_info['user_id']})\n\n"
            "✅ *Отправить отчет разработчику?*",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    
    elif report_info['step'] == 'waiting_url':
        # Сохраняем ссылку
        report_info['problem_url'] = update.message.text
        
        keyboard = [
            [InlineKeyboardButton("✅ Отправить отчет", callback_data="send_report")],
            [InlineKeyboardButton("❌ Отмена", callback_data="cancel_report")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"✅ Ссылка сохранена: {update.message.text[:100]}\n\n"
            "📋 *Ваш отчет:*\n\n"
            f"*Описание:*\n{report_info['description'][:300]}\n\n"
            f"*Проблемная ссылка:*\n{update.message.text}\n\n"
            f"*От:* @{report_info['username']} (ID: {report_info['user_id']})\n\n"
            "✅ *Отправить отчет разработчику?*",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ВСЕХ текстовых сообщений (ссылки, команды, и т.д.)"""
    message_text = update.message.text.strip()
    chat_id = str(update.message.chat.id)
    
    # Если сообщение похоже на команду доната
    if message_text.lower() in ['донат', 'donate', 'поддержать', 'оплата']:
        await donate_command(update, context)
        return
    
    # Если сообщение о проблеме
    if message_text.lower() in ['ошибка', 'баг', 'проблема', 'report', 'bug']:
        await report_issue_command(update, context)
        return
    
    # Проверяем URL
    url_pattern = r'https?://(?:www\.)?(?:youtube\.com|youtu\.be|tiktok\.com|instagram\.com).+'
    
    if not re.match(url_pattern, message_text):
        await update.message.reply_text(
            "❌ *Это не ссылка на видео!*\n\n"
            "Отправьте ссылку или команду:\n"
            "/donate - поддержать разработчика\n"
            "/report - сообщить о проблеме",
            parse_mode='Markdown'
        )
        return
    
    # Отправляем статус
    status_msg = await update.message.reply_text(
        "🔍 *Анализирую ссылку...*\n"
        "Определяю доступные форматы...",
        parse_mode='Markdown'
    )
    
    # Получаем доступные форматы
    video_info, error = get_available_formats(message_text)
    
    if error:
        await status_msg.edit_text(f"❌ *Ошибка:*\n`{error}`", parse_mode='Markdown')
        return
    
    # Сохраняем данные
    user_data[chat_id] = {
        'url': message_text,
        'info': video_info,
    }
    
    # Создаем клавиатуру с кнопками
    keyboard = []
    
    # Добавляем ВИДЕО форматы (3 варианта)
    for i, fmt in enumerate(video_info['video_formats']):
        keyboard.append([
            InlineKeyboardButton(
                fmt['name'],
                callback_data=f"video_{fmt['format_id']}_{i}"
            )
        ])
    
    # Добавляем АУДИО формат
    if video_info['audio_formats']:
        audio_fmt = video_info['audio_formats'][0]
        keyboard.append([
            InlineKeyboardButton(
                audio_fmt['name'],
                callback_data=f"audio_{audio_fmt['format_id']}_0"
            )
        ])
    
    # Кнопка доната (только иногда, чтобы не надоедала)
    if random.random() < 0.3:  # 30% chance to show donate button
        keyboard.append([InlineKeyboardButton("❤️ Поддержать разработчика", callback_data="donate")])
    
    # Кнопка отмены
    keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Обновляем сообщение
    title = video_info['title']
    duration = video_info['duration']
    mins = duration // 60
    secs = duration % 60
    
    message_text = (
        f"✅ *{title}*\n"
        f"⏱️ Длительность: {mins}:{secs:02d}\n\n"
        f"🎛️ *Выберите формат для скачивания:*\n\n"
        f"📹 *Видео:*\n"
        + "\n".join([f"• {fmt['description']}" for fmt in video_info['video_formats']])
    )
    
    if video_info['audio_formats']:
        message_text += f"\n\n🎵 *Аудио:*\n• {video_info['audio_formats'][0]['description']}"
    
    # Иногда добавляем предложение поддержать
    if random.random() < 0.2:  # 20% chance
        message_text += "\n\n✨ *Бот бесплатный!* Если нравится — поддержите разработчика ❤️"
    
    await status_msg.edit_text(
        message_text,
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик нажатий на кнопки"""
    query = update.callback_query
    await query.answer()
    
    chat_id = str(query.message.chat.id)
    data = query.data
    
    # Команда /donate - сразу показываем крипто-кошельки
    if data == "donate":
        await show_donate_info(update, context, is_callback=True)
        return
    
    # Начать отправку отчета
    elif data == "report_issue":
        await query.edit_message_text(
            "🛠 *Сообщить о проблеме*\n\n"
            "Опишите проблему подробно:\n\n"
            "1. Что произошло?\n"
            "2. Какая ссылка не работает? (если есть)\n"
            "3. Какая ошибка появляется?\n\n"
            "📝 *Просто напишите сообщение с описанием проблемы*",
            parse_mode='Markdown'
        )
        
        # Сохраняем состояние "ожидаем описание проблемы"
        report_data[chat_id] = {
            'step': 'waiting_description',
            'messages': [],
            'user_id': query.from_user.id,
            'username': query.from_user.username or f"id{query.from_user.id}"
        }
        return
    
    # Отправить отчет разработчику
    elif data == "send_report":
        if chat_id not in report_data:
            await query.answer("❌ Нет данных отчета")
            return
        
        report_info = report_data[chat_id]
        
        try:
            # Формируем сообщение для разработчика
            report_message = (
                f"🛠 *НОВЫЙ ОТЧЕТ О ПРОБЛЕМЕ*\n\n"
                f"*От:* @{report_info['username']}\n"
                f"*ID пользователя:* {report_info['user_id']}\n"
                f"*ID чата:* {chat_id}\n\n"
                f"*Описание проблемы:*\n{report_info['description']}\n"
            )
            
            if 'problem_url' in report_info:
                report_message += f"\n*Проблемная ссылка:*\n{report_info['problem_url']}"
            
            # Пытаемся отправить сообщение разработчику
            try:
                # Отправляем через бота (если у разработчика есть username)
                await context.bot.send_message(
                    chat_id=DONATE_INFO['author_username'],
                    text=report_message,
                    parse_mode='Markdown'
                )
                success = True
            except:
                # Если не получилось отправить по username, просто логируем
                print(f"📨 ОТЧЕТ ОТ {report_info['username']}: {report_info['description'][:100]}")
                success = True
            
            # Удаляем данные отчета
            if chat_id in report_data:
                del report_data[chat_id]
            
            if success:
                await query.edit_message_text(
                    "✅ *Отчет успешно отправлен!*\n\n"
                    "Спасибо за обратную связь! Разработчик получил ваше сообщение и рассмотрит проблему в ближайшее время.\n\n"
                    "✉️ *Контакты разработчика:* @kolyasiqq\n\n"
                    "Для возврата в главное меню отправьте /start",
                    parse_mode='Markdown'
                )
            else:
                await query.edit_message_text(
                    "⚠️ *Не удалось отправить отчет автоматически*\n\n"
                    "Пожалуйста, напишите разработчику напрямую:\n"
                    "✉️ @kolyasiqq\n\n"
                    "Скопируйте описание проблемы:\n"
                    f"`{report_info['description'][:300]}`",
                    parse_mode='Markdown'
                )
                
        except Exception as e:
            await query.edit_message_text(
                f"❌ *Ошибка отправки:* {str(e)[:100]}\n\n"
                "Напишите разработчику напрямую: @kolyasiqq",
                parse_mode='Markdown'
            )
        return
    
    # Отмена отчета
    elif data == "cancel_report":
        if chat_id in report_data:
            del report_data[chat_id]
        
        keyboard = [
            [InlineKeyboardButton("❤️ Поддержать разработчика", callback_data="donate")],
            [InlineKeyboardButton("🛠 Сообщить о проблеме", callback_data="report_issue")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "🎬 *ezLoader PRO v5.0*\n\n"
            "📹 *3 варианта видео + аудио:*\n"
            "• 🎬 Лучшее качество (до 720p)\n"
            "• 📹 Среднее качество (480p)\n"  
            "• ⚡️ Быстрое скачивание (360p)\n"
            "• 🎵 Только аудио MP3\n\n"
            "✨ *Новое: Возможность поддержать разработчика!*\n\n"
            "📋 *Как использовать:*\n"
            "1. Отправьте ссылку на видео\n"
            "2. Выберите формат кнопкой\n"
            "3. Получите файл за 10-60 сек\n\n"
            "✅ *Поддерживает:* YouTube, TikTok, Instagram\n"
            "⚡️ *Работает 24/7* на удаленном сервере",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        return
    
    # Назад в главное меню
    elif data == "back_to_start":
        keyboard = [
            [InlineKeyboardButton("❤️ Поддержать разработчика", callback_data="donate")],
            [InlineKeyboardButton("🛠 Сообщить о проблеме", callback_data="report_issue")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "🎬 *ezLoader PRO v5.0*\n\n"
            "📹 *3 варианта видео + аудио:*\n"
            "• 🎬 Лучшее качество (до 720p)\n"
            "• 📹 Среднее качество (480p)\n"  
            "• ⚡️ Быстрое скачивание (360p)\n"
            "• 🎵 Только аудио MP3\n\n"
            "✨ *Новое: Возможность поддержать разработчика!*\n\n"
            "📋 *Как использовать:*\n"
            "1. Отправьте ссылку на видео\n"
            "2. Выберите формат кнопкой\n"
            "3. Получите файл за 10-60 сек\n\n"
            "✅ *Поддерживает:* YouTube, TikTok, Instagram\n"
            "⚡️ *Работает 24/7* на удаленном сервере",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        return
    
    # Отмена скачивания
    elif data == "cancel":
        await query.edit_message_text("✅ Выбор отменен. Отправьте новую ссылку если нужно.")
        if chat_id in user_data:
            del user_data[chat_id]
        return
    
    # Скачивание видео/аудио
    elif data.startswith("video_") or data.startswith("audio_"):
        await handle_download_callback(query, data, chat_id)
        return
    
    # Неизвестная команда
    else:
        await query.edit_message_text("❌ Неизвестная команда")
        return

async def handle_download_callback(query, data: str, chat_id: str):
    """Обрабатывает callback скачивания"""
    # Получаем сохраненные данные
    user_info = user_data.get(chat_id)
    if not user_info:
        await query.edit_message_text("❌ Данные устарели. Отправьте ссылку заново.")
        return
    
    # Определяем тип скачивания
    if data.startswith("video_"):
        parts = data.split("_")
        format_id = parts[1]
        format_index = int(parts[2])
        
        format_info = user_info['info']['video_formats'][format_index]
        format_name = format_info['name']
        
        await query.edit_message_text(
            f"⏳ *{format_name}*\n"
            f"Скачиваю видео...\n"
            f"Это займет 10-60 секунд",
            parse_mode='Markdown'
        )
        
        is_audio = False
        
    elif data.startswith("audio_"):
        parts = data.split("_")
        format_id = parts[1]
        
        await query.edit_message_text(
            f"⏳ *Скачиваю аудио MP3...*\n"
            f"Конвертирую в MP3...\n"
            f"Это займет 10-30 секунд",
            parse_mode='Markdown'
        )
        
        is_audio = True
    
    # Скачиваем выбранный формат
    file_path, error = download_selected_format(
        user_info['url'], 
        format_id, 
        chat_id, 
        is_audio
    )
    
    if error:
        await query.edit_message_text(
            f"❌ *Ошибка скачивания:*\n`{error}`\n\n"
            f"Попробуйте другой формат или ссылку\n"
            f"Или сообщите о проблеме: /report",
            parse_mode='Markdown'
        )
        return
    
    # Отправляем файл
    try:
        file_size = os.path.getsize(file_path) / (1024 * 1024)
        
        if is_audio:
            with open(file_path, 'rb') as audio_file:
                await query.message.reply_audio(
                    audio=audio_file,
                    caption=(
                        f"🎵 {user_info['info']['title'][:50]}\n"
                        f"📦 Размер: {file_size:.1f}MB\n"
                        f"📥 @ezloader_pro_bot\n\n"
                        f"❤️ Бот бесплатный! Поддержать разработчика: /donate"
                    ),
                    duration=user_info['info']['duration']
                )
        else:
            with open(file_path, 'rb') as video_file:
                await query.message.reply_video(
                    video=video_file,
                caption=(
                    f"🎬 {user_info['info']['title'][:50]}\n"
                    f"📦 Размер: {file_size:.1f}MB\n"
                    f"📥 @ezloader_pro_bot\n\n"
                    f"✨ Нравится бот? Поддержите разработчика! /donate"
                ),