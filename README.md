<<<<<<< HEAD
# Mycompany_platform_excel
The platform processes a large Excel table containing accountants and their clients. It automatically generates a downloadable ZIP file, where each accountant receives a separate Excel file that includes only their respective clients.
=======
# מערכת עיבוד דוחות רו"ח / Accountant Reports Processing System

מערכת פשוטה לעיבוד קבצי Excel וחלוקתם לפי רו"ח עם ממשק עברי.

A simple system for processing Excel files and splitting them by accountant with Hebrew interface.

## תכונות / Features

- 📁 העלאת קבצי Excel (.xlsx)
- 🔍 זיהוי אוטומטי/ממוזג של שמות רו"ח (כולל מיזוג שמות דומים בפאזי)
- 📊 שמירה על עמודות ספציפיות בלבד בסדר קבוע
- 📦 יצירת קובץ ZIP עם קובץ Excel לכל רו"ח וקובץ mapping.csv
- 🌐 ממשק עברי מלא (RTL)
- ⚡ עיבוד בזיכרון ללא שמירה קבועה

## התקנה מקומית / Local Run

```bash
python -m pip install -r requirements.txt
python app.py  # השרת יאזין על 0.0.0.0:7860
```

פתח בדפדפן: `http://127.0.0.1:7860`

## שימוש ע"י הלקוח / Client Usage
1. גלוש לכתובת השרת (localhost:7860).
2. לחץ על "בחר קובץ Excel", ובחר קובץ `.xlsx` עם העמודות הנדרשות.
3. לחץ "העלה ועבד".
4. הדפדפן יוריד קובץ ZIP המכיל:
   - קובץ Excel אחד לכל רו"ח ממוזג (על בסיס מיזוג שמות דומים)
   - קובץ `mapping.csv` המציג את השיוכים: original → canonical

## עמודות נדרשות / Required Columns
- חודש חיוב
- תאריך חיוב
- שם העסק
- שם
- משפחה
- אימייל
- טלפון
- סוג עסקה
- סוג תשלום
- סכום
- עמלת אשראי
- מע"מ
- להעברה
- תיאור התשלום

## שגיאות / Error Handling
- 400: עמודות חסרות או בעיית אימות
- 415: סוג קובץ לא נתמך (רק .xlsx)
- 500: שגיאה כללית

## טכנולוגיות / Tech
- Backend: Flask, pandas, openpyxl, rapidfuzz
- Encoding: UTF-8
>>>>>>> 0bd80cd (First with basic)
