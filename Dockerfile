FROM python:3.12-slim

WORKDIR /app

# تثبيت التبعيات
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# نسخ التطبيق
COPY . .

# إنشاء مجلد البيانات
RUN mkdir -p data

EXPOSE 8000

# استخدام Gunicorn مع Uvicorn workers للإنتاج
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
