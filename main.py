import os
import asyncio
import threading
import discord
from discord import app_commands
from flask import Flask

# ═══════════════════ CẤU HÌNH ═══════════════════
# Token lấy từ biến môi trường -> KHÔNG dán token vào file này!
TOKEN           = os.getenv("DISCORD_TOKEN", "")

GIF_URL         = "https://i.pinimg.com/originals/78/17/b2/7817b2cf90b9144bc972b7950a9aebf3.gif"
TICKET_CATEGORY = 1548743518292549822       # ID Category HOẶC kênh text
POLICY_LINK     = "https://discord.com"
EMBED_COLOR     = 0x0B0B0B
SHOP_NAME       = "RyanX"
GUILD_ID        = 0                         # ID server (lệnh hiện ngay)

ADMIN_ROLE_ID   = 0    # ID role Admin (để tag khi tạo/đóng ticket)
SUPPORT_ROLE_ID = 0    # ID role Support Mod

STAFF_EXTRA_ROLE_IDS = []

# ═════════════ KIỂM TRA TOKEN TRƯỚC KHI CHẠY ═════════════
if not TOKEN:
    raise SystemExit(
        "⚠️ Chưa có token! Hãy set biến môi trường DISCORD_TOKEN\n"
        "   - Trên máy:  set DISCORD_TOKEN=token_cua_ban  (Windows)\n"
        "   - Trên Render: Environment → DISCORD_TOKEN")

intents = discord.Intents.default()
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)


# ═════════════ WEB SERVER GIỮ BOT SỐNG 24/7 (Render) ═════════════
web = Flask(__name__)

@web.route("/")
def home():
    return f"✅ {SHOP_NAME} Ticket Bot đang chạy 24/7!"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    web.run(host="0.0.0.0", port=port)

threading.Thread(target=run_web, daemon=True).start()


# ===================== TIỆN ÍCH =====================
def black_embed(title: str = None, description: str = None) -> discord.Embed:
    return discord.Embed(title=title, description=description, color=EMBED_COLOR)


def is_staff(member: discord.Member) -> bool:
    p = member.guild_permissions
    if p.administrator or p.manage_guild or p.manage_channels:
        return True
    return any(member.get_role(rid) for rid in STAFF_EXTRA_ROLE_IDS)


def get_category(guild: discord.Guild):
    ch = guild.get_channel(TICKET_CATEGORY)
    if isinstance(ch, discord.TextChannel):
        return ch.category
    if isinstance(ch, discord.CategoryChannel):
        return ch
    return None


def get_ping_roles(guild: discord.Guild):
    roles = []
    for rid in (ADMIN_ROLE_ID, SUPPORT_ROLE_ID):
        if rid:
            r = guild.get_role(rid)
            if r and r not in roles:
                roles.append(r)
    if roles:
        return roles

    def priority(name: str) -> int:
        n = name.lower()
        if n in ("admin", "administrator", "support", "support mod", "mod", "moderator"):
            return 0
        if "admin" in n or "support" in n or "mod" in n:
            return 1
        return 2

    candidates = sorted(
        (r for r in guild.roles if not r.is_default() and not r.managed),
        key=lambda r: priority(r.name))
    for r in candidates:
        if priority(r.name) >= 2:
            break
        if r not in roles:
            roles.append(r)
        if len(roles) >= 3:
            break
    return roles


# ===================== EMBED =====================
def panel_embed() -> discord.Embed:
    e = black_embed(
        title="🔥 HỖ TRỢ KHÁCH HÀNG",
        description=(
            "**🛒 MUA HÀNG:**\n"
            "Nếu bạn muốn mua key bản quyền hoặc dịch vụ tối ưu PC\n\n"
            "**⚙️ HỖ TRỢ:**\n"
            "Nếu bạn cần kích hoạt key, cài đặt, bảo hành hoặc gặp lỗi sau khi mua\n\n"
            "✦ Vui lòng không spam ticket\n"
            "✦ Khách hàng là thượng đế\n"
            "✦ Mua hàng = chấp nhận Rules & Chính sách mà Shop đưa ra"
        ),
    )
    e.set_image(url=GIF_URL)
    e.set_footer(text=f"{SHOP_NAME} • TICKET SUPPORT CENTER")
    return e


def ticket_embed(user: discord.Member, loai: str) -> discord.Embed:
    e = black_embed(
        title=f"🎟️ TICKET {loai}",
        description=(
            f"Xin chào {user.mention}, chào mừng đến với ticket!\n\n"
            "📝 Vui lòng mô tả **chi tiết vấn đề** của bạn để staff hỗ trợ nhanh nhất.\n\n"
            "✦ Không spam / ping staff liên tục\n"
            "✦ Không chia sẻ thông tin cá nhân\n"
            "✦ Staff sẽ phản hồi trong ít phút"
        ),
    )
    e.set_thumbnail(url=user.display_avatar.url)
    e.set_image(url=GIF_URL)
    e.set_footer(text=f"{SHOP_NAME} • TICKET SUPPORT CENTER")
    return e


# ===================== TẠO TICKET =====================
async def open_ticket(interaction: discord.Interaction, slug: str, loai: str):
    try:
        await _open_ticket_impl(interaction, slug, loai)
    except Exception as e:
        print("❌ Lỗi open_ticket:", e)
        msg = black_embed(description=f"❌ Đã xảy ra lỗi: `{e}`")
        if interaction.response.is_done():
            await interaction.followup.send(embed=msg, ephemeral=True)
        else:
            await interaction.response.send_message(embed=msg, ephemeral=True)


async def _open_ticket_impl(interaction: discord.Interaction, slug: str, loai: str):
    guild, user = interaction.guild, interaction.user
    category = get_category(guild)

    if not category:
        return await interaction.response.send_message(
            embed=black_embed(description="⚠️ `TICKET_CATEGORY` sai ID!"), ephemeral=True)

    for ch in category.text_channels:
        if ch.topic and ch.topic.startswith(f"ticket|{user.id}|"):
            return await interaction.response.send_message(
                embed=black_embed(description=f"❌ Bạn đã có ticket mở: {ch.mention}"),
                ephemeral=True)

    await interaction.response.defer(ephemeral=True)

    ping_roles = get_ping_roles(guild)

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        user: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True,
            attach_files=True, embed_links=True),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
    }

    for role in ping_roles:
        overwrites[role] = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True)
    for role in guild.roles:
        if role.is_default():
            continue
        perms = role.permissions
        if perms.administrator or perms.manage_guild or perms.manage_channels or role.id in STAFF_EXTRA_ROLE_IDS:
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True)

    try:
        channel = await guild.create_text_channel(
            name=f"{slug}-{user.name}", category=category,
            topic=f"ticket|{user.id}|{slug}", overwrites=overwrites,
            reason=f"Ticket {loai} - {user}",
        )
    except discord.Forbidden:
        return await interaction.followup.send(
            embed=black_embed(description="❌ Bot thiếu quyền **Manage Channels / Manage Roles**!"),
            ephemeral=True)

    mention_staff = " ".join(r.mention for r in ping_roles)
    content = user.mention + (f" • {mention_staff}" if mention_staff else "")

    await channel.send(content, embed=ticket_embed(user, loai), view=TicketControl())
    await interaction.followup.send(
        embed=black_embed(description=f"✅ Ticket của bạn: {channel.mention}"),
        ephemeral=True)


# ===================== FORM LÝ DO ĐÓNG TICKET =====================
class CloseReasonModal(discord.ui.Modal, title="🔒 Đóng Ticket"):
    ly_do = discord.ui.TextInput(
        label="Lý do đóng ticket (có thể bỏ trống)",
        style=discord.TextStyle.paragraph,
        placeholder="VD: Đã hỗ trợ xong / Đã bán hàng...",
        required=False, max_length=300)

    async def on_submit(self, interaction: discord.Interaction):
        staff = " ".join(r.mention for r in get_ping_roles(interaction.guild))
        desc = (
            f"**📝 Lý do:** {self.ly_do.value or '*Không có lý do*'}\n"
            f"**👤 Người đóng:** {interaction.user.mention}\n"
            + (f"**🔔 Thông báo:** {staff}\n" if staff else "")
            + "\nBạn có chắc muốn đóng ticket này?"
        )
        await interaction.response.send_message(
            embed=black_embed(title="⚠️ XÁC NHẬN ĐÓNG TICKET", description=desc),
            view=ConfirmClose())


# ===================== NÚT TRONG TICKET =====================
class TicketControl(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="NHẬN XỬ LÝ", emoji="🙋", style=discord.ButtonStyle.secondary, custom_id="ryanx_claim")
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_staff(interaction.user):
            return await interaction.response.send_message(
                embed=black_embed(description="❌ Chỉ người có quyền quản lý mới nhận được ticket!"),
                ephemeral=True)
        button.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.channel.send(
            embed=black_embed(description=f"🙋 {interaction.user.mention} đã nhận ticket. Vui lòng chờ!"))

    @discord.ui.button(label="ĐÓNG TICKET", emoji="🔒", style=discord.ButtonStyle.secondary, custom_id="ryanx_close")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CloseReasonModal())


class ConfirmClose(discord.ui.View):
    @discord.ui.button(label="XÁC NHẬN ĐÓNG", emoji="🔒", style=discord.ButtonStyle.secondary)
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            embed=black_embed(description="🔒 Ticket sẽ bị **xóa sau 5 giây**..."))
        await asyncio.sleep(5)
        try:
            await interaction.channel.delete(reason="Ticket đã đóng")
        except Exception as e:
            print("❌ Lỗi xóa kênh:", e)

    @discord.ui.button(label="HỦY", emoji="↩️", style=discord.ButtonStyle.secondary)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.message.delete()


# ===================== PANEL CHÍNH =====================
class TicketPanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(
            label="CHÍNH SÁCH MUA HÀNG", emoji="📜",
            style=discord.ButtonStyle.link, url=POLICY_LINK))

    @discord.ui.button(label="MUA HÀNG", emoji="🛒", style=discord.ButtonStyle.secondary, custom_id="ryanx_buy")
    async def buy(self, interaction: discord.Interaction, button: discord.ui.Button):
        await open_ticket(interaction, "mua-hang", "MUA HÀNG")

    @discord.ui.button(label="HỖ TRỢ", emoji="⚙️", style=discord.ButtonStyle.secondary, custom_id="ryanx_support")
    async def support(self, interaction: discord.Interaction, button: discord.ui.Button):
        await open_ticket(interaction, "ho-tro", "HỖ TRỢ")


# ===================== LỆNH =====================
@tree.command(name="setup-ticket", description="📩 Gửi panel ticket hỗ trợ")
@app_commands.checks.has_permissions(administrator=True)
async def setup_ticket(interaction: discord.Interaction):
    await interaction.response.send_message(embed=panel_embed(), view=TicketPanel())


@setup_ticket.error
async def setup_ticket_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            embed=black_embed(description="❌ Chỉ admin mới dùng được lệnh này!"), ephemeral=True)
    else:
        print("Lỗi lệnh setup-ticket:", error)


@tree.command(name="ticket", description="🎟️ Tạo ticket hỗ trợ ngay lập tức")
@app_commands.describe(loai="Chọn loại ticket (không chọn = HỖ TRỢ)")
@app_commands.choices(loai=[
    app_commands.Choice(name="🛒 MUA HÀNG", value="mua-hang"),
    app_commands.Choice(name="⚙️ HỖ TRỢ", value="ho-tro"),
])
async def ticket(interaction: discord.Interaction, loai: app_commands.Choice[str] = None):
    slug = loai.value if loai else "ho-tro"
    ten  = "MUA HÀNG" if slug == "mua-hang" else "HỖ TRỢ"
    await open_ticket(interaction, slug, ten)


# ===================== SỰ KIỆN =====================
@bot.event
async def on_ready():
    bot.add_view(TicketPanel())
    bot.add_view(TicketControl())
    try:
        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)
            tree.copy_global_to(guild=guild)
            await tree.sync(guild=guild)
        else:
            await tree.sync()
        print("✅ Đã sync lệnh!")
    except Exception as e:
        print("Lỗi sync lệnh:", e)
    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.watching, name=f"{SHOP_NAME} • Ticket"))
    print(f"✅ Bot online: {bot.user}")


bot.run(TOKEN)
