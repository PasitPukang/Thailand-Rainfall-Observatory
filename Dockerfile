FROM apache/airflow:2.11.2-python3.12
COPY requirements.txt /tmp/weather-requirements.txt
RUN pip install --no-cache-dir -r /tmp/weather-requirements.txt
