import secrets
import string
import time
from typing import Optional
import discord
from discord import ui
from database import db
from config import CODE_PREFIX

def generate_random_code(length: int = 6) -> str:
    """Генерация 6-значного кода вида XXXXXX (например: 7K9AB2)"""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # без похожих O, 0, I, 1
    return "".join(secrets.choice(alphabet) for _ in range(length))

def format_timestamp(ts: Optional[int]) -> str:
    if not ts:
        return "Бессрочно"
    return f"<t:{ts}:f> (<t:{ts}:R>)"

# ==========================================
# МОДАЛЬНОЕ ОКНО КАК НА СКРИНШОТЕ
# ==========================================
class RedeemCodeModal(ui.Modal, title="🕵️ Last step to be verified!"):
    code_input = ui.TextInput(
        label="CAPTCHA Code",
        placeholder="XXXXXX",
        min_length=1,
        max_length=32,
        required=True,
        style=discord.TextStyle.short
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        code_str = self.code_input.value.strip().upper()

        if not interaction.guild:
            await interaction.followup.send("❌ Активация кодов возможна только на сервере.", ephemeral=True)
            return

        # 1. Попытка активации в базе данных
        success, msg, role_id = await db.redeem_code(
            code=code_str,
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

        # 2. Выдача роли в Discord
        role = interaction.guild.get_role(role_id)
        if not role:
            embed = discord.Embed(
                title="⚠️ Роль не найдена",
                description=(
                    f"Код `{code_str}` корректен, но привязанная к нему роль (ID: `{role_id}`) "
                    "была удалена с сервера. Обратитесь к администрации."
                ),
                color=discord.Color.orange()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        # Проверка прав бота
        bot_member = interaction.guild.me
        if not bot_member.guild_permissions.manage_roles:
            embed = discord.Embed(
                title="⚠️ Ошибка прав бота",
                description="У бота нет разрешения **Управлять ролями** (`Manage Roles`). Сообщите администраторам.",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        if bot_member.top_role <= role:
            embed = discord.Embed(
                title="⚠️ Ошибка иерархии ролей",
                description=(
                    f"Роль бота ниже, чем выдаваемая роль **{role.name}**.\n"
                    "Администратор должен поднять роль бота выше в *Настройки сервера -> Роли*."
                ),
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        # Выдаем роль
        try:
            member = interaction.user
            if isinstance(member, discord.Member):
                if role in member.roles:
                    embed = discord.Embed(
                        title="ℹ️ Роль уже у вас",
                        description=f"Код успешно учтён, но у вас уже есть роль **{role.mention}**!",
                        color=discord.Color.blue()
                    )
                else:
                    await member.add_roles(role, reason=f"Активация промокода {code_str}")
                    embed = discord.Embed(
                        title="🎉 Успешная активация!",
                        description=f"Вам успешно выдана роль: **{role.mention}**",
                        color=discord.Color.green()
                    )
                    embed.add_field(name="Код", value=f"`{code_str}`", inline=True)
                    embed.set_footer(text="Приятного общения!")

                await interaction.followup.send(embed=embed, ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("❌ Недостаточно прав для выдачи роли.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Произошла ошибка при выдаче роли: {e}", ephemeral=True)


# ==========================================
# ПОСТОЯННАЯ КНОПКА В ЧАТЕ ДЛЯ УЧАСТНИКОВ
# ==========================================
class PersistentRedeemView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(
        label="Verify",
        style=discord.ButtonStyle.success,
        emoji="🕵️",
        custom_id="persistent_btn_verify_code"
    )
    async def verify_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(RedeemCodeModal())


# ==========================================
# МОДАЛКА НАСТРОЙКИ КОДА ПРИ СОЗДАНИИ
# ==========================================
class CodeSettingsModal(ui.Modal):
    def __init__(self, role: discord.Role):
        super().__init__(title=f"Код для роли @{role.name[:20]}")
        self.role = role

        self.custom_code = ui.TextInput(
            label="Свой код (оставьте пустым для авто)",
            placeholder="Например: VIP2026 или пусто",
            required=False,
            max_length=32
        )
        self.max_uses = ui.TextInput(
            label="Лимит использований (0 = бесконечно)",
            default="1",
            required=True,
            max_length=6
        )
        self.expire_hours = ui.TextInput(
            label="Срок жизни в часах (0 = бессрочно)",
            default="0",
            required=True,
            max_length=6
        )
        self.note = ui.TextInput(
            label="Заметка / Для кого (необязательно)",
            placeholder="Например: Розыгрыш в Telegram",
            required=False,
            max_length=100
        )

        self.add_item(self.custom_code)
        self.add_item(self.max_uses)
        self.add_item(self.expire_hours)
        self.add_item(self.note)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        # Валидация лимита
        try:
            uses = int(self.max_uses.value.strip())
            if uses < 0:
                raise ValueError()
        except ValueError:
            await interaction.followup.send("❌ Лимит использований должен быть целым неотрицательным числом.", ephemeral=True)
            return

        # Валидация срока
        try:
            hours = float(self.expire_hours.value.strip())
            if hours < 0:
                raise ValueError()
            expires_at = int(time.time() + hours * 3600) if hours > 0 else None
        except ValueError:
            await interaction.followup.send("❌ Срок жизни должен быть положительным числом часов или 0.", ephemeral=True)
            return

        # Генерация или очистка кода
        code = self.custom_code.value.strip().upper()
        if not code:
            code = generate_random_code()

        success, msg = await db.create_code(
            code=code,
            guild_id=interaction.guild.id,
            role_id=self.role.id,
            max_uses=uses,
            expires_at=expires_at,
            created_by=interaction.user.id,
            note=self.note.value.strip()
        )

        if not success:
            await interaction.followup.send(f"❌ {msg}", ephemeral=True)
            return

        embed = discord.Embed(
            title="✅ Код успешно сгенерирован!",
            color=discord.Color.green()
        )
        embed.add_field(name="🔑 Код", value=f"```\n{code}\n```", inline=False)
        embed.add_field(name="🎭 Роль", value=self.role.mention, inline=True)
        embed.add_field(name="🔢 Лимит использований", value="Бесконечно" if uses == 0 else f"{uses} раз", inline=True)
        embed.add_field(name="⏳ Срок действия", value=format_timestamp(expires_at), inline=True)
        if self.note.value.strip():
            embed.add_field(name="📝 Заметка", value=self.note.value.strip(), inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)


# ==========================================
# ВЫБОР РОЛИ ДЛЯ СОЗДАНИЯ КОДА
# ==========================================
class RoleSelectView(ui.View):
    def __init__(self):
        super().__init__(timeout=180)

    @ui.select(cls=ui.RoleSelect, placeholder="Выберите роль, которую будет давать код...", min_values=1, max_values=1)
    async def select_role(self, interaction: discord.Interaction, select: ui.RoleSelect):
        selected_role = select.values[0]
        # Проверяем, чтобы роль не была @everyone или выше бота
        if selected_role.is_default():
            await interaction.response.send_message("❌ Нельзя назначить роль @everyone.", ephemeral=True)
            return

        if interaction.guild.me.top_role <= selected_role:
            await interaction.response.send_message(
                f"⚠️ Внимание: роль бота ниже роли {selected_role.mention}. "
                "Бот не сможет выдать её участникам, пока вы не поднимете роль бота выше.",
                ephemeral=True
            )

        modal = CodeSettingsModal(role=selected_role)
        await interaction.response.send_modal(modal)


# ==========================================
# ВЫБОР КАНАЛА ДЛЯ ПУБЛИКАЦИИ ВИТРИНЫ
# ==========================================
class ChannelSelectForRedeemView(ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    @ui.select(
        cls=ui.ChannelSelect,
        channel_types=[discord.ChannelType.text, discord.ChannelType.news],
        placeholder="Выберите текстовый канал для кнопки активации..."
    )
    async def select_channel(self, interaction: discord.Interaction, select: ui.ChannelSelect):
        channel = select.values[0]
        perms = channel.permissions_for(interaction.guild.me)
        if not perms.send_messages or not perms.embed_links:
            await interaction.response.send_message(
                f"❌ У бота нет прав отправлять сообщения/встраивать ссылки в канал {channel.mention}.",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="🕵️ Verification / Верификация",
            description=(
                "Для получения доступа к серверу нажмите на кнопку **Verify** ниже "
                "и введите выданный вам код (**CAPTCHA Code**).\n\n"
                "После проверки кода бот автоматически выдаст вам роль!"
            ),
            color=discord.Color.dark_theme()
        )
        embed.set_footer(text="Verification Gate • Нажмите кнопку ниже для верификации")

        await channel.send(embed=embed, view=PersistentRedeemView())
        await interaction.response.send_message(
            f"✅ Сообщение с кнопкой **Verify** успешно отправлено в канал {channel.mention}!",
            ephemeral=True
        )


# ==========================================
# МОДАЛКА ДЕАКТИВАЦИИ КОДА
# ==========================================
class RevokeCodeModal(ui.Modal, title="Отозвать / Деактивировать код"):
    code_input = ui.TextInput(
        label="Код для деактивации",
        placeholder="Введите код, который хотите аннулировать",
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        code_str = self.code_input.value.strip().upper()
        success = await db.revoke_code(code_str, interaction.guild.id)
        if success:
            await interaction.response.send_message(f"✅ Код `{code_str}` успешно деактивирован.", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ Код `{code_str}` не найден на этом сервере.", ephemeral=True)


# ==========================================
# ГЛАВНОЕ МЕНЮ АДМИН-ПАНЕЛИ
# ==========================================
class AdminPanelView(ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @ui.button(label="Создать код", style=discord.ButtonStyle.primary, emoji="➕", row=0)
    async def btn_create(self, interaction: discord.Interaction, button: ui.Button):
        embed = discord.Embed(
            title="➕ Создание нового кода",
            description="Выберите роль из выпадающего списка ниже, которую участник получит при вводе кода:",
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed, view=RoleSelectView(), ephemeral=True)

    @ui.button(label="Список кодов", style=discord.ButtonStyle.secondary, emoji="📋", row=0)
    async def btn_list(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        codes = await db.list_codes(interaction.guild.id, limit=25)

        if not codes:
            await interaction.followup.send("ℹ️ На этом сервере пока нет созданных кодов.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"📋 Список кодов сервера ({len(codes)})",
            color=discord.Color.blue()
        )

        now = int(time.time())
        for c in codes:
            role = interaction.guild.get_role(c["role_id"])
            role_name = role.mention if role else f"ID: {c['role_id']} (Удалена)"

            # Статус
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

    @ui.button(label="Отозвать код", style=discord.ButtonStyle.danger, emoji="❌", row=1)
    async def btn_revoke(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(RevokeCodeModal())

    @ui.button(label="Установить кнопку Verify в канал", style=discord.ButtonStyle.success, emoji="📢", row=1)
    async def btn_post_showcase(self, interaction: discord.Interaction, button: ui.Button):
        embed = discord.Embed(
            title="📢 Публикация блока верификации",
            description="Выберите канал, куда бот отправит сообщение с кнопкой **«Verify»**:",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, view=ChannelSelectForRedeemView(), ephemeral=True)
