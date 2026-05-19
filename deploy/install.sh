#!/bin/bash
# نصب التطبيق على سيرفر Ubuntu/Debian
set -e

echo "=== EGX Analyzer Deployment ==="

# 1. تحديث النظام
sudo apt update && sudo apt upgrade -y

# 2. تثبيت Python و nginx
sudo apt install -y python3 python3-pip python3-venv nginx certbot python3-certbot-nginx

# 3. إنشاء مجلد التطبيق
sudo mkdir -p /opt/egx-analyzer
sudo chown $USER:$USER /opt/egx-analyzer

# 4. نسخ الملفات (افترض إن الملفات في المسار الحالي)
cp -r . /opt/egx-analyzer/
cd /opt/egx-analyzer

# 5. إنشاء بيئة افتراضية وتثبيت المكتبات
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 6. إنشاء مجلد البيانات
mkdir -p data

# 7. إعداد متغيرات البيئة
cat > .env << EOF
EGX_SECRET_KEY=$(openssl rand -hex 32)
EGX_CORS_ORIGINS=https://your-domain.com
EGX_DB_PATH=/opt/egx-analyzer/data/egx_v2.db
EOF

# 8. نصب systemd service
sudo cp deploy/egx-analyzer.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable egx-analyzer
sudo systemctl start egx-analyzer

# 9. إعداد nginx
sudo cp deploy/nginx.conf /etc/nginx/sites-available/egx-analyzer
sudo ln -sf /etc/nginx/sites-available/egx-analyzer /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

echo ""
echo "=== تم النصب بنجاح ==="
echo "شغّل: sudo certbot --nginx -d your-domain.com"
echo "عشان تفعّل HTTPS"
