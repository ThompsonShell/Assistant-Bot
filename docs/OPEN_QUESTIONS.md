# Ochiq savollar (Phase 0)

Sana: 2026-11-19. Har bir savolga mening tavsiyam bor; "ha" desangiz ham bo'ladi.
Phase 1 kodidan oldin **A guruhi** javob olishi kerak.

## A. Phase 1 dan oldin kerak

**Q1. Repo ochiq (public), reja esa "private" deb faraz qiladi.**
`ThompsonShell/Assistant-Bot` hozir hamma uchun ochiq. O'rganish ma'lumotlari (`lifeos.db`) gitga tushmaydi, lekin `docs/`, `data/` ichidagi hamma narsa ommaviy bo'ladi (PDF, reja, xatolar jurnali).
Tavsiya: reponi **private** qiling (GitHub -> Settings -> Danger zone -> Change visibility). PDF va shaxsiy fayllar uchun `data/` papkasini `.gitignore` ga qo'shaman. Qaror sizniki.

**Q2. Mavjud o'rganish moduli bilan reja ustma-ust tushadi.**
Reja kelishidan oldin men quyidagilarni qurgan edim: `/word /review /words /learned /recall /diary /quiz /drill /read /summary /tried /topic /readlog`. Rejada esa `/cards /addword /exam /diary(oqim) /lesson /hint ...`.
Tavsiya: **yangi nomlar asosiy**, eskilari alias bo'lib qoladi (hech narsa buzilmaydi). Ya'ni `/cards` = `/review`, `/addword` = `/word`, `/exam` = `/quiz`.

**Q3. SRS algoritmi: SM-2 (hozir) yoki Leitner 1/3/7/14/30 (reja)?**
Reja Leitner so'raydi. Hozirgi `vocab_cards` SM-2 maydonlari bilan, lekin haqiqiy ma'lumot hali deyarli yo'q.
Tavsiya: **Leitner** (oddiy, bashorat qilinadigan, rejaga mos) va `srs.py` ni almashtirish. Qayta tiklash kerak bo'lmaydi.

**Q4. `/diary` ma'nosi o'zgaradi.**
Hozir `/diary` bugungi yozuvni ko'rsatadi, `/learned` va `/recall` yozadi. Reja `/diary` ni 7 qadamli oqim qiladi (learned / input / output / mistakes / 3 words / question / tomorrow).
Tavsiya: `/diary` = oqim, ko'rish uchun `/diary show`, `/learned` va `/recall` tez yo'l bo'lib qoladi. Jadvalga yangi ustunlar migratsiya bilan qo'shiladi (eski yozuvlar saqlanadi). Bot oqim uchun hozircha holat saqlamaydi, shu uchun kichik "suhbat holati" jadvali kerak bo'ladi.

**Q5. Proaktiv xabarlar "kuniga 2 tadan ko'p emas" qoidasiga zid.**
Hozir kuniga **6 tagacha** xabar kelishi mumkin: 08:00 brief, 09/14/20 kartochkalar, 18:00 reading, 19:00 imtihon, 21:00 kundalik.
Tavsiya: faqat **08:00** (brief ichida kartochkalar soni, bugungi reading, imtihon eslatmasi) va **21:00** (kundalik). 22:00 da bitta yumshoq eslatma. Qolgan eslatmalarni o'chiraman va `/settings` ga o'tkazaman. Rozimisiz?

**Q6. Vaqt zonasi.**
Koddagi standart `UTC`. Eslatmalar 08:00 / 21:00 **Toshkent** vaqtida bo'lishi uchun `.env` da `DISPLAY_TIMEZONE=Asia/Tashkent` bo'lishi shart. `.env` ni men o'qimayman. Iltimos, o'zingiz tekshiring.

## B. Phase 2-3 uchun

**Q7. PDF "A Resource for Reading & Words": yo'li va turi.**
Fayl yo'lini bering yoki `data/` ga qo'ying. Matn qatlami bormi yoki skaner qilinganmi (nusxa ko'chirib bo'ladimi)? Skaner bo'lsa, so'zlarni ajratish OCR talab qiladi va ishonchsizroq bo'ladi. 1100 so'z `queue_words` ga tushadi, kuniga 8-10 tasi faollashadi.

**Q8. `/addword <so'z>`: ta'rifni kim beradi?**
Variant 1: faqat so'z yozasiz, Claude ta'rif va misol yaratadi (har safar AI chaqiruvi). Variant 2: o'zingiz yozasiz (`so'z - ma'no`).
Tavsiya: ikkalasi. Ma'no yozmasangiz, Claude to'ldiradi.

**Q9. Imtihon savollari va qo'lda yozish qoidasi.**
Reja: bot sizning o'rningizga kod yozmasligi kerak, `/hint` 4 bosqichda. Lekin hozir oddiy matn Claude'ga ketadi va u to'liq yechim yozib beradi.
Tavsiya: "o'qish rejimi" qo'shish (`/settings` dan yoqiladi): rejim yoqilganda to'liq yechim so'ralsa, bot avval `/hint` bosqichiga yo'naltiradi, to'liq yechim faqat "yechimni ko'rsat" deb aniq so'raganda.

## C. Keyingi fazalar uchun

**Q10. Jira: yozish ruxsati.**
Hozirgi `/jira` **faqat o'qiydi** (bu ataylab qilingan edi). Reja 2-qism 6-bo'lim esa Jira'da Epic/Story/Task yaratadi va yangilaydi.
Kerak: (a) yozishga ruxsat berasizmi, (b) loyiha kaliti, (c) issue turlari (Epic, Story, Task, Sub-task mavjudmi), (d) API token ruxsatlari. Rejaga ko'ra Jira'da **birinchi marta hech narsa yaratishdan oldin sizdan so'rayman**. Import Phase 4 dan keyin.

**Q11. Claude chaqiruvi: obuna (hozir) yoki API kalit.**
Hozir har bir AI chaqiruvi `claude -p` jarayonini ishga tushiradi (bir necha soniya, Pro limitidan sarflanadi). Imtihon yaratish, yozma va og'zaki fikr-mulohaza ko'p chaqiruv talab qiladi. Anthropic hujjatlari mahsulotlar uchun API kalitni tavsiya qiladi.
Tavsiya: hozircha obuna bilan davom etamiz, limit tugasa yoki sekin bo'lsa API kalitga o'tamiz. Bu qaror hozir bloklamaydi.

**Q12. `/speak`: nutqni matnga aylantirish (STT).**
Hozir bot ovozli xabarni umuman o'qimaydi. Variantlar: (a) faqat saqlash (stub), (b) pullik STT API, (c) kompyuteringizda bepul `faster-whisper` (kichik model CPU'da ishlaydi, lekin sekinroq). Narx va maxfiylik bo'yicha men (c) ni tavsiya qilaman, lekin avval (a) bilan boshlash mumkin. Phase 5 da hal qilamiz.

**Q13. Server: bot faqat noutbuk yoqilganda ishlaydi.**
08:00 va 21:00 eslatmalari uchun jarayon doim ishlashi kerak. Reja bo'yicha deploy (Docker, VPS) Phase 7 da va bu sizning o'quv mashqingiz. Shu paytgacha noutbuk yoqilgan bo'lishi kerakmi yoki vaqtincha Railway ishlatamizmi? Repoda hozir Railway/VPS sozlamalari yo'q.

**Q14. Sizdan kutilayotgan ma'lumotlar (rejada TODO).**
- Ish vazifalari ro'yxati, muddatlar, kuniga necha soat va qaysi vaqtda (2-qism 5-bo'lim).
- IELTS kitoblari uchun audio bormi.
- Parallel o'qish uchun ustozlar tavsiyasi (oldin so'ragandim).

## D. Eslatma (savol emas)

Reja 2-qism 3-bo'limiga ko'ra bot ishlab chiqish faqat yakshanba, 90 daqiqagacha. Phase 0 reja bo'yicha D01 (juma) uchun belgilangan edi, men uni bugun bajardim, ertangi slot bo'sh qoladi.
