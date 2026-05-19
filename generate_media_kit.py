from fpdf import FPDF
from pathlib import Path

pdf = FPDF(orientation='P', unit='mm', format='A4')
pdf.add_font('Cairo', '', 'C:\Windows\Fonts\Tahoma.ttf', uni=True)
pdf.add_font('Cairo', 'B', 'C:\Windows\Fonts\Tahomabd.ttf', uni=True)
pdf.set_auto_page_break(auto=True, margin=15)

# Page 1
pdf.add_page()
pdf.set_fill_color(26, 26, 46)
pdf.rect(0, 0, 210, 60, 'F')
pdf.set_y(15)
pdf.set_text_color(255, 255, 255)
pdf.set_font('Cairo', 'B', 26)
pdf.cell(0, 12, 'EGX Analyzer', align='C')
pdf.ln(14)
pdf.set_font('Cairo', '', 11)
pdf.set_text_color(200, 200, 200)
pdf.cell(0, 7, 'منصة تحليل البورصة المصرية - اكثر من 300 سهم متاح', align='C')
pdf.ln(10)
pdf.set_fill_color(255, 215, 0)
pdf.set_text_color(26, 26, 46)
pdf.set_font('Cairo', 'B', 10)
pdf.cell(0, 8, 'عرض رعاية اعلانية', align='C', fill=True)

pdf.ln(15)
# المساحات
pdf.set_text_color(26, 26, 46)
pdf.set_font('Cairo', 'B', 14)
pdf.cell(0, 10, 'المساحات الاعلانية المتاحة', ln=True)
pdf.ln(4)

ads = [
    ('البنر العلوي', 'تحت الهيدر الرئيسي - يظهر في كل صفحات الموقع', '728x90 بكسل'),
    ('البنر السفلي (Footer)', 'اسفل الموقع - يظهر في كل الصفحات', '728x70 بكسل'),
    ('الشريط الجانبي', 'في القائمة الجانبية - يظهر اثناء التصفح', '300x250 بكسل'),
]
pdf.set_font('Cairo', 'B', 11)
for name, desc, size in ads:
    pdf.set_fill_color(248, 249, 250)
    pdf.set_text_color(26, 26, 46)
    x0 = pdf.get_x()
    w = 170
    pdf.rect(x0, pdf.get_y(), w, 22, 'F')
    y0 = pdf.get_y()
    pdf.set_xy(x0 + 4, y0 + 2)
    pdf.cell(w - 8, 7, name, ln=True)
    pdf.set_font('Cairo', '', 9)
    pdf.set_text_color(100, 100, 100)
    pdf.set_xy(x0 + 4, y0 + 10)
    pdf.cell(w - 8, 5, desc, ln=True)
    pdf.set_xy(x0 + 4, y0 + 15)
    pdf.cell(w - 8, 5, f'المقاس: {size}', ln=True)
    pdf.ln(3)

pdf.ln(8)

# Prices
pdf.set_font('Cairo', 'B', 14)
pdf.set_text_color(26, 26, 46)
pdf.cell(0, 10, 'الاسعار', ln=True)
pdf.ln(4)

prices = [
    ('1,500 ج', 'شهريا - البنر الواحد'),
    ('3,500 ج', 'شهريا - باكج البنرات كلها'),
]
pdf.set_font('Cairo', 'B', 18)
for amt, desc in prices:
    pdf.set_fill_color(26, 26, 46)
    pdf.set_text_color(255, 255, 255)
    pdf.rect(pdf.get_x(), pdf.get_y(), 80, 24, 'F')
    y0 = pdf.get_y()
    pdf.set_xy(pdf.get_x() + 4, y0 + 2)
    pdf.cell(72, 10, amt, align='C')
    pdf.set_font('Cairo', '', 8)
    pdf.set_xy(pdf.get_x() + 4, y0 + 14)
    pdf.cell(72, 6, desc, align='C')
    pdf.set_font('Cairo', 'B', 18)
    pdf.set_x(pdf.get_x() + 85)

pdf.ln(30)
pdf.set_font('Cairo', '', 10)
pdf.set_text_color(26, 26, 46)
pdf.cell(0, 7, 'خصم 10% على الحجز لمدة 3 شهور', ln=True)
pdf.cell(0, 7, 'خصم 20% على الحجز لمدة 6 شهور', ln=True)
pdf.cell(0, 7, 'خصم 30% على الحجز لمدة سنة', ln=True)

# Page 2
pdf.add_page()
pdf.set_text_color(26, 26, 46)
pdf.set_font('Cairo', 'B', 14)
pdf.cell(0, 10, 'متطلبات الاعلان', ln=True)
pdf.ln(4)
pdf.set_font('Cairo', '', 10)
reqs = [
    'صورة بصيغة PNG او JPG - اقصى حجم 500KB',
    'المقاسات: 728x90 (علوي)، 728x70 (سفلي)، 300x250 (جانبي)',
    'عدم احتواء الاعلان على صوت او فيديو',
    'عدم مخالفة القوانين المصرية او المحتوى غير اللائق',
    'الرابط الوجهة يجب ان يكون HTTPS',
    'يفضل ان يكون الاعلان متوافقا مع طابع الموقع (استثمار، تداول، اقتصاد)',
]
for r in reqs:
    pdf.cell(0, 8, f'  {r}', ln=True)

pdf.ln(8)
pdf.set_font('Cairo', 'B', 14)
pdf.cell(0, 10, 'الشروط والاحكام', ln=True)
pdf.ln(4)
pdf.set_font('Cairo', '', 10)
terms = [
    '1. مدة الحملة الاعلانية تبدا من تاريخ التفعيل المتفق عليه.',
    '2. يتم السداد مقدما بالكامل (تحويل بنكي او Vodafone Cash).',
    '3. الاعلان ينتهي تلقائيا في تاريخ الانتهاء ولا يتجدد إلا باتفاق جديد.',
    '4. يحتفظ الموقع بالحق في ايقاف اي اعلان مخالف دون استرداد.',
    '5. الموقع غير مسؤول عن محتوى الاعلان او المنتج المعلن عنه.',
    '6. في حالة تعطل الموقع لاكثر من 48 ساعة متواصلة، يتم تعويض المدة.',
    '7. الاسعار قابلة للتغيير بعد انتهاء مدة العقد المتفق عليها.',
]
for t in terms:
    pdf.cell(0, 8, f'  {t}', ln=True)

pdf.ln(10)
pdf.set_font('Cairo', 'B', 14)
pdf.cell(0, 10, 'للحجز والاستفسار', ln=True)
pdf.set_font('Cairo', '', 12)
whatsapp = '+20 XXX XXX XXXX'
pdf.cell(0, 8, f'واتساب: {whatsapp}', ln=True)
pdf.set_font('Cairo', '', 9)
pdf.set_text_color(100, 100, 100)
pdf.cell(0, 6, '(يتم تحديد الرقم من اعدادات الموقع)', ln=True)

out = Path(__file__).parent / 'media_kit.pdf'
pdf.output(str(out))
print(f'OK: {out}')
