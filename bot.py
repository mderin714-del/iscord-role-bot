import os
import sys
import time
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from config import DISCORD_TOKEN
from database import db
from views import (
    AdminPanelView,
    PersistentRedeemView,
    generate_random_code,
    format_timestamp
)

# Настройка намерений (Intents)
intents = discord.Intents.default()
intents.members = True # Для выдачи ролей и информации об участниках

class RoleCodeBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        # 1. Инициализация базы данных
        await db.init_db()
        print("База данных SQLite успешно инициализирована.")

        # 2. Регистрация постоянных кнопок (для работы после перезапуска)
        self.add_view(PersistentRedeemView())
        print("Постоянный виджет активации зарегистрирован.")

bot = RoleCodeBot()

@bot.event
async def on_ready():
    print("=" * 50)
    print(f"Бот успешно запущен как: {bot.user.name} (ID: {bot.user.id})")
    print("Синхронизация слэш-команд...")
    try:
        synced = await bot.tree.sync()
        print(f"Успешно синхронизировано {len(synced)} слэш-команд(ы) глобально.")
    except Exception as e:
        print(f"Ошибка при синхронизации команд: {e}")
    print("=" * 50)
    print("Бот готов к работе!")


# ==========================================
# СЛЭШ-КОМАНДЫ: АДМИНИСТРИРОВАНИЕ
# ==========================================

@bot.tree.command(name="panel", description="Админ-панель генерации кодов верификации (только для администраторов)")
@app_commands.default_permissions(administrator=True)
async def panel_command(interaction: discord.Interaction):
    """Интерактивная админ-панель для создания кодов верификации"""
    if not interaction.user.guild_permissions.administrator and not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message("❌ У вас нет прав администратора для доступа к этой панели.", ephemeral=True)
        return

    embed = discord.Embed(
        title="⚙️ Панель генерации кодов верификации",
        description=(
            "Здесь вы можете генерировать коды доступа для участников сервера, "
            "просматривать активные коды, а также выставить сообщение с кнопкой **Verify** в канал верификации.\n\n"
            "Нажмите нужную кнопку ниже:"
        ),
        color=discord.Color.gold()
    )
    embed.add_field(name="➕ Создать код", value="Генерация кода (формата `XXXXXX`) с привязкой к роли", inline=True)
    embed.add_field(name="📋 Список кодов", value="Просмотр базы активных кодов и статистики", inline=True)
    embed.add_field(name="📢 Кнопка Verify", value="Разместить блок верификации в публичный канал", inline=True)

    await interaction.response.send_message(embed=embed, view=AdminPanelView(), ephemeral=True)


@bot.tree.command(name="admin_panel", description="Открыть панель управления кодами доступа (алиас /panel)")
@app_commands.default_permissions(administrator=True)
async def admin_panel_alias(interaction: discord.Interaction):
    await panel_command(interaction)


@bot.tree.command(name="code_create", description="Быстрое создание нового кода доступа для роли")
@app_commands.describe(
    role="Роль, которая будет выдаваться при вводе кода",
    uses="Количество использований (1 по умолчанию, 0 = бесконечно)",
    expires_hours="Срок действия кода в часах (0 = бессрочно)",
    custom_code="Свой вариант кода (если оставить пустым, сгенерируется красивый случайный)",
    note="Заметка/комментарий для администраторов (необязательно)"
)
@app_commands.default_permissions(administrator=True)
async def code_create(
    interaction: discord.Interaction,
    role: discord.Role,
    uses: int = 1,
    expires_hours: int = 0,
    custom_code: Optional[str] = None,
    note: Optional[str] = None
):
    if not interaction.user.guild_permissions.administrator and not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message("❌ У вас нет прав для выполнения этой команды.", ephemeral=True)
        return

    if role.is_default():
        await interaction.response.send_message("❌ Нельзя привязать код к роли @everyone.", ephemeral=True)
        return

    # Проверка позиции роли бота
    bot_member = interaction.guild.me
    if bot_member.top_role <= role:
        await interaction.response.send_message(
            f"⚠️ Внимание: роль бота ниже роли {role.mention}. "
            "Бот не сможет выдать её участникам, пока вы не поднимете роль бота выше в настройках сервера.",
            ephemeral=True
        )

    if uses < 0:
        await interaction.response.send_message("❌ Количество использований должно быть >= 0.", ephemeral=True)
        return

    if expires_hours < 0:
        await interaction.response.send_message("❌ Срок действия должен быть >= 0 часов.", ephemeral=True)
        return

    code_str = custom_code.strip().upper() if custom_code else generate_random_code()
    expires_at = int(time.time() + expires_hours * 3600) if expires_hours > 0 else None

    success, msg = await db.create_code(
        code=code_str,
        guild_id=interaction.guild.id,
        role_id=role.id,
        max_uses=uses,
        expires_at=expires_at,
        created_by=interaction.user.id,
        note=note or ""
    )

    if not success:
        await interaction.response.send_message(f"❌ {msg}", ephemeral=True)
        return

    embed = discord.Embed(
        title="✅ Код доступа успешно создан!",
        color=discord.Color.green()
    )
    embed.add_field(name="🔑 Код", value=f"```\n{code_str}\n```", inline=False)
    embed.add_field(name="🎭 Роль", value=role.mention, inline=True)
    embed.add_field(name="🔢 Активаций", value="Бесконечно" if uses == 0 else f"{uses} раз", inline=True)
    embed.add_field(name="⏳ Срок действия", value=format_timestamp(expires_at), inline=True)
    if note:
        embed.add_field(name="📝 Заметка", value=note, inline=False)

    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="code_list", description="Показать список всех промокодов сервера")
@app_commands.default_permissions(administrator=True)
async def code_list(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator and not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message("❌ У вас нет прав для выполнения этой команды.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    codes = await db.list_codes(interaction.guild.id, limit=30)

    if not codes:
        await interaction.followup.send("ℹ️ На этом сервере пока нет созданных кодов.", ephemeral=True)
        return

    embed = discord.Embed(
        title=f"📋 Коды доступа сервера ({len(codes)})",
        color=discord.Color.blue()
    )

    now = int(time.time())
    for c in codes:
        role = interaction.guild.get_role(c["role_id"])
        role_name = role.mention if role else f"ID: {c['role_id']} (Удалена)"

        if not c["is_active"]:
            status = "🔴 Отключен"
        elif c["expires_at"] and now > c["expires_at"]:
            status = "⏳ Истёк"
        elif c["max_uses"] > 0 and c["used_count"] >= c["max_uses"]:
            status = "🚫 Исчерпан"
        else:
            status = "🟢 Активен"

        max_u = "∞" if c["max_uses"] == 0 else str(c["max_uses"])
        uses_str = f"{c['used_count']}/{max_u}"
        exp_str = format_timestamp(c["expires_at"])
        note_str = f" | *{c['note']}*" if c["note"] else ""

        embed.add_field(
            name=f"`{c['code']}` — {status}",
            value=f"Роль: {role_name}\nИспользовано: **{uses_str}**\nСрок: {exp_str}{note_str}",
            inline=False
        )

    await interaction.followup.send(embed=embed, ephemeral=True)


@bot.tree.command(name="code_revoke", description="Деактивировать промокод")
@app_commands.describe(code="Код, который необходимо отозвать")
@app_commands.default_permissions(administrator=True)
async def code_revoke(interaction: discord.Interaction, code: str):
    if not interaction.user.guild_permissions.administrator and not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message("❌ У вас нет прав для выполнения этой команды.", ephemeral=True)
        return

    clean_code = code.strip().upper()
    success = await db.revoke_code(clean_code, interaction.guild.id)
    if success:
        await interaction.response.send_message(f"✅ Код `{clean_code}` успешно деактивирован.", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ Код `{clean_code}` не найден.", ephemeral=True)


@bot.tree.command(name="code_info", description="Подробная информация о коде и список тех, кто его активировал")
@app_commands.describe(code="Код для просмотра статистики")
@app_commands.default_permissions(administrator=True)
async def code_info(interaction: discord.Interaction, code: str):
    if not interaction.user.guild_permissions.administrator and not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message("❌ У вас нет прав для выполнения этой команды.", ephemeral=True)
        return

    clean_code = code.strip().upper()
    stats = await db.get_code_stats(clean_code, interaction.guild.id)
    if not stats:
        await interaction.response.send_message(f"❌ Код `{clean_code}` не найден на этом сервере.", ephemeral=True)
        return

    role = interaction.guild.get_role(stats["role_id"])
    role_str = role.mention if role else f"ID: {stats['role_id']} (Удалена)"
    max_u = "∞" if stats["max_uses"] == 0 else str(stats["max_uses"])

    embed = discord.Embed(
        title=f"📊 Информация о коде `{clean_code}`",
        color=discord.Color.blue()
    )
    embed.add_field(name="🎭 Выдаваемая роль", value=role_str, inline=True)
    embed.add_field(name="🔢 Активаций", value=f"{stats['used_count']} / {max_u}", inline=True)
    embed.add_field(name="⏳ Срок действия", value=format_timestamp(stats["expires_at"]), inline=True)
    embed.add_field(name="🟢 Статус", value="Активен" if stats["is_active"] else "Деактивирован", inline=True)

    if stats["note"]:
        embed.add_field(name="📝 Заметка", value=stats["note"], inline=False)

    redemptions = stats.get("redemptions", [])
    if redemptions:
        lines = []
        for r in redemptions[:15]:
            user_mention = f"<@{r['user_id']}>"
            time_str = f"<t:{r['redeemed_at']}:R>"
            lines.append(f"• {user_mention} — {time_str}")
        if len(redemptions) > 15:
            lines.append(f"... и ещё {len(redemptions) - 15} чел.")
        embed.add_field(name=f"👥 Кто активировал ({len(redemptions)})", value="\n".join(lines), inline=False)
    else:
        embed.add_field(name="👥 Кто активировал", value="Пока никто не активировал этот код.", inline=False)

    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="post_redeem_box", description="Отправить блок с кнопкой ввода кода в указанный канал")
@app_commands.describe(channel="Канал для отправки (если не указан, отправится в текущий канал)")
@app_commands.default_permissions(administrator=True)
async def post_redeem_box(interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None):
    if not interaction.user.guild_permissions.administrator and not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message("❌ У вас нет прав для этой команды.", ephemeral=True)
        return

    target_channel = channel or interaction.channel
    perms = target_channel.permissions_for(interaction.guild.me)
    if not perms.send_messages or not perms.embed_links:
        await interaction.response.send_message(
            f"❌ У бота нет прав на отправку сообщений в {target_channel.mention}.",
            ephemeral=True
        )
        return

    embed = discord.Embed(
        title="🎁 Получение роли по промокоду",
        description=(
            "Если у вас есть код доступа или промокод — нажмите кнопку ниже и введите его.\n\n"
            "После быстрой проверки бот автоматически выдаст вам роль!"
        ),
        color=discord.Color.blurple()
    )
    embed.set_footer(text="Один код можно активировать только один раз.")

    await target_channel.send(embed=embed, view=PersistentRedeemView())
    await interaction.response.send_message(
        f"✅ Блок активации успешно размещен в канале {target_channel.mention}!",
        ephemeral=True
    )


# ==========================================
# СЛЭШ-КОМАНДА ДЛЯ УЧАСТНИКОВ (ПРЯМОЙ ВВОД)
# ==========================================

@bot.tree.command(name="redeem", description="Активировать код доступа и получить роль")
@app_commands.describe(code="Ваш промокод или секретный ключ")
async def redeem(interaction: discord.Interaction, code: str):
    await interaction.response.defer(ephemeral=True, thinking=True)
    clean_code = code.strip().upper()

    success, msg, role_id = await db.redeem_code(
        code=clean_code,
        guild_id=interaction.guild.id,
        user_id=interaction.user.id
    )

    if not success:
        embed = discord.Embed(
            title="Ошибка активации",
            description=msg,
            color=discord.Color.red()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        return

    role = interaction.guild.get_role(role_id)
    if not role:
        await interaction.followup.send("⚠️ Роль не найдена на сервере. Обратитесь к администратору.", ephemeral=True)
        return

    bot_member = interaction.guild.me
    if not bot_member.guild_permissions.manage_roles:
        await interaction.followup.send("⚠️ У бота нет прав управлять ролями (`Manage Roles`).", ephemeral=True)
        return

    if bot_member.top_role <= role:
        await interaction.followup.send(
            f"⚠️ Роль бота ниже, чем роль **{role.name}**. Обратитесь к администратору.",
            ephemeral=True
        )
        return

    try:
        member = interaction.user
        if role in member.roles:
            embed = discord.Embed(
                title="ℹ️ Роль уже у вас",
                description=f"Код активирован, но роль **{role.mention}** уже выдана вам ранее.",
                color=discord.Color.blue()
            )
        else:
            await member.add_roles(role, reason=f"Активация промокода {clean_code}")
            embed = discord.Embed(
                title="🎉 Успешная активация!",
                description=f"Вам выдана роль: **{role.mention}**",
                color=discord.Color.green()
            )
            embed.add_field(name="Код", value=f"`{clean_code}`", inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ Ошибка при выдаче роли: {e}", ephemeral=True)


# ==========================================
# ТОЧКА ВХОДА
# ==========================================
def main():
    if not DISCORD_TOKEN or DISCORD_TOKEN == "ВАШ_ТОКЕН_ЗДЕСЬ":
        print("\n" + "!" * 60)
        print("ОШИБКА: Токен бота не задан!")
        print("Откройте файл .env в папке бота и вставьте ваш DISCORD_TOKEN.")
        print("Получить токен можно на https://discord.com/developers/applications")
        print("!" * 60 + "\n")
        sys.exit(1)

    try:
        bot.run(DISCORD_TOKEN)
    except discord.LoginFailure:
        print("\n" + "!" * 60)
        print("ОШИБКА: Неверный токен Discord! Проверьте значение DISCORD_TOKEN в файле .env.")
        print("!" * 60 + "\n")
    except Exception as e:
        print(f"\nКритическая ошибка запуска: {e}")

if __name__ == "__main__":
    main()
