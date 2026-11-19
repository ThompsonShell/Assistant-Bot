# Ochiq savollar (Phase 0, reja v2 bo'yicha yangilangan)

Sana: 2026-11-19. Har bir savolga mening tavsiyam bor; "ha" desangiz ham bo'ladi.
Phase 1 kodi yozildi (pastdagi "Holat" jadvaliga qarang). Ochiq savollar shu faylda qoldi.

## Holat (2026-11-19, amalga oshirilgandan keyin)

Siz Phase 0 ni tasdiqlash o'rniga to'g'ridan-to'g'ri amalga oshirishni buyurdingiz, shuning uchun quyidagilar qilindi. Savollarning o'zi o'chirilmadi, pastda holati bilan turibdi.

| Savol | Holat |
|---|---|
| Q2 buyruq nomlari | Hech qaysi eski buyruq olib tashlanmadi. `/cards`, `/addword`, `/exam` aliaslari **qo'shilmadi**. Kerak bo'lsa ayting |
| Q4 `/diary` | Qilindi: `/diary` = bugungi ro'yxat (input, output, so'zlar, rasm). Eski ko'rinish: `/diary show`, `/diary week`. 7 qadamli matn oqimi **hali yo'q**, o'rniga `/learned` va `/recall` |
| Q15 rasmni Claude'ga berish | Kod yozildi (API va CLI yo'llari), **CLI yo'li haqiqiy loginda hali sinalmagan**. 10 daqiqalik sinov hamon kerak |
| Q16 rasm saqlash | Qilindi: `data/diary_photos/`, gitignore, 600 ruxsat |
| Q17 sana | Qilindi: izoh > `/date` > sahifa > bugun, 48 soat, "Sana noto'g'ri" tugmasi |
| Q18 matplotlib | Qo'shilmadi (Phase 7) |
| Q19 Phase 1 hajmi | Siz hammasini birdan so'radingiz, shuning uchun 1a va 1b birga qilindi |
| Q1, Q3, Q5, Q6, Q7-Q14 | **Ochiq**. Eng muhimi: Q1 (repo hamon public; rasmlar gitga tushmaydi, lekin `docs/` va kelajakdagi fayllar ochiq bo'ladi), Q5 (eslatmalar endi kuniga 8 tagacha), Q6 (`DISPLAY_TIMEZONE`) |

Yangi savollar:

**Q20. "Faol kun" ta'rifi.** Hozir faol kun = tasdiqlangan qog'oz yozuv YOKI matnli kundalikda input/output bor. Matnli kun daqiqa qo'shmaydi, lekin ketma-ketlik va barqarorlikka kiradi. Faqat qog'ozni hisoblash kerakmi?

**Q21. "So'zlar 3 ta" qoidasi.** Kun to'liq hisoblanishi uchun input + output + 3 ta yangi so'z kerak (shablondagi "3 WORDS"). Rejada kuniga 8-10 yangi karta ko'rsatilgan. 3 ta yetarlimi?

**Q22. Yil oynasi.** `/stats yil` 2026-11-20 dan boshlab 365 kunlik oyna. "Kalendar yili" varianti `/settings` bilan keladi, u hali yo'q.

## A. Phase 1 dan oldin kerak

**Q1. Repo ochiq (public), reja esa "private" deb faraz qiladi.**
`ThompsonShell/Assistant-Bot` hozir hamma uchun ochiq. O'rganish ma'lumotlari (`lifeos.db`) gitga tushmaydi, lekin `docs/`, `data/` ichidagi hamma narsa ommaviy bo'ladi (PDF, reja, xatolar jurnali).
Reja v2 da bu yanada muhim: qo'lyozma **rasmlar** va ularning matni shaxsiy ma'lumot. Tavsiya: reponi **private** qiling (GitHub -> Settings -> Danger zone -> Change visibility). PDF va shaxsiy fayllar uchun `data/` papkasini `.gitignore` ga qo'shaman. Qaror sizniki.

**Q2. Mavjud o'rganish moduli bilan reja ustma-ust tushadi.**
Reja kelishidan oldin men quyidagilarni qurgan edim: `/word /review /words /learned /recall /diary /quiz /drill /read /summary /tried /topic /readlog`. Rejada esa `/cards /addword /exam /diary(oqim) /lesson /hint ...`.
Tavsiya: **yangi nomlar asosiy**, eskilari alias bo'lib qoladi (hech narsa buzilmaydi). Ya'ni `/cards` = `/review`, `/addword` = `/word`, `/exam` = `/quiz`.

**Q3. SRS algoritmi: SM-2 (hozir) yoki Leitner 1/3/7/14/30 (reja)?**
Reja Leitner so'raydi. Hozirgi `vocab_cards` SM-2 maydonlari bilan, lekin haqiqiy ma'lumot hali deyarli yo'q.
Tavsiya: **Leitner** (oddiy, bashorat qilinadigan, rejaga mos) va `srs.py` ni almashtirish. Qayta tiklash kerak bo'lmaydi.

**Q4. Kundalik endi qog'oz + rasm; `/diary` zaxira yo'l.**
Reja v2: asosiy kiritish usuli qog'ozdagi sahifa rasmi, `/diary` matn oqimi faqat qog'ozsiz kunlar uchun. Hozir `/diary` bugungi yozuvni ko'rsatadi, `/learned` va `/recall` yozadi.
Tavsiya: `/diary` = matn oqimi (7 qadam), ko'rish uchun `/diary show`, `/learned` va `/recall` tez yo'l bo'lib qoladi. Jadvalga ustunlar (`mistakes, words, question, tomorrow, source`) migratsiya bilan qo'shiladi, eski yozuvlar saqlanadi. Bot oqim uchun hozircha holat saqlamaydi, kichik "suhbat holati" jadvali kerak (rasm tasdiqlash oqimi uchun ham shu kerak).

**Q5. Proaktiv xabarlar "kuniga 2 tadan ko'p emas" qoidasiga zid.**
Hozir kuniga **6 tagacha** xabar kelishi mumkin: 08:00 brief, 09/14/20 kartochkalar, 18:00 reading, 19:00 imtihon, 21:00 kundalik.
Tavsiya: faqat **08:00** (brief ichida kartochkalar soni, bugungi reading, imtihon eslatmasi) va **21:00** (qog'oz kundalik rasmini so'rash). 22:00 da bitta yumshoq eslatma. Qolgan eslatmalarni o'chiraman va `/settings` ga o'tkazaman. Rozimisiz?

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

## B2. Reja v2 (qog'oz kundalik) bilan kelgan yangi savollar

**Q15. Rasmni Claude'ga qanday beramiz? (eng muhim noma'lum)**
Bot hozir Claude'ga faqat matn beradi. `claude -p` (2.1.328) da `--input-format stream-json` va `--allowedTools` bor, rasm uchun ikki ehtimoliy yo'l: (a) rasmni stream-json xabari ichida yuborish, (b) faqat `Read` vositasiga bitta vaqtinchalik faylni ruxsat berish. **Men hech birini sinab ko'rmadim**: sandbox'da Claude login yo'q. Ishlamasa, yagona ishonchli yo'l API kalit (rasmni qo'llab-quvvatlaydi, lekin pullik).
Tavsiya: Phase 1 boshlanishidan oldin 10 daqiqalik sinov: kompyuteringizda bitta qo'lyozma sahifa rasmini `claude -p` ga berib ko'rish. Sinov skriptini men yozib beraman, natijaga qarab yo'l tanlaymiz. Qo'lyozmani (o'zbek + ingliz aralash) o'qish sifatini ham shu sinov ko'rsatadi.

**Q16. Rasmlar qayerda saqlanadi?**
Hozir saqlash papkasi yo'q. Tavsiya: `data/diary_photos/` (gitignore), faqat sizning kompyuteringizda. Rasmlar Claude'ga yuboriladi (reja buni qayd etadi). `/delete_entry <sana>` rasmni va yozuvni o'chiradi. Q1 (repo private) bilan bog'liq.

**Q17. Qog'oz shabloni va sana.**
Shablon aniq (DATE, TIME, LEARNED, ...). Savol: sana yo'q yoki o'qib bo'lmasa bot nima qiladi? Tavsiya: reja bo'yicha so'raydi ("Wrong date" tugmasi), hech qachon taxmin qilmaydi. Orqaga qaytarib kiritish 48 soatgacha (`/date` yoki caption), aniqlandimi?

**Q18. Grafiklar uchun `matplotlib` qo'shilsinmi?**
`/stats year` va `/calendar` (issiqlik xaritasi) rasm chizadi. `requirements.txt` da yo'q. Qo'shish ~50 MB, lekin faqat Phase 7 da kerak. Tavsiya: Phase 7 da qo'shamiz, Phase 1 da faqat matnli statistika.

**Q19. Phase 1 hajmi 90 daqiqalik yakshanba sessiyasiga sig'maydi.**
Reja v2 da Phase 1 = rasm qabul qilish + vision + tasdiqlash oqimi + eslatmalar + `/settings` + `/stats` + `/streak`. Reja 2-qism: bot ishlab chiqish faqat yakshanba, 90 daqiqagacha (D03, 22-noyabr).
Tavsiya: Phase 1 ni ikkiga bo'lish. **1a** (22-noyabr): matnli `/diary` oqimi, 08:00/21:00 eslatmalari, `/settings`, `/stats` va `/streak` (tasdiqlangan yozuvlardan). **1b** (keyingi yakshanba): rasm + vision + tasdiqlash. Shunda 1a rasm sinoviga (Q15) bog'liq bo'lmaydi.

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
