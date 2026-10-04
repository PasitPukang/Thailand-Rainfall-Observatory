# Power BI dashboard: ฝนตกหนักและสภาพอากาศรายจังหวัด

ไฟล์รายงานที่พร้อมเปิดคือ [Thailand_Rainfall_2018_2026.pbix](Thailand_Rainfall_2018_2026.pbix) ข้อมูลฝังในรายงานครอบคลุม 1 มกราคม 2018 ถึง **26 กันยายน 2026** (ปี 2026 ยังไม่ครบปี) หน้า Overview จัดการ์ด 3 รายการไว้ด้านบน กราฟฝนสะสมรายปีและอันดับจังหวัดไว้ด้านล่าง พร้อมตัวเลือกจังหวัดแบบ dropdown สำหรับกรองทั้งหน้า ไฟล์ [Thailand_Rainfall_2018_2026.pbip](Thailand_Rainfall_2018_2026.pbip) และโฟลเดอร์ Report/SemanticModel เป็นโครงการต้นฉบับสำหรับแก้ layout เพิ่มเติม

รายงานอ่าน `export/dim_province.csv` และ `export/mart_weather_daily.csv` ในโฟลเดอร์นี้ หลัง Airflow ทำงาน CSV จะถูกสร้างใหม่จาก PostgreSQL แล้วให้กด **Home → Refresh** ใน Power BI Desktop เพื่ออัปเดตภาพ ตัวเลือกจังหวัดอยู่มุมขวาบนของหน้า เลือก **All** เพื่อดูทุกจังหวัด หรือเลือกจังหวัดหนึ่งเพื่อดูสถิติที่จุดตัวแทนของจังหวัดนั้น Power BI Service ต้องมีการตั้งค่าแหล่งข้อมูลและการรีเฟรชเพิ่มเติมก่อนเผยแพร่

**หลัง clone ไปเครื่องอื่น:** PBIX มีข้อมูลฝังอยู่ จึงเปิดดูได้ทันที แต่ก่อน Refresh ให้เปิด **File → Options and settings → Data source settings → Change Source** แล้วเลือก `powerbi/export/dim_province.csv` และ `powerbi/export/mart_weather_daily.csv` ในโฟลเดอร์ที่ clone ใหม่ แหล่งข้อมูลใน PBIP เป็นพาธตัวอย่างและต้องแก้สองตารางใน Power Query ก่อนโหลดข้อมูล ไฟล์ PBIX และ CSV ชุดใหญ่เก็บด้วย Git LFS; ให้รัน `git lfs pull` หากเห็นเพียงไฟล์ pointer

## ปรับแต่งหรือสร้างรายงานเพิ่มเติม

1. หลังโหลดข้อมูล ให้รัน `python -m pipeline.cli export-powerbi` เพื่อสร้าง CSV สองไฟล์ใน `powerbi/export/` หรือเชื่อม PostgreSQL ที่ `localhost:55432`, ฐานข้อมูล `weather`, ผู้ใช้ `airflow`, รหัสผ่านจาก `POSTGRES_PASSWORD` ใน `.env` แล้วเลือกตาราง `dim_province` และ `mart_weather_daily`.
2. ใน Power BI Desktop ตั้งความสัมพันธ์ `dim_province[province_id]` (หนึ่ง) → `mart_weather_daily[province_id]` (หลาย) โดยให้กรองทางเดียว.
3. สร้าง Date table ด้วยสูตรด้านล่าง แล้วเชื่อม `'Date'[Date]` → `mart_weather_daily[weather_date]`.
4. เพิ่ม Measures จาก [measures.dax](measures.dax) ทีละสูตร หากต้องการขยายรายงาน
5. ใช้ `theme.json` ผ่านเมนู View → Themes → Browse for themes เพื่อใช้สีเดียวกันทั้งรายงาน

```dax
Date =
ADDCOLUMNS(
    CALENDAR(DATE(2018, 1, 1), MAX(mart_weather_daily[weather_date])),
    "Year", YEAR([Date]),
    "MonthNo", MONTH([Date]),
    "YearMonth", FORMAT([Date], "YYYY-MM")
)
```

## ตัวอย่างการขยายหน้า 1: ภาพรวม

- ตัวกรอง: ปีและจังหวัด
- การ์ด: `Rainfall (mm)`, `Heavy rain days`, `Very heavy rain days`, `Average temperature (C)`
- กราฟเส้น: `YearMonth` กับ `Rainfall (mm)`
- แผนที่จุด: `dim_province[latitude]`, `dim_province[longitude]`; สีหรือขนาดตาม `Heavy rain days`
- แผนภูมิแท่ง: 10 จังหวัดที่มี `Heavy rain days` สูงสุด

## ตัวอย่างการขยายหน้า 2: แนวโน้มรายจังหวัด

- กราฟเส้น: ปี เทียบจำนวนวันฝนหนัก แยกจังหวัด
- Heatmap ด้วย Matrix: แถวเป็นจังหวัด คอลัมน์เป็นเดือน ค่าเป็น `Rainfall (mm)`
- ตาราง: จังหวัด, ปี, ฝนรวม, วันฝนหนัก, ค่าสูงสุดรายวัน

## ความหมายของข้อมูล

แต่ละจังหวัดมี **จุดพิกัดตัวแทนหนึ่งจุด** จาก [ชุดพิกัดจังหวัด](https://github.com/dataengineercafe/thailand-province-latitude-longitude) ไม่ใช่ค่าเฉลี่ยทุกพื้นที่ในจังหวัด ข้อมูล ERA5 เป็นข้อมูลสภาพอากาศจากแบบจำลองย้อนหลัง ไม่ใช่การอ่านจากสถานีตรวจวัด และไม่ได้เป็นข้อมูลพยากรณ์หรือน้ำท่วมจริง

เกณฑ์ `heavy` คือฝนสะสมในวันตามเวลาไทย ≥35.1 มม. และ `very_heavy` ≥90.1 มม. ตาม [เกณฑ์ฝนของกรมอุตุนิยมวิทยา](https://www.tmd.go.th/info/%E0%B9%80%E0%B8%81%E0%B8%93%E0%B8%91%E0%B8%AD%E0%B8%B2%E0%B8%81%E0%B8%B2%E0%B8%A8) ซึ่งนำมาประยุกต์กับข้อมูลแบบจำลองและวันปฏิทินไทย

สำหรับการเผยแพร่ข้อมูลผ่าน Power BI Service โปรดตรวจสอบสิทธิ์ใช้งานและวิธีรีเฟรชของบัญชีที่ใช้ หากเชื่อม PostgreSQL ในเครื่อง ต้องตั้งค่า gateway หรือใช้ฐานข้อมูลที่ Service เข้าถึงได้
