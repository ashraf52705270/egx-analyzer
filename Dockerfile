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

# استخدام Uvicorn مع PORT ديناميكي (يدعم Railway)
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
