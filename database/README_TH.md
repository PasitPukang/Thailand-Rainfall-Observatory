# วิธีดูข้อมูลทั้งหมดใน PostgreSQL

ฐานข้อมูล `weather` เก็บข้อมูลสภาพอากาศของ 77 จังหวัดและผลการทำงานของ Airflow ใน 5 ตาราง:

| ตาราง | เนื้อหา |
| --- | --- |
| `dim_province` | ชื่อและพิกัดจังหวัด |
| `fact_weather_hourly` | ข้อมูลฝน อุณหภูมิ ความชื้น และลมรายชั่วโมง |
| `mart_weather_daily` | ข้อมูลสรุปรายวันสำหรับ Power BI |
| `etl_batch` | ประวัติการโหลดข้อมูล |
| `pipeline_run_audit` | สถานะรอบ Airflow และจำนวนแถวที่เพิ่มหรืออัปเดตจริง |

## เปิดผ่านโปรแกรมจัดการ PostgreSQL

ใช้ pgAdmin หรือ DBeaver แล้วสร้างการเชื่อมต่อด้วยข้อมูลนี้:

| ช่อง | ค่า |
| --- | --- |
| Host | `127.0.0.1` |
| Port | `55432` |
| Database | `weather` |
| Username | `airflow` |
| Password | ค่า `POSTGRES_PASSWORD` ในไฟล์ `.env` ของโครงการ |

เปิด Docker Desktop และบริการของโครงการก่อนเชื่อมต่อ: ในโฟลเดอร์โครงการรัน `docker compose up -d` หากบริการยังไม่ทำงาน รหัสผ่านนี้ใช้กับฐานข้อมูลเฉพาะเครื่องตามการตั้งค่าของโครงการ และไม่เก็บรหัสผ่านจริงไว้ใน GitHub

ในหน้าต่าง SQL ลองคำสั่งเหล่านี้:

```sql
-- จำนวนแถวในแต่ละตาราง
SELECT 'dim_province' AS table_name, COUNT(*) FROM dim_province
UNION ALL SELECT 'fact_weather_hourly', COUNT(*) FROM fact_weather_hourly
UNION ALL SELECT 'mart_weather_daily', COUNT(*) FROM mart_weather_daily
UNION ALL SELECT 'etl_batch', COUNT(*) FROM etl_batch;

-- สถานะรอบ Airflow ล่าสุดและจำนวนข้อมูลที่เพิ่มจริง
SELECT run_id, status, target_date, new_hourly_rows,
       updated_hourly_rows, new_daily_rows, message
FROM pipeline_run_audit
ORDER BY finished_at DESC
LIMIT 20;

-- ดูข้อมูลรายชั่วโมง 100 แถวล่าสุด พร้อมชื่อจังหวัด
SELECT p.province_name, h.*
FROM fact_weather_hourly h
JOIN dim_province p USING (province_id)
ORDER BY h.weather_time DESC, h.province_id
LIMIT 100;

-- ดูข้อมูลรายวันของจังหวัดและช่วงเวลาที่สนใจ
SELECT p.province_name, d.*
FROM mart_weather_daily d
JOIN dim_province p USING (province_id)
WHERE p.province_name = 'กรุงเทพมหานคร'
  AND d.weather_date BETWEEN DATE '2026-01-01' AND DATE '2026-01-31'
ORDER BY d.weather_date;
```

ตารางรายชั่วโมงมีหลายล้านแถว โปรแกรมฐานข้อมูลจะแสดงทีละหน้า ส่วนไฟล์ `export/fact_weather_hourly_YYYY.csv` แยกทุกปีเพื่อเปิดดูข้อมูลทั้งหมด โดยแต่ละไฟล์มีแถวน้อยกว่าขีดจำกัดของ Excel หากต้องการส่งออกใหม่หลัง Airflow เพิ่มข้อมูล ให้รัน `python database/export_all_hourly.py` ในโฟลเดอร์โครงการ
