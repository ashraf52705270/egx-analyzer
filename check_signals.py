#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
سكريبت فحص إشارات الطيار الآلي
تشغيل: python check_signals.py
       python check_signals.py MILS ALUM
       python check_signals.py --all
       python check_signals.py --today

بيبحث في قاعدة بيانات التطبيق عن إشارات الأسهم المطلوبة
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime, timedelta

# ═══════════════════════════════════════════════════════════════
# البحث عن قاعدة البيانات
# ═══════════════════════════════════════════════════════════════
SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR / "data"

DB_PATH = os.getenv("EGX_DB_PATH", str(DATA_DIR / "egx_v2.db"))

# لو مش لاقيها في المسار الافتراضي، دور في مسارات تانية
if not os.path.exists(DB_PATH):
    alt_paths = [
        str(Path(__file__).resolve().parent / "data" / "egx_v2.db"),
        str(Path(__file__).resolve().parent / "egx_v2.db"),
        str(Path.cwd() / "data" / "egx_v2.db"),
        str(Path.cwd() / "egx_v2.db"),
    ]
    for p in alt_paths:
        if os.path.exists(p):
            DB_PATH = p
            break

if not os.path.exists(DB_PATH):
    print("=" * 60)
    print("❌ مش لاقي قاعدة البيانات!")
    print(f"   المسار المطلوب: {DB_PATH}")
    print()
    print("💡 جرب تشغل السكريبت من نفس مجلد التطبيق:")
    print("   cd /path/to/egx_analyzer")
    print("   python check_signals.py MILS ALUM")
    print()
    print("   أو حدد المسار يدوياً:")
    print("   EGX_DB_PATH=/path/to/egx_v2.db python check_signals.py MILS ALUM")
    print("=" * 60)
    sys.exit(1)


def query_signals(symbols=None, days=None, limit=500):
    """البحث في سجل الإشارات"""
    try:
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # ═══════════════════════════════════════════════════════
        # 1. سجل الإشارات (signals_log)
        # ═══════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("📡 سجل الإشارات التفصيلي (signals_log)")
        print("=" * 70)

        query = "SELECT * FROM signals_log WHERE 1=1"
        params = []

        if symbols:
            placeholders = ",".join(["?"] * len(symbols))
            query += f" AND symbol IN ({placeholders})"
            params.extend([s.upper() for s in symbols])

        if days:
            since = (datetime.utcnow() - timedelta(days=days)).isoformat()
            query += " AND created_at >= ?"
            params.append(since)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        try:
            cursor.execute(query, params)
            rows = cursor.fetchall()

            if not rows:
                if symbols:
                    print(f"\n   🔍 لا توجد إشارات لـ: {', '.join(symbols)}")
                else:
                    print("\n   🔍 لا توجد إشارات مسجلة")
            else:
                print(f"\n   تم العثور على {len(rows)} إشارة:\n")
                print(f"   {'الرمز':<10} {'الإجراء':<15} {'النوع':<18} {'الدرجة':<8} {'السعر':<10} {'التاريخ'}")
                print("   " + "-" * 75)

                for row in rows:
                    sym = row['symbol'] or '—'
                    action = row['action'] or '—'
                    sig_type = row['signal_type'] or '—'
                    score = f"{row['score']:.0f}" if row['score'] else '—'
                    price = f"{row['price']:.2f}" if row['price'] else '—'
                    created = row['created_at'] or '—'
                    # اختصار التاريخ
                    if created and 'T' in created:
                        created = created[:19].replace('T', ' ')

                    # تلوين حسب الإجراء
                    if 'OPEN' in action.upper():
                        icon = '🚀'
                    elif 'CLOSE' in action.upper() or 'STOP' in action.upper():
                        icon = '🛑'
                    elif 'TARGET' in action.upper() or 'T1' in action.upper() or 'T2' in action.upper() or 'T3' in action.upper():
                        icon = '🎯'
                    else:
                        icon = '📡'

                    print(f"   {icon} {sym:<8} {action:<13} {sig_type:<16} {score:<8} {price:<10} {created}")

        except Exception as e:
            print(f"   ⚠️ خطأ في الاستعلام: {e}")

        # ═══════════════════════════════════════════════════════
        # 2. الإشارات المُرسلة (sent_signals)
        # ═══════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("📮 الإشارات المُرسلة / منع التكرار (sent_signals)")
        print("=" * 70)

        query2 = "SELECT * FROM sent_signals WHERE 1=1"
        params2 = []

        if symbols:
            placeholders = ",".join(["?"] * len(symbols))
            query2 += f" AND symbol IN ({placeholders})"
            params2.extend([s.upper() for s in symbols])

        if days:
            since = (datetime.utcnow() - timedelta(days=days)).isoformat()
            query2 += " AND sent_at >= ?"
            params2.append(since)

        query2 += " ORDER BY sent_at DESC LIMIT ?"
        params2.append(limit)

        try:
            cursor.execute(query2, params2)
            rows2 = cursor.fetchall()

            if not rows2:
                if symbols:
                    print(f"\n   🔍 لا توجد إشارات مُرسلة لـ: {', '.join(symbols)}")
                else:
                    print("\n   🔍 لا توجد إشارات مُرسلة")
            else:
                print(f"\n   تم العثور على {len(rows2)} إشارة مُرسلة:\n")
                print(f"   {'الرمز':<10} {'نوع الإشارة':<20} {'تاريخ الإرسال'}")
                print("   " + "-" * 55)

                for row in rows2:
                    sym = row['symbol'] or '—'
                    sig_type = row['signal_type'] or '—'
                    sent_at = row['sent_at'] or '—'
                    if sent_at and 'T' in sent_at:
                        sent_at = sent_at[:19].replace('T', ' ')

                    icon = '✅' if 'OPEN' in sig_type.upper() else '📌'
                    print(f"   {icon} {sym:<8} {sig_type:<18} {sent_at}")

        except Exception as e:
            print(f"   ⚠️ خطأ في الاستعلام: {e}")

        # ═══════════════════════════════════════════════════════
        # 3. ملخص لكل سهم
        # ═══════════════════════════════════════════════════════
        if symbols:
            print("\n" + "=" * 70)
            print(f"📊 ملخص لكل سهم مطلوب")
            print("=" * 70)

            for sym in symbols:
                sym = sym.upper()
                print(f"\n   🔎 {sym}:")

                # عدد الإشارات
                try:
                    cursor.execute(
                        "SELECT COUNT(*) as cnt, MIN(created_at) as first_sig, MAX(created_at) as last_sig "
                        "FROM signals_log WHERE symbol = ?", (sym,)
                    )
                    row = cursor.fetchone()
                    if row and row['cnt'] > 0:
                        first = row['first_sig'][:19].replace('T', ' ') if row['first_sig'] else '—'
                        last = row['last_sig'][:19].replace('T', ' ') if row['last_sig'] else '—'
                        print(f"      📡 إجمالي الإشارات: {row['cnt']}")
                        print(f"      🕐 أول إشارة: {first}")
                        print(f"      🕐 آخر إشارة: {last}")
                    else:
                        print(f"      ❌ لا توجد إشارات مسجلة لهذا السهم")
                except:
                    print(f"      ⚠️ خطأ في الاستعلام")

                # هل ظهر كـ OPEN؟
                try:
                    cursor.execute(
                        "SELECT * FROM sent_signals WHERE symbol = ? AND signal_type = 'OPEN' "
                        "ORDER BY sent_at DESC LIMIT 5", (sym,)
                    )
                    opens = cursor.fetchall()
                    if opens:
                        print(f"      ✅ ظهر كفرصة فتح ({len(opens)} مرة):")
                        for o in opens:
                            t = o['sent_at'][:19].replace('T', ' ') if o['sent_at'] else '—'
                            print(f"         → {t}")
                    else:
                        print(f"      ❌ لم يظهر كفرصة فتح (OPEN) في الطيار الآلي")
                except:
                    pass

                # آخر 5 إشارات
                try:
                    cursor.execute(
                        "SELECT action, signal_type, score, price, created_at "
                        "FROM signals_log WHERE symbol = ? "
                        "ORDER BY created_at DESC LIMIT 5", (sym,)
                    )
                    recent = cursor.fetchall()
                    if recent:
                        print(f"      📋 آخر الإشارات:")
                        for r in recent:
                            t = r['created_at'][:19].replace('T', ' ') if r['created_at'] else '—'
                            price = f"{r['price']:.2f}" if r['price'] else '—'
                            score = f"{r['score']:.0f}" if r['score'] else '—'
                            print(f"         → {t} | {r['action'] or '—'} | نوع: {r['signal_type'] or '—'} | درجة: {score} | سعر: {price}")
                except:
                    pass

        # ═══════════════════════════════════════════════════════
        # 4. إحصائيات عامة
        # ═══════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("📈 إحصائيات عامة")
        print("=" * 70)

        try:
            cursor.execute("SELECT COUNT(*) as cnt FROM signals_log")
            total = cursor.fetchone()['cnt']
            print(f"\n   إجمالي الإشارات المسجلة: {total}")

            cursor.execute("SELECT COUNT(DISTINCT symbol) as cnt FROM signals_log")
            unique = cursor.fetchone()['cnt']
            print(f"   عدد الأسهم المختلفة: {unique}")

            cursor.execute(
                "SELECT symbol, COUNT(*) as cnt FROM signals_log "
                "GROUP BY symbol ORDER BY cnt DESC LIMIT 10"
            )
            top = cursor.fetchall()
            if top:
                print(f"\n   🏆 أكثر 10 أسهم إشارات:")
                for i, row in enumerate(top, 1):
                    print(f"      {i}. {row['symbol']}: {row['cnt']} إشارة")

            cursor.execute(
                "SELECT action, COUNT(*) as cnt FROM signals_log "
                "GROUP BY action ORDER BY cnt DESC"
            )
            actions = cursor.fetchall()
            if actions:
                print(f"\n   📊 توزيع الإجراءات:")
                for row in actions:
                    icon = {'OPEN': '🚀', 'CLOSE_STOP': '🛑', 'CLOSE_T1': '🎯', 'CLOSE_T2': '🎯', 'CLOSE_T3': '🏆', 'TRAIL_STOP': '📌'}.get(row['action'], '📡')
                    print(f"      {icon} {row['action'] or 'غير محدد'}: {row['cnt']}")

        except Exception as e:
            print(f"   ⚠️ خطأ: {e}")

        conn.close()

    except Exception as e:
        print(f"❌ خطأ في الاتصال بقاعدة البيانات: {e}")
        print(f"   المسار: {DB_PATH}")


# ═══════════════════════════════════════════════════════════════
# التشغيل
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("🔍 فحص إشارات الطيار الآلي - EGX Signal Checker")
    print(f"📁 قاعدة البيانات: {DB_PATH}")

    args = sys.argv[1:]

    if not args:
        print("\n💡 الاستخدام:")
        print("   python check_signals.py MILS ALUM     ← بحث عن أسهم معينة")
        print("   python check_signals.py --all          ← كل الإشارات")
        print("   python check_signals.py --today        ← إشارات اليوم فقط")
        print("   python check_signals.py --week         ← آخر أسبوع")
        print()
        # افتراضي: اعرض أسهم MILS و ALUM
        print("⏳ جاري البحث عن MILS و ALUM تلقائياً...\n")
        query_signals(symbols=["MILS", "ALUM"])

    elif "--all" in args:
        query_signals(limit=200)

    elif "--today" in args:
        query_signals(days=1, limit=200)

    elif "--week" in args:
        query_signals(days=7, limit=500)

    else:
        symbols = [a.upper() for a in args if not a.startswith("--")]
        query_signals(symbols=symbols)
