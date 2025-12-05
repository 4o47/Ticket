import discord
from discord import app_commands
import sqlite3
import os
import datetime
import asyncio
import io

# =========================================================
# ⚙️ إعدادات السيرفر (يجب تعديل هذه القيم)
# =========================================================

# يتم استدعاء التوكن من قائمة Secrets في Replit (DISCORD_TOKEN)
TOKEN = os.environ.get('DISCORD_TOKEN') 

# يجب أن يكون التوكن صحيحاً لعمل البوت
if not TOKEN:
    print("FATAL ERROR: DISCORD_TOKEN not found in Replit Secrets.")

# ضع أرقام الآيديات الخاصة بك هنا
GUILD_ID = 1245964626374692866 # آيدي السيرفر
STAFF_ROLE_ID = 1440469974455156789 # آيدي رتبة الإدارة (التي تستلم التكتات)
LOG_CHANNEL_ID = 1442616571049541774 # آيدي روم السجلات (Logs)
RATING_CHANNEL_ID = 1442616336252539181 # آيدي روم وصول التقييمات
OWNER_ID = 767758085376180256 # آيدي أونر السيرفر

# الردود التلقائية (كلمة مفتاحية : الرد)
AUTO_RESPONSES = {
    "السلام عليكم": "وعليكم السلام ورحمة الله! كيف يمكننا خدمتك اليوم؟",
    "تحويل": "لتحويل الأموال، يرجى تزويدنا بصورة التحويل وانتظار المسؤول.",
    "سعر": "يمكنك معرفة الأسعار عبر التوجه لروم #الأسعار",
}

# =========================================================
# 💾 نظام قاعدة البيانات (SQLite)
# =========================================================

def get_db_connection():
    return sqlite3.connect('bot_database.db')

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    # إنشاء جدول لحفظ نقاط الإداريين (لتقييم الأداء)
    c.execute('''
        CREATE TABLE IF NOT EXISTS staff_points (
            user_id INTEGER PRIMARY KEY,
            points INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

# تشغيل تهيئة قاعدة البيانات عند بدء البوت
init_db()

def get_staff_points(user_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT points FROM staff_points WHERE user_id = ?", (user_id,))
    data = c.fetchone()
    conn.close()
    return data[0] if data else 0

def add_staff_point(user_id):
    conn = get_db_connection()
    c = conn.cursor()
    # إضافة نقطة. إذا لم يكن موجوداً، يضيفه بصفر
    c.execute("INSERT OR IGNORE INTO staff_points (user_id, points) VALUES (?, 0)", (user_id,))
    c.execute("UPDATE staff_points SET points = points + 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def get_top_staff():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT user_id, points FROM staff_points ORDER BY points DESC LIMIT 10")
    data = c.fetchall()
    conn.close()
    return data

# =========================================================
# 🖼️ نافذة تغيير اسم التكت (Modal)
# =========================================================
class RenameTicketModal(discord.ui.Modal, title="تغيير اسم التكت"):
    name_input = discord.ui.TextInput(
        label="الاسم الجديد",
        placeholder="مثال: closed-support-123",
        min_length=3,
        max_length=50
    )

    async def on_submit(self, interaction: discord.Interaction):
        # التحقق من الصلاحية: هل المستخدم لديه رتبة الإدارة؟
        staff_role = interaction.guild.get_role(STAFF_ROLE_ID)
        if staff_role and staff_role not in interaction.user.roles:
            return await interaction.response.send_message(f"❌ هذا الإجراء للإدارة فقط.", ephemeral=True)

        new_name = self.name_input.value.replace(" ", "-").lower()
        
        try:
            await interaction.channel.edit(name=new_name)
            await interaction.response.send_message(f"✅ تم تغيير اسم الروم إلى `{new_name}`", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ حدث خطأ أثناء تغيير الاسم: {e}", ephemeral=True)

# =========================================================
# 📝 نافذة فتح التكت (Modal)
# =========================================================
class TicketModal(discord.ui.Modal, title="فتح تذكرة جديدة"):
    def __init__(self, ticket_type: str, *args, **kwargs):
        super().__init__(*args, **kwargs, timeout=300)
        self.ticket_type = ticket_type

    problem_summary = discord.ui.TextInput(
        label="عنوان المشكلة",
        placeholder="اختصار للمشكلة...",
        max_length=50
    )

    problem_details = discord.ui.TextInput(
        label="التفاصيل الكاملة",
        placeholder="اشرح مشكلتك بالتفصيل هنا...",
        style=discord.TextStyle.paragraph,
        max_length=1000
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        
        guild = interaction.guild
        
        # البحث عن كتغوري "Tickets" أو إنشائه
        category = discord.utils.get(guild.categories, name="Tickets")
        if not category:
            try:
                category = await guild.create_category("Tickets")
            except Exception as e:
                return await interaction.followup.send(f"❌ خطأ: فشل في إنشاء فئة التذاكر. تحقق من صلاحيات البوت. ({e})", ephemeral=True)

        # إعداد الصلاحيات للروم الجديد
        # (إخفاء الروم عن الجميع، ثم إظهاره لصاحب التكت ولرتبة الإدارة)
        staff_role = guild.get_role(STAFF_ROLE_ID)
        if not staff_role:
            return await interaction.followup.send(f"❌ خطأ: لم يتم العثور على رتبة الإدارة بالآيدي {STAFF_ROLE_ID}.", ephemeral=True)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True, embed_links=True),
            staff_role: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }

        # إنشاء الروم وتخزين صاحب التكت في الـ Topic
        channel_name = f"{self.ticket_type}-{self.problem_summary.value.replace(' ', '-').lower()}"

        try:
            channel = await guild.create_text_channel(
                channel_name[:100],  # تحديد طول الاسم لـ 100 حرف كحد أقصى
                category=category,
                overwrites=overwrites,
                topic=str(interaction.user.id) # لتخزين آيدي صاحب التكت في الـ Topic
            )
        except Exception as e:
            return await interaction.followup.send(f"❌ خطأ: فشل في إنشاء قناة التكت. تحقق من صلاحيات البوت. ({e})", ephemeral=True)

        # رسالة الترحيب داخل التكت
        embed = discord.Embed(
            title=f"تكت جديد: {self.ticket_type}",
            description=f"مرحباً {interaction.user.mention}\nسيقوم فريق الدعم بالرد عليك قريباً.",
            color=discord.Color.blue()
        )
        embed.add_field(name="📜 العنوان", value=self.problem_summary.value, inline=False)
        embed.add_field(name="📝 التفاصيل", value=self.problem_details.value, inline=False)
        embed.add_field(name="⏳ الحالة", value="بانتظار الاستلام", inline=True)
        
        await channel.send(staff_role.mention, embed=embed, view=TicketControlView())
        await interaction.followup.send(f"✅ تم فتح التكت بنجاح: {channel.mention}", ephemeral=True)


# =========================================================
# ⭐️ نظام التقييم (Stars)
# =========================================================
class RatingView(discord.ui.View):
    def __init__(self, staff_member, original_opener, ticket_channel_name, guild_id):
        super().__init__(timeout=600)
        self.staff_member_id = staff_member.id
        self.staff_member_name = staff_member.display_name
        self.original_opener_id = original_opener.id
        self.ticket_channel_name = ticket_channel_name
        self.guild_id = guild_id
        
    async def process_rating(self, interaction: discord.Interaction, stars: int):
        try:
            # التأكد من أن صاحب التكت هو من يقوم بالتقييم
            if interaction.user.id != self.original_opener_id:
                return await interaction.response.send_message("❌ يمكنك لصاحب التكت الأصلي فقط التقييم.", ephemeral=True)

            # الرد فوراً لتجنب انتهاء الوقت
            await interaction.response.send_message(f"شكراً لك! تم إرسال تقييمك ({stars} نجوم).")

            # الحصول على السيرفر من الـ bot مباشرة (لأن التقييم يحصل في DM)
            guild = interaction.client.get_guild(self.guild_id)
            if guild:
                rating_channel = guild.get_channel(RATING_CHANNEL_ID)
                staff_member = guild.get_member(self.staff_member_id)
                
                # إرسال التقييم لروم التقييمات
                if rating_channel:
                    embed = discord.Embed(
                        title=f"⭐ تقييم جديد: {stars} نجوم",
                        color=discord.Color.gold()
                    )
                    staff_mention = staff_member.mention if staff_member else f"إداري ({self.staff_member_id})"
                    embed.add_field(name="👤 المُقيّم", value=interaction.user.mention, inline=True)
                    embed.add_field(name="مستلم الخدمة", value=staff_mention, inline=True)
                    embed.add_field(name="📜 اسم التكت", value=self.ticket_channel_name, inline=False)

                    if stars >= 4:
                        # إضافة نقطة إذا كان التقييم 4 نجوم أو أكثر
                        add_staff_point(self.staff_member_id)
                        new_points = get_staff_points(self.staff_member_id)
                        embed.add_field(name="إجمالي نقاط الإداري", value=str(new_points), inline=False)
                        embed.description = f"تم إضافة نقطة واحدة لـ {staff_mention}."
                    else:
                        embed.description = "لم يتم إضافة نقطة (التقييم أقل من 4 نجوم)."
                        
                    await rating_channel.send(embed=embed)

            # تعطيل الأزرار بعد التقييم
            for item in self.children:
                item.disabled = True
            await interaction.message.edit(view=self)
            self.stop()
        except discord.NotFound:
            pass
        except Exception as e:
            print(f"خطأ في التقييم: {e}")
        
    @discord.ui.button(label="⭐", style=discord.ButtonStyle.danger)
    async def star_1(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.process_rating(interaction, 1)

    @discord.ui.button(label="⭐⭐⭐", style=discord.ButtonStyle.primary)
    async def star_3(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.process_rating(interaction, 3)

    @discord.ui.button(label="⭐⭐⭐⭐⭐", style=discord.ButtonStyle.success)
    async def star_5(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.process_rating(interaction, 5)

# =========================================================
# 🔨 لوحة تحكم التكت (داخل الروم)
# =========================================================
class TicketControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    # --- استلام التكت ---
    @discord.ui.button(label="✅ استلام التكت", style=discord.ButtonStyle.success, custom_id="persistent:claim_ticket")
    async def claim_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            staff_role = interaction.guild.get_role(STAFF_ROLE_ID)
            if staff_role and staff_role not in interaction.user.roles:
                return await interaction.response.send_message("❌ هذا الإجراء للإدارة فقط.", ephemeral=True)
            
            # التحقق إذا التكت مستلم مسبقاً
            current_topic = interaction.channel.topic or ""
            if "|" in current_topic:
                return await interaction.response.send_message("❌ هذا التكت مستلم مسبقاً.", ephemeral=True)
            
            # حفظ آيدي الإداري المستلم في الـ topic
            # الصيغة: opener_id|claimer_id
            new_topic = f"{current_topic}|{interaction.user.id}"
            await interaction.channel.edit(topic=new_topic)
            
            # منع باقي الإداريين من الكتابة في التكت
            if staff_role:
                await interaction.channel.set_permissions(staff_role, send_messages=False, read_messages=True)
            
            # السماح فقط للإداري المستلم بالكتابة
            await interaction.channel.set_permissions(interaction.user, send_messages=True, read_messages=True)
            
            embed = discord.Embed(
                description=f"✅ تم استلام التكت بواسطة {interaction.user.mention}\n📝 الآن فقط {interaction.user.mention} يقدر يرد على هذا التكت.",
                color=discord.Color.green()
            )
            await interaction.response.send_message(embed=embed)
            
            log_channel = interaction.guild.get_channel(LOG_CHANNEL_ID)
            if log_channel:
                log_embed = discord.Embed(
                    title="📋 سجل التكت",
                    description=f"تم استلام التكت `{interaction.channel.name}` بواسطة {interaction.user.mention}",
                    color=discord.Color.blue(),
                    timestamp=datetime.datetime.now()
                )
                await log_channel.send(embed=log_embed)
        except discord.NotFound:
            pass
        except Exception as e:
            print(f"خطأ في استلام التكت: {e}")

    # --- إغلاق التكت ---
    @discord.ui.button(label="🔒 إغلاق التكت", style=discord.ButtonStyle.danger, custom_id="persistent:close_ticket")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            staff_role = interaction.guild.get_role(STAFF_ROLE_ID)
            if staff_role and staff_role not in interaction.user.roles:
                return await interaction.response.send_message("❌ هذا الإجراء للإدارة فقط.", ephemeral=True)
            
            await interaction.response.send_message("🔒 جاري إغلاق التكت...", ephemeral=True)
            
            # قراءة الـ topic لاستخراج opener_id و claimer_id
            # الصيغة: opener_id|claimer_id
            topic = interaction.channel.topic or ""
            original_opener = None
            claimer = None
            
            if "|" in topic:
                parts = topic.split("|")
                opener_id = parts[0]
                claimer_id = parts[1]
                
                if opener_id.isdigit():
                    original_opener = interaction.guild.get_member(int(opener_id))
                if claimer_id.isdigit():
                    claimer = interaction.guild.get_member(int(claimer_id))
            else:
                # التكت غير مستلم، استخدم الـ topic كـ opener_id فقط
                if topic.isdigit():
                    original_opener = interaction.guild.get_member(int(topic))
            
            # إرسال التقييم فقط إذا كان التكت مستلم من إداري
            if original_opener and claimer:
                try:
                    rating_embed = discord.Embed(
                        title="⭐ قيم تجربتك",
                        description=f"تم إغلاق تكتك `{interaction.channel.name}`.\nيرجى تقييم الخدمة التي تلقيتها من {claimer.display_name}:",
                        color=discord.Color.gold()
                    )
                    await original_opener.send(
                        embed=rating_embed,
                        view=RatingView(claimer, original_opener, interaction.channel.name, interaction.guild.id)
                    )
                except:
                    pass
            
            log_channel = interaction.guild.get_channel(LOG_CHANNEL_ID)
            if log_channel:
                log_embed = discord.Embed(
                    title="🔒 تم إغلاق التكت",
                    description=f"تم إغلاق `{interaction.channel.name}` بواسطة {interaction.user.mention}",
                    color=discord.Color.red(),
                    timestamp=datetime.datetime.now()
                )
                await log_channel.send(embed=log_embed)
            
            await interaction.channel.delete()
        except discord.NotFound:
            pass
        except Exception as e:
            print(f"خطأ في إغلاق التكت: {e}")

    # --- تغيير اسم التكت ---
    @discord.ui.button(label="✏️ تغيير الاسم", style=discord.ButtonStyle.secondary, custom_id="persistent:rename_ticket")
    async def rename_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.response.send_modal(RenameTicketModal())
        except discord.NotFound:
            pass

    # --- إضافة عضو للتكت ---
    @discord.ui.button(label="➕ إضافة عضو", style=discord.ButtonStyle.primary, custom_id="persistent:add_member")
    async def add_member(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            staff_role = interaction.guild.get_role(STAFF_ROLE_ID)
            if staff_role and staff_role not in interaction.user.roles:
                return await interaction.response.send_message("❌ هذا الإجراء للإدارة فقط.", ephemeral=True)
            
            await interaction.response.send_modal(AddMemberModal())
        except discord.NotFound:
            pass

    # --- حفظ المحادثة ---
    @discord.ui.button(label="📄 حفظ المحادثة", style=discord.ButtonStyle.secondary, custom_id="persistent:save_transcript")
    async def save_transcript(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            staff_role = interaction.guild.get_role(STAFF_ROLE_ID)
            if staff_role and staff_role not in interaction.user.roles:
                return await interaction.response.send_message("❌ هذا الإجراء للإدارة فقط.", ephemeral=True)
            
            await interaction.response.defer(ephemeral=True)
            
            messages = []
            async for message in interaction.channel.history(limit=100, oldest_first=True):
                timestamp = message.created_at.strftime("%Y-%m-%d %H:%M")
                messages.append(f"[{timestamp}] {message.author.display_name}: {message.content}")
            
            transcript = "\n".join(messages)
            file = discord.File(io.BytesIO(transcript.encode()), filename=f"transcript-{interaction.channel.name}.txt")
            
            log_channel = interaction.guild.get_channel(LOG_CHANNEL_ID)
            if log_channel:
                await log_channel.send(f"📄 محادثة التكت `{interaction.channel.name}`:", file=file)
            
            await interaction.followup.send("✅ تم حفظ المحادثة في روم السجلات.", ephemeral=True)
        except discord.NotFound:
            pass
        except Exception as e:
            print(f"خطأ في حفظ المحادثة: {e}")


# =========================================================
# ➕ نافذة إضافة عضو (Modal)
# =========================================================
class AddMemberModal(discord.ui.Modal, title="إضافة عضو للتكت"):
    member_id = discord.ui.TextInput(
        label="آيدي العضو",
        placeholder="مثال: 123456789012345678",
        min_length=17,
        max_length=20
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            member = interaction.guild.get_member(int(self.member_id.value))
            if not member:
                return await interaction.response.send_message("❌ لم يتم العثور على العضو.", ephemeral=True)
            
            await interaction.channel.set_permissions(member, read_messages=True, send_messages=True)
            await interaction.response.send_message(f"✅ تم إضافة {member.mention} للتكت.", ephemeral=False)
        except ValueError:
            await interaction.response.send_message("❌ آيدي غير صحيح.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ خطأ: {e}", ephemeral=True)


# =========================================================
# 🎫 لوحة فتح التكتات (Panel)
# =========================================================
class TicketPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="💸 بيع", style=discord.ButtonStyle.primary, custom_id="persistent:ticket_sell", emoji="💵")
    async def sell_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.response.send_modal(TicketModal("بيع"))
        except discord.NotFound:
            pass

    @discord.ui.button(label="🔧 دعم فني", style=discord.ButtonStyle.secondary, custom_id="persistent:ticket_support", emoji="🛠️")
    async def support_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.response.send_modal(TicketModal("دعم-فني"))
        except discord.NotFound:
            pass

    @discord.ui.button(label="📝 استفسار", style=discord.ButtonStyle.secondary, custom_id="persistent:ticket_inquiry", emoji="❓")
    async def inquiry_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.response.send_modal(TicketModal("استفسار"))
        except discord.NotFound:
            pass


# =========================================================
# 🤖 إعداد البوت
# =========================================================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

class MyBot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.synced = False

    async def setup_hook(self):
        self.add_view(TicketControlView())
        self.add_view(TicketPanelView())

bot = MyBot()


# =========================================================
# 📡 الأحداث (Events)
# =========================================================
@bot.event
async def on_ready():
    print(f"✅ البوت شغال: {bot.user}")
    print(f"📊 متصل بـ {len(bot.guilds)} سيرفر")
    
    if not bot.synced:
        try:
            guild = discord.Object(id=GUILD_ID)
            bot.tree.copy_global_to(guild=guild)
            await bot.tree.sync(guild=guild)
            print("✅ تم مزامنة الأوامر")
            bot.synced = True
        except Exception as e:
            print(f"❌ خطأ في المزامنة: {e}")
    
    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.watching, name="التذاكر 🎫")
    )


@bot.event
async def on_message(message):
    if message.author.bot:
        return
    
    for keyword, response in AUTO_RESPONSES.items():
        if keyword in message.content:
            await message.reply(response)
            break


# =========================================================
# ⚡ الأوامر (Slash Commands)
# =========================================================
@bot.tree.command(name="setup", description="إرسال لوحة فتح التكتات")
@app_commands.checks.has_permissions(administrator=True)
async def setup_panel(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🎫 نظام التذاكر",
        description="اختر نوع التذكرة التي تريد فتحها:\n\n"
                    "💰 **شراء** - لطلبات الشراء\n"
                    "💸 **بيع** - لطلبات البيع\n"
                    "🔧 **دعم فني** - للمشاكل التقنية\n"
                    "📝 **استفسار** - للأسئلة العامة",
        color=discord.Color.blue()
    )
    embed.set_footer(text="اضغط على الزر المناسب لفتح تذكرة")
    
    await interaction.channel.send(embed=embed, view=TicketPanelView())
    await interaction.response.send_message("✅ تم إرسال لوحة التذاكر!", ephemeral=True)


@bot.tree.command(name="top", description="عرض أفضل الإداريين")
async def top_staff_cmd(interaction: discord.Interaction):
    top_list = get_top_staff()
    
    if not top_list:
        return await interaction.response.send_message("❌ لا توجد بيانات حتى الآن.", ephemeral=True)
    
    embed = discord.Embed(
        title="🏆 أفضل الإداريين",
        color=discord.Color.gold()
    )
    
    medals = ["🥇", "🥈", "🥉"]
    description = ""
    for i, (user_id, points) in enumerate(top_list):
        medal = medals[i] if i < 3 else f"**{i+1}.**"
        member = interaction.guild.get_member(user_id)
        name = member.mention if member else f"مستخدم ({user_id})"
        description += f"{medal} {name} - **{points}** نقطة\n"
    
    embed.description = description
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="addpoints", description="إضافة نقاط لإداري")
@app_commands.checks.has_permissions(administrator=True)
async def add_points_cmd(interaction: discord.Interaction, member: discord.Member, amount: int):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO staff_points (user_id, points) VALUES (?, 0)", (member.id,))
    c.execute("UPDATE staff_points SET points = points + ? WHERE user_id = ?", (amount, member.id))
    conn.commit()
    conn.close()
    
    await interaction.response.send_message(f"✅ تم إضافة **{amount}** نقطة لـ {member.mention}")


@bot.tree.command(name="ping", description="اختبار استجابة البوت")
async def ping_cmd(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)
    await interaction.response.send_message(f"🏓 Pong! `{latency}ms`")


# =========================================================
# 🚀 تشغيل البوت
# =========================================================
if TOKEN:
    bot.run(TOKEN)
else:
    print("❌ لم يتم العثور على DISCORD_TOKEN. أضف التوكن في Secrets.")
