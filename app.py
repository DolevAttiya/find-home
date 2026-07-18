import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import yaml
import json
import os
import folium
import math
from datetime import datetime, date
from pathlib import Path
from streamlit_folium import st_folium

APP_DIR = Path(__file__).parent
from core.database import (
    init_db, get_apartments, get_groups, get_stats,
    mark_seen, update_note, mark_inactive, mark_not_relevant,
    merge_manually, unmerge_manually,
)
from core.dedup import group_apartments, _street_name

st.set_page_config(page_title="חיפוש דירות", page_icon="🏠", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
/* RTL רק על אזור התוכן הראשי, לא על כל ה-.stApp - כדי שסדר העמודות
   (סינון, כרטיסים מול מפה וכו') יתהפך נכון להזחה עברית, בלי לגעת
   במבנה/אנימציית הקיפול של הסיידבר עצמו (שנשאר במבנה המקורי של Streamlit) */
[data-testid="stMain"] { direction: rtl; }
h1, h2, h3, p, label, .stMarkdown, .stMarkdown p,
div[data-testid="stMetricLabel"], div[data-testid="stMetricValue"],
.stTextArea textarea, .stDataFrame, .stSelectbox, .stCheckbox,
div[data-testid="stText"], div[data-testid="column"] {
    direction: rtl; text-align: right;
}
.stSlider, .stNumberInput { direction: ltr; }
th { text-align: right !important; }
[data-testid="stDataFrame"] tr { cursor: pointer; }
[data-testid="stDataFrame"] tr:hover td { background: rgba(229,62,62,0.08) !important; }
[data-testid="column"]:first-child { position: sticky; top: 0; }
.badge-new   { background:#d4edda; color:#155724; padding:2px 7px; border-radius:4px; font-size:.8em; }
.badge-drop  { background:#fff3cd; color:#856404; padding:2px 7px; border-radius:4px; font-size:.8em; }
.badge-seen  { background:#e2e3e5; color:#383d41; padding:2px 7px; border-radius:4px; font-size:.8em; }
.badge-off   { background:#f8d7da; color:#721c24; padding:2px 7px; border-radius:4px; font-size:.8em; }
.days-low    { color:#2d7d46; font-weight:600; }
.days-mid    { color:#e07b00; font-weight:600; }
.days-high   { color:#c0392b; font-weight:700; }
</style>
""", unsafe_allow_html=True)

init_db()

TODAY = date.today()


# ── helpers ──────────────────────────────────────────────────────────────────

def _fmt_rooms(val) -> str:
    """3.0 → '3'  |  3.5 → '3.5'  |  None → '-'"""
    if val is None:
        return "-"
    try:
        return f"{float(val):g}"
    except (TypeError, ValueError):
        return str(val)

def _days_on_market(apt: dict) -> int | None:
    for field in ("posted_at", "scraped_at"):
        val = apt.get(field)
        if not val:
            continue
        try:
            dt = pd.to_datetime(val)
            if dt.tzinfo is not None:
                dt = dt.tz_convert("UTC").tz_localize(None)
            return max(0, (pd.Timestamp.now() - dt).days)
        except Exception:
            continue
    return None


def _days_label(days: int | None) -> str:
    if days is None:
        return "-"
    if days == 0:
        return "היום"
    return f"{days}י׳"


def _orig_price(apt: dict) -> int | None:
    return apt.get("original_price") or apt.get("first_hist_price")


def _price_per_sqm(apt: dict) -> int | None:
    price, size = apt.get("price"), apt.get("size_sqm")
    if price and size:
        return round(price / size)
    return None


def _room_buckets(rooms_range: tuple, step: float = 0.5) -> list[float]:
    """כל ערכי החדרים בתוך הטווח שנבחר (למשל 3.0-4.0 עם step 0.5 -> [3.0,3.5,4.0]),
    בשביל לתת לכל מספר חדרים סליידר גודל נפרד ("פילטר כפול")."""
    lo, hi = rooms_range
    n = int(round((hi - lo) / step))
    return [round(lo + i * step, 2) for i in range(n + 1)]


def _passes_size_by_rooms(apt: dict, size_by_rooms: dict, step: float = 0.5) -> bool:
    """בודק גודל מול הדלי (bucket) של מספר החדרים הקרוב ביותר של הדירה.
    חוסר נתון (rooms/size לא ידועים) עובר את הבדיקה - כמו כל שאר הפילטרים
    כאן, לא רוצים לפסול דירה בגלל שדה חסר."""
    rooms, size = apt.get("rooms"), apt.get("size_sqm")
    if rooms is None or size is None:
        return True
    bucket = round(round(rooms / step) * step, 2)
    rng = size_by_rooms.get(bucket)
    if rng is None:
        return True
    return rng[0] <= size <= rng[1]


def _status_badges(apt: dict) -> str:
    parts = []
    scraped = apt.get("scraped_at")
    if scraped:
        try:
            if pd.to_datetime(scraped).date() == TODAY:
                parts.append("🆕")
        except Exception:
            pass
    orig = _orig_price(apt)
    if orig and apt.get("price") and orig > apt["price"]:
        parts.append("📉")
    if apt.get("seen"):
        parts.append("👁")
    if not apt.get("is_active", 1):
        parts.append("🚫")
    if apt.get("not_relevant"):
        parts.append("👎")
    return " ".join(parts)


def _img_data_uri(path: str) -> str | None:
    import base64
    try:
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        ext = path.rsplit(".", 1)[-1].lower()
        mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp", "gif": "gif"}.get(ext, "jpeg")
        return f"data:image/{mime};base64,{b64}"
    except Exception:
        return None


def _render_gallery(images: list, height: int = 640):
    # components.html (לא st.html!) - st.html מכניס תוכן דרך innerHTML שלא
    # מריץ <script> בכלל, אז לחיצה על תמונה לא הייתה עושה כלום (אומת ידנית:
    # openImg נשאר undefined). components.html יוצר iframe אמיתי עם srcdoc
    # שבו script רץ כרגיל. התצוגה המוגדלת היא position:fixed שמכסה את כל
    # ה-iframe - לא צריך לגעת בדף החיצוני בכלל, אז אין צורך ב-window.parent.
    imgs_b64 = [uri for uri in (_img_data_uri(p) for p in images[:15]) if uri]
    if not imgs_b64:
        return

    imgs_json = json.dumps(imgs_b64)
    html = f"""<style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    html,body{{margin:0;background:transparent;height:100%}}
    .gallery{{display:flex;flex-direction:column;gap:10px;padding:2px;
              height:100%;overflow-y:auto}}
    .thumb{{width:100%;height:280px;object-fit:cover;border-radius:10px;
            cursor:pointer;border:2px solid transparent;transition:all .15s;flex-shrink:0;display:block}}
    .thumb:hover{{border-color:#e53e3e;transform:scale(1.01)}}
    #preview{{opacity:0;pointer-events:none;position:fixed;inset:0;background:rgba(0,0,0,.9);
              border-radius:8px;display:flex;align-items:center;
              justify-content:center;transition:opacity .15s;z-index:10}}
    #preview.open{{opacity:1;pointer-events:auto}}
    #main-img{{max-width:92%;max-height:92%;object-fit:contain;border-radius:6px}}
    .nav{{position:absolute;top:50%;transform:translateY(-50%);background:rgba(255,255,255,.15);
          border:none;color:#fff;font-size:1.6em;padding:10px 16px;cursor:pointer;border-radius:6px}}
    .nav:hover{{background:rgba(255,255,255,.32)}}
    #btn-prev{{left:14px}} #btn-next{{right:14px}}
    #btn-close{{position:absolute;top:12px;right:14px;background:rgba(0,0,0,.45);
               border:none;color:#fff;font-size:1.3em;padding:5px 12px;cursor:pointer;border-radius:5px}}
    #counter{{position:absolute;bottom:14px;left:50%;transform:translateX(-50%);
             color:rgba(255,255,255,.7);font-size:.9em;font-family:Arial}}
    </style>
    <div class="gallery">
      {"".join(f'<img class="thumb" src="{src}" onclick="openImg({i})">' for i, src in enumerate(imgs_b64))}
    </div>
    <div id="preview">
      <button class="nav" id="btn-prev" onclick="event.stopPropagation();nav(-1)">&#9664;</button>
      <img id="main-img" src="">
      <button class="nav" id="btn-next" onclick="event.stopPropagation();nav(1)">&#9654;</button>
      <button id="btn-close" onclick="closePreview()">&#x2715;</button>
      <div id="counter"></div>
    </div>
    <script>
    const imgs={imgs_json};let cur=0;
    function openImg(i){{cur=i;
      document.getElementById('main-img').src=imgs[i];
      document.getElementById('counter').textContent=(i+1)+' / '+imgs.length;
      document.getElementById('preview').classList.add('open');}}
    function closePreview(){{document.getElementById('preview').classList.remove('open');}}
    function nav(dir){{cur=(cur+dir+imgs.length)%imgs.length;
      document.getElementById('main-img').src=imgs[cur];
      document.getElementById('counter').textContent=(cur+1)+' / '+imgs.length;}}
    document.getElementById('preview').addEventListener('click', closePreview);
    document.addEventListener('keydown',e=>{{
      if(!document.getElementById('preview').classList.contains('open'))return;
      if(e.key==='Escape')closePreview();
      if(e.key==='ArrowLeft')nav(1);if(e.key==='ArrowRight')nav(-1);
    }});
    </script>"""
    components.html(html, height=height, scrolling=False)


def _render_apt_detail(apt: dict, key_prefix: str = ""):
    post_id = (key_prefix + "_" if key_prefix else "") + (apt.get("post_id") or str(apt.get("id") or id(apt)))
    member_ids = apt.get("_member_post_ids") or [apt.get("post_id")]

    # ── header badges ──
    src_names = {"facebook": "פייסבוק", "madlan": "מדלן", "yad2": "יד2", "dorin": "דורין", "yad2_project": "יד2 פרויקט", "komo": "קומו"}
    src_label = " + ".join(src_names.get(s, s) for s in apt.get("source_list", [apt.get("source", "")]))
    days = _days_on_market(apt)

    badge_parts = []
    if src_label:
        badge_parts.append(f'<span class="badge-seen">{src_label}</span>')
    if apt.get("group_size", 1) > 1:
        badge_parts.append(f'<span class="badge-drop">🔗 נמצאה ב-{apt["group_size"]} מודעות</span>')
    if apt.get("seen"):
        badge_parts.append('<span class="badge-seen">👁 ראיתי</span>')
    if not apt.get("is_active", 1):
        badge_parts.append('<span class="badge-off">🚫 הוסרה</span>')
    if apt.get("not_relevant"):
        badge_parts.append('<span class="badge-off">👎 לא רלוונטי</span>')
    scraped = apt.get("scraped_at")
    if scraped:
        try:
            if pd.to_datetime(scraped).date() == TODAY:
                badge_parts.append('<span class="badge-new">🆕 חדשה היום</span>')
        except Exception:
            pass
    if badge_parts:
        st.markdown(" ".join(badge_parts), unsafe_allow_html=True)

    # ── price + drop ──
    price = apt.get("price")
    orig = _orig_price(apt)
    if price:
        if orig and orig > price:
            drop = orig - price
            pct = drop / orig * 100
            st.markdown(
                f"<div style='font-size:1.5em;font-weight:700;color:#2d7d46'>"
                f"{int(price):,} ₪ "
                f"<span style='font-size:.65em;color:#c0392b'>📉 ירד מ-{int(orig):,} ₪ (-{int(drop):,} ₪ / -{pct:.1f}%)</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f"<div style='font-size:1.5em;font-weight:700'>{int(price):,} ₪</div>",
                unsafe_allow_html=True,
            )

    price_per_sqm = _price_per_sqm(apt)
    if price_per_sqm:
        st.caption(f"💰 {price_per_sqm:,} ₪ למ\"ר")

    # ── days on market ──
    if days is not None:
        if days <= 7:
            cls, note = "days-low", "דירה חדשה"
        elif days <= 30:
            cls, note = "days-mid", "מחכה כבר — יש מה לדבר"
        else:
            cls, note = "days-high", "מחכה הרבה זמן — כוח מיקוח גבוה!"
        st.markdown(
            f'<span class="{cls}">⏱ {days} ימים בשוק</span> '
            f'<span style="color:#888;font-size:.85em">({note})</span>',
            unsafe_allow_html=True,
        )

    # ── specs ──
    c1, c2, c3 = st.columns(3)
    c1.metric("חדרים", _fmt_rooms(apt.get("rooms")))
    c2.metric("מ״ר", int(apt["size_sqm"]) if apt.get("size_sqm") else "-")
    c3.metric("קומה", apt.get("floor") or "-")

    # ── amenities ──
    amenities = []
    if apt.get("has_mamad") == 1:    amenities.append('✓ ממ"ד')
    if apt.get("has_parking") == 1:  amenities.append("✓ חניה")
    if apt.get("has_balcony") == 1:  amenities.append("✓ מרפסת")
    if apt.get("has_elevator") == 1: amenities.append("✓ מעלית")
    if amenities:
        st.markdown("&nbsp;&nbsp;|&nbsp;&nbsp;".join(amenities))

    # ── contact ──
    row = []
    if apt.get("phone"):
        row.append(f"📞 **{apt['phone']}**")
    if apt.get("post_url"):
        row.append(f"[🔗 מודעה מקורית]({apt['post_url']})")
    if row:
        st.markdown("  &nbsp;·&nbsp;  ".join(row))

    if apt.get("lat") and apt.get("lon"):
        if st.button("🎯 הצג במפה", key=f"focus_{post_id}", use_container_width=True):
            st.session_state["map_focus_post_id"] = apt.get("post_id")
            st.session_state["map_focus_lat"] = apt["lat"]
            st.session_state["map_focus_lon"] = apt["lon"]
            st.rerun()

    # ── action buttons ──
    act1, act2, act3 = st.columns(3)
    with act1:
        seen = apt.get("seen", 0)
        if seen:
            if st.button("↩ בטל ראיתי", key=f"seen_{post_id}", use_container_width=True):
                for pid in member_ids:
                    mark_seen(pid, False)
                st.rerun()
        else:
            if st.button("✓ ראיתי", key=f"seen_{post_id}", type="primary", use_container_width=True):
                for pid in member_ids:
                    mark_seen(pid, True)
                st.rerun()
    with act2:
        active = apt.get("is_active", 1)
        if active:
            if st.button("🗑 סמן כהוסרה", key=f"inactive_{post_id}", use_container_width=True):
                for pid in member_ids:
                    mark_inactive(pid, active=False)
                st.rerun()
        else:
            if st.button("↩ שחזר מודעה", key=f"inactive_{post_id}", use_container_width=True):
                for pid in member_ids:
                    mark_inactive(pid, active=True)
                st.rerun()
    with act3:
        not_relevant = apt.get("not_relevant", 0)
        if not_relevant:
            if st.button("↩ בטל לא רלוונטי", key=f"notrel_{post_id}", use_container_width=True):
                for pid in member_ids:
                    mark_not_relevant(pid, False)
                st.rerun()
        else:
            if st.button("👎 לא רלוונטי", key=f"notrel_{post_id}", use_container_width=True):
                for pid in member_ids:
                    mark_not_relevant(pid, True)
                st.rerun()

    # ── notes ──
    st.markdown("**הערות שלי:**")
    note_val = st.text_area(
        "הערות",
        value=apt.get("notes") or "",
        height=100,
        label_visibility="collapsed",
        key=f"note_area_{post_id}",
        placeholder="כתוב כאן הערות על הדירה הזו...",
    )
    if st.button("💾 שמור הערה", key=f"save_note_{post_id}"):
        for pid in member_ids:
            update_note(pid, note_val)
        st.toast("הערה נשמרה!")

    # ── merged listings ──
    members = apt.get("_members") or []
    if len(members) > 1:
        with st.expander(f"📋 כל המודעות המקוריות ({len(members)})"):
            for m in sorted(members, key=lambda m: m.get("scraped_at") or "", reverse=True):
                m_src = src_names.get(m.get("source", ""), m.get("source", ""))
                m_price = f"{int(m['price']):,} ₪" if m.get("price") else "-"
                m_link = f" · [🔗 מודעה]({m['post_url']})" if m.get("post_url") else ""
                m_phone = f" · 📞 {m['phone']}" if m.get("phone") else ""
                st.markdown(f"- **{m_src}** — {m_price}{m_phone}{m_link}")

        if any(m.get("manual_group") for m in members):
            if st.button("✂ פרק איחוד ידני", key=f"unmerge_{post_id}"):
                unmerge_manually(member_ids)
                st.rerun()

    # ── description ──
    if apt.get("text"):
        safe_text = apt["text"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
        st.markdown(
            f"""<div dir="rtl" style="
                font-size: 0.78em;
                line-height: 1.55;
                color: #333;
                background: #f9f9f9;
                border-right: 3px solid #e53e3e;
                padding: 10px 12px;
                border-radius: 4px;
                max-height: 220px;
                overflow-y: auto;
                white-space: pre-wrap;
                word-break: break-word;
            ">{safe_text}</div>""",
            unsafe_allow_html=True,
        )


def _apt_images(apt: dict) -> list:
    if not apt.get("images_json"):
        return []
    try:
        return [p for p in json.loads(apt["images_json"]) if os.path.exists(p)]
    except Exception:
        return []


def _close_apt_dialog():
    # נקרא רק בסגירה יזומה ע"י המשתמש (X/Escape/קליק בחוץ) - לא כשהדיאלוג
    # נשאר פתוח בגלל rerun פנימי (כפתורי פעולה בתוכו), כי אז הקוד למטה
    # פשוט קורא ל-_apt_dialog(...) שוב מבלי לגעת בקי הזה.
    st.session_state.pop("open_dialog_post_id", None)
    # בכוונה לא מנקים כאן את _last_map_click_coords! ניסיתי את זה קודם כדי
    # לאפשר קליק חוזר על אותה נקודה לפתוח שוב - אבל זה יצר לולאה אינסופית:
    # st_folium ממשיך להחזיר את last_object_clicked הישן בכל rerun גם בלי
    # קליק חדש בפועל (זה בדיוק מה שהגלאי הזה נועד לסנן, ר' הערה למטה). אם
    # מנקים את המפתח בסגירה, ה-rerun שהסגירה עצמה גורמת לו "נראה" כמו קליק
    # חדש על אותה נקודה -> פותח מיד שוב -> סוגרים -> נפתח מיד שוב... בלי
    # סוף. השארת המפתח כמו שהוא פותרת את זה; המחיר היחיד הוא שקליק חוזר
    # בפועל על *אותה* נקודה בדיוק מיד אחרי סגירה לא יפתח - שולי לעומת לולאה.


def _apt_dialog(apt: dict):
    # Streamlit מזהה כל דיאלוג ע"פ hash קבוע של (title, width, icon,
    # on_dismiss, ...) - לא מביא בחשבון את התוכן שמעבירים לפונקציה. אצלנו
    # אותה @st.dialog נקראת שוב ושוב לדירות שונות עם title קבוע ("פרטי
    # דירה"), כך שה-id יוצא זהה בכל פעם. הפרונט של Streamlit משתמש ב-id
    # הזה כדי "למנוע תוכן ישן מדיאלוג קודם" (ר' streamlit/elements/lib/
    # dialog.py, מתייחס ל-issue #10907) - וכשה-id זהה בין דירה A לדירה B,
    # זיהוי-הכפילות הזה בטעות תפס סגירה+פתיחה-מחדש לדירה אחרת כ"אותו
    # דיאלוג" ולפעמים מנע ממנו להיפתח בפועל בצד הלקוח (גם שה-session_state
    # והרינדור בצד פייתון תקינים לגמרי - אומת ב-AppTest). הפתרון: מדביקים
    # את הכתובת (ובלעדיה, ה-post_id) בתוך ה-title עצמו כדי שה-id ישתנה
    # אמיתית בין דירה לדירה - זה גם דקורציה דינמית (לא decorator סטטי
    # ברמת המודול) כדי שה-title יוכל להיגזר מ-apt בכל קריאה.
    title = apt.get("address") or apt.get("post_id") or "פרטי דירה"

    @st.dialog(title, width="large", on_dismiss=_close_apt_dialog)
    def _dialog():
        # ימין (30%) = פרטי הדירה, שמאל (60%) = גלריית תמונות גדולה עם גלילה.
        # st.dialog מוצג ב-portal מחוץ ל-stMain (שם מוגדר direction:rtl), אז
        # בתוך הדיאלוג הסדר הוא LTR רגיל - מי שמוצהר ראשון מוצג משמאל. בדקתי
        # ידנית: col_gallery צריך להיות ראשון כדי ש-col_details יוצג מימין.
        col_gallery, col_details = st.columns([60, 30])
        with col_details:
            st.subheader(apt.get("address") or "פרטי דירה")
            _render_apt_detail(apt)
        with col_gallery:
            images = _apt_images(apt)
            if images:
                _render_gallery(images)
            else:
                st.markdown(
                    "<div style='background:#f0f0f0;height:400px;border-radius:10px;"
                    "display:flex;align-items:center;justify-content:center;"
                    "font-size:3em;color:#bbb'>🏠</div>",
                    unsafe_allow_html=True,
                )

    _dialog()


def _render_apt_card(apt: dict):
    post_id = apt.get("post_id") or str(id(apt))

    with st.container(border=True, key=f"apt_card_{post_id}"):
        images = []
        if apt.get("images_json"):
            try:
                images = [p for p in json.loads(apt["images_json"]) if os.path.exists(p)]
            except Exception:
                pass
        thumb_uri = _img_data_uri(images[0]) if images else None
        if thumb_uri:
            st.markdown(
                f"<img src='{thumb_uri}' style='width:100%;height:160px;"
                "object-fit:cover;border-radius:6px;display:block;'>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                "<div style='background:#f0f0f0;height:160px;border-radius:6px;"
                "display:flex;align-items:center;justify-content:center;"
                "font-size:2.2em;color:#bbb'>🏠</div>",
                unsafe_allow_html=True,
            )

        src_names = {"facebook": "פייסבוק", "madlan": "מדלן", "yad2": "יד2", "dorin": "דורין", "yad2_project": "יד2 פרויקט", "komo": "קומו"}
        src_label = " + ".join(src_names.get(s, s) for s in apt.get("source_list", [apt.get("source", "")]))
        badge_line = f'<span class="badge-seen">{src_label}</span>'
        if apt.get("group_size", 1) > 1:
            badge_line += f' <span class="badge-drop">🔗×{apt["group_size"]}</span>'
        status = _status_badges(apt)
        if status:
            badge_line += f" {status}"
        st.markdown(badge_line, unsafe_allow_html=True)

        price = apt.get("price")
        orig = _orig_price(apt)
        if price:
            if orig and orig > price:
                pct = (orig - price) / orig * 100
                st.markdown(
                    f"<div style='font-size:1.25em;font-weight:700;color:#2d7d46'>{int(price):,} ₪ "
                    f"<span style='font-size:.6em;color:#c0392b'>📉 -{pct:.0f}%</span></div>",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f"<div style='font-size:1.25em;font-weight:700'>{int(price):,} ₪</div>",
                    unsafe_allow_html=True,
                )
        else:
            st.markdown("<div style='font-size:1.1em;color:#888'>מחיר לא צוין</div>", unsafe_allow_html=True)

        price_per_sqm = _price_per_sqm(apt)
        if price_per_sqm:
            st.caption(f"💰 {price_per_sqm:,} ₪ למ\"ר")

        st.markdown(f"**{apt.get('address') or 'כתובת לא ידועה'}**")

        facts = []
        if apt.get("rooms"):    facts.append(f"{_fmt_rooms(apt['rooms'])} חד'")
        if apt.get("size_sqm"): facts.append(f"{int(apt['size_sqm'])} מ\"ר")
        if apt.get("floor"):    facts.append(f"קומה {apt['floor']}")
        if facts:
            st.caption(" · ".join(facts))

        tags = []
        if apt.get("has_mamad"):    tags.append('ממ"ד')
        if apt.get("has_parking"):  tags.append("חניה")
        if apt.get("has_balcony"):  tags.append("מרפסת")
        if apt.get("has_elevator"): tags.append("מעלית")
        if tags:
            st.caption("✓ " + " · ".join(tags))

        days = _days_on_market(apt)
        if days is not None:
            st.caption(f"⏱ {days} ימים בשוק")

        has_coords = apt.get("lat") and apt.get("lon")
        if has_coords:
            card_act1, card_act2, card_act3 = st.columns([2, 1, 1])
        else:
            card_act1, card_act2 = st.columns([2, 1])
            card_act3 = None
        with card_act1:
            if st.button("🔍 פרטים", key=f"card_{post_id}", use_container_width=True):
                st.session_state["open_dialog_post_id"] = post_id
                st.rerun()
        with card_act2:
            if st.button("👎 הסתר", key=f"card_hide_{post_id}", use_container_width=True):
                member_ids = apt.get("_member_post_ids") or [apt.get("post_id")]
                for pid in member_ids:
                    mark_not_relevant(pid, True)
                st.rerun()
        if card_act3 is not None:
            with card_act3:
                if st.button("🎯", key=f"card_focus_{post_id}", use_container_width=True, help="הצג במפה"):
                    st.session_state["map_focus_post_id"] = apt.get("post_id")
                    st.session_state["map_focus_lat"] = apt["lat"]
                    st.session_state["map_focus_lon"] = apt["lon"]
                    st.rerun()

        st.checkbox("בחר לאיחוד ↔", key=f"mergesel_{post_id}")


def load_config():
    with open("config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_config(config):
    with open("config.yaml", "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False)


# ── Sidebar ───────────────────────────────────────────────────────────────────

st.sidebar.title("🏠 חיפוש דירות")
page = st.sidebar.radio("ניווט", ["תוצאות", "הגדרות", "קבוצות"], key="nav")

# ── Results page ─────────────────────────────────────────────────────────────

if page == "תוצאות":
    st.title("דירות שנמצאו")

    config = load_config()

    stats = get_stats()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("סה״כ דירות", stats["total"])
    c2.metric("חדשות היום", stats["new_today"])
    c3.metric("ירידות מחיר", stats["price_drops"])
    c4.metric("קבוצות פעילות", stats["groups"])

    st.divider()

    with st.expander("סינון תוצאות", expanded=True):
        fc1, fc2 = st.columns(2)
        with fc1:
            only_price = st.checkbox("רק פוסטים עם מחיר", value=config["מחיר"].get("רק_פוסטים_עם_מחיר", True))
            price_range = st.slider(
                "טווח מחיר (₪)", 3_000_000, 6_000_000,
                (config["מחיר"].get("מינימום", 3_000_000), config["מחיר"].get("מקסימום", 6_000_000)),
                step=50_000, disabled=not only_price,
            )
            rooms_range = st.slider(
                "מספר חדרים", 1.0, 10.0,
                (float(config["חדרים"].get("מינימום", 3)), float(config["חדרים"].get("מקסימום", 5))),
                step=0.5,
            )
            size_by_rooms_mode = st.checkbox("גודל שונה לכל מספר חדרים (פילטר כפול)", value=False)
            if size_by_rooms_mode:
                cfg_size_by_rooms = config.get("גודל_לפי_חדרים", {})
                default_min = config["גודל_במטר"].get("מינימום", 60)
                default_max = config["גודל_במטר"].get("מקסימום", 150)
                size_range = None
                size_by_rooms = {}
                for rv in _room_buckets(rooms_range):
                    key = f"{rv:g}"
                    bucket_cfg = cfg_size_by_rooms.get(key, {})
                    size_by_rooms[rv] = st.slider(
                        f"גודל ל-{key} חדרים (מ״ר)", 20, 300,
                        (bucket_cfg.get("מינימום", default_min), bucket_cfg.get("מקסימום", default_max)),
                        step=5, key=f"size_rooms_{key}",
                    )
            else:
                size_range = st.slider(
                    "גודל (מ״ר)", 20, 300,
                    (config["גודל_במטר"].get("מינימום", 60), config["גודל_במטר"].get("מקסימום", 150)),
                    step=5,
                )
                size_by_rooms = None
            price_per_sqm_range = st.slider(
                'מחיר למ"ר (₪)', 5_000, 60_000, (5_000, 60_000), step=1_000,
            )
        with fc2:
            has_mamad   = st.checkbox('✓ ממ"ד / מרחב מוגן')
            has_parking = st.checkbox("✓ חניה")
            has_balcony = st.checkbox("✓ מרפסת")
            source_filter = st.selectbox("מקור", ["הכל", "פייסבוק", "מדלן", "יד2", "דורין", "יד2 פרויקט", "קומו"])
            only_with_images = st.checkbox("📷 רק עם תמונות")
            st.markdown("---")
            hide_seen    = st.checkbox("הסתר דירות שראיתי 👁", value=False)
            show_inactive = st.checkbox("הצג מודעות שהוסרו 🚫", value=False)
            hide_not_relevant = st.checkbox("הסתר דירות לא רלוונטיות 👎", value=True)

    filters = {
        "only_with_price": only_price,
        "min_price":  price_range[0] if only_price else None,
        "max_price":  price_range[1] if only_price else None,
        "min_rooms":  rooms_range[0],
        "max_rooms":  rooms_range[1],
        "min_size":   size_range[0] if size_range else None,
        "max_size":   size_range[1] if size_range else None,
        "has_mamad":  has_mamad,
        "has_parking": has_parking,
        "has_balcony": has_balcony,
        "source": {"הכל": None, "פייסבוק": "facebook", "מדלן": "madlan", "יד2": "yad2", "דורין": "dorin", "יד2 פרויקט": "yad2_project", "קומו": "komo"}.get(source_filter),
    }

    apartments_all = get_apartments(filters)

    # Python-level filters
    apartments_raw = [
        a for a in apartments_all
        if (show_inactive or a.get("is_active", 1))
        and (not hide_seen or not a.get("seen"))
        and (not hide_not_relevant or not a.get("not_relevant"))
    ]
    apartments = group_apartments(apartments_raw)
    if only_with_images:
        apartments = [a for a in apartments if a.get("images_json")]
    apartments = [
        a for a in apartments
        if _price_per_sqm(a) is None
        or price_per_sqm_range[0] <= _price_per_sqm(a) <= price_per_sqm_range[1]
    ]
    if size_by_rooms:
        apartments = [a for a in apartments if _passes_size_by_rooms(a, size_by_rooms)]

    merged_count = sum(1 for a in apartments if a.get("group_size", 1) > 1)
    subtitle = f"נמצאו {len(apartments)} דירות"
    if merged_count:
        subtitle += f" (מתוך {len(apartments_raw)} מודעות, {merged_count} דירות אוחדו מכמה מקורות)"
    st.subheader(subtitle)

    sort_col1, sort_col2 = st.columns([3, 1])
    with sort_col1:
        sort_field = st.selectbox(
            "מיון לפי", ["ללא מיון", "מחיר", 'מחיר למ"ר', 'גודל (מ"ר)', "ימים בשוק", "רחוב"],
        )
    with sort_col2:
        sort_desc = st.checkbox("סדר יורד", value=False)

    SORT_FIELDS = {
        "מחיר": lambda a: a.get("price"),
        'מחיר למ"ר': _price_per_sqm,
        'גודל (מ"ר)': lambda a: a.get("size_sqm"),
        "ימים בשוק": _days_on_market,
        "רחוב": lambda a: _street_name(a.get("address")),
    }
    if sort_field != "ללא מיון":
        keyfunc = SORT_FIELDS[sort_field]
        # דירות בלי הערך הזה (None) תמיד בסוף, בלי קשר לכיוון המיון
        with_val = [a for a in apartments if keyfunc(a) is not None]
        without_val = [a for a in apartments if keyfunc(a) is None]
        with_val.sort(key=keyfunc, reverse=sort_desc)
        apartments = with_val + without_val

    if apartments:
        df = pd.DataFrame(apartments)

        LOAD_BATCH = 24
        st.session_state.setdefault("load_count", LOAD_BATCH)

        map_df = df[df["lat"].notna() & df["lon"].notna()].copy()

        # פיזור עדין של מרקרים שחופפים בדיוק על אותה נקודה - נבדק מול ה-DB
        # ונמצאו קבוצות של עד 33 דירות פעילות על אותו lat/lon בדיוק (הרבה
        # כתובות מתגאקדות לאותה נקודה). בלי זה רק המרקר העליון בערימה בכלל
        # ניתן ללחיצה בדפדפן: קליק "נראה" כמו לחיצה על דירה מסוימת אבל בפועל
        # פותח דירה אקראית מהערימה (דווח כ"פותח דירה אחרת"), וכל הקליקים
        # החוזרים על אותו פיקסל מזוהים ע"י ה-guard למטה כ"אותו קליק בדיוק"
        # ונחסמים אחרי הפעם הראשונה (דווח כ"עובד רק פעם אחת"). פיזור מעגלי
        # של כ-12 מ' סביב הנקודה המקורית הופך כל דירה לבת-לחיצה בנפרד, וגם
        # נותן קואורדינטות שונות לכל דירה כך שה-guard מבחין נכון בין קליקים.
        if not map_df.empty:
            jittered_lat = map_df["lat"].astype(float).copy()
            jittered_lon = map_df["lon"].astype(float).copy()
            for (base_lat, base_lon), positions in map_df.groupby(["lat", "lon"]).indices.items():
                if len(positions) <= 1:
                    continue
                for i, pos in enumerate(positions):
                    angle = 2 * math.pi * i / len(positions)
                    radius_m = 12
                    dlat = (radius_m * math.cos(angle)) / 111_320
                    dlon = (radius_m * math.sin(angle)) / ((111_320 * math.cos(math.radians(base_lat))) or 1)
                    jittered_lat.iloc[pos] = base_lat + dlat
                    jittered_lon.iloc[pos] = base_lon + dlon
            map_df["lat"] = jittered_lat
            map_df["lon"] = jittered_lon

        # פתיחת הדיאלוג לפני שהרשת בכלל נבנית - לא עוצר את שאר הרינדור
        # (דיאלוגים ב-Streamlit לא עוצרים את הריצה, רק מוסיפים overlay).
        # לא pop-ים כאן בכוונה: כפתורי פעולה בתוך הדיאלוג (סמן כהוסרה/ראיתי/
        # לא רלוונטי) קוראים ל-st.rerun() כדי לרענן את עצמם, ואם היינו
        # מוחקים את המפתח כאן הדיאלוג היה נסגר לבד בלי שהמשתמש ביקש (זה
        # בדיוק הבאג שדווח - "הכפתור לא עובד", כשבפועל הפעולה כן קרתה
        # ב-DB אבל הדיאלוג נעלם בלי אישור). הניקוי היחיד הוא ב-on_dismiss.
        open_target = st.session_state.get("open_dialog_post_id")
        if open_target:
            target_apt = next((a for a in apartments if a.get("post_id") == open_target), None)
            if target_apt:
                _apt_dialog(target_apt)

        # אם הכרטיס שצריך לגלול אליו עדיין לא נטען (מעבר ל-load_count של
        # ה-infinite scroll) - מרחיבים את load_count כדי שיהיה קיים ב-DOM
        scroll_target = st.session_state.get("scroll_to_post_id")
        if scroll_target:
            idx = next((i for i, a in enumerate(apartments) if a.get("post_id") == scroll_target), None)
            if idx is not None and idx >= st.session_state["load_count"]:
                st.session_state["load_count"] = idx + 1

        col_grid, col_map = st.columns([7, 4])

        with col_map, st.container(key="map_sticky_container"):
            if map_df.empty:
                st.info("אין קואורדינטות עדיין — הן מחושבות אחרי הסריקה לפי כתובות שנמצאו בפוסטים.")
            else:
                focus_id = st.session_state.get("map_focus_post_id")
                focus_lat = st.session_state.get("map_focus_lat")
                focus_lon = st.session_state.get("map_focus_lon")
                is_focused_view = focus_lat is not None and focus_lon is not None

                if is_focused_view:
                    map_center, map_zoom = [focus_lat, focus_lon], 18
                    st.button(
                        "↩ חזרה לתצוגה הכללית", key="map_reset_focus", use_container_width=True,
                        on_click=lambda: (
                            st.session_state.pop("map_focus_post_id", None),
                            st.session_state.pop("map_focus_lat", None),
                            st.session_state.pop("map_focus_lon", None),
                        ),
                    )
                else:
                    map_center = [map_df["lat"].mean(), map_df["lon"].mean()]
                    map_zoom = 14

                m = folium.Map(
                    location=map_center,
                    zoom_start=map_zoom,
                    tiles="OpenStreetMap",
                )
                for _, row in map_df.iterrows():
                    price_str = f"{int(row['price']):,} ₪" if pd.notna(row.get("price")) and row.get("price") else "מחיר לא ידוע"
                    rooms_str = f"{_fmt_rooms(row.get('rooms'))} חד׳" if pd.notna(row.get("rooms")) and row.get("rooms") else ""
                    size_str  = f"{int(row['size_sqm'])} מ״ר" if pd.notna(row.get("size_sqm")) and row.get("size_sqm") else ""
                    floor_str = f"קומה {row['floor']}" if row.get("floor") else ""
                    addr_str  = row.get("address") or ""
                    source_str = {"facebook": "פייסבוק", "madlan": "מדלן", "yad2": "יד2", "dorin": "דורין", "yad2_project": "יד2 פרויקט", "komo": "קומו"}.get(row.get("source", ""), row.get("source", ""))

                    tags = []
                    if row.get("has_mamad"):    tags.append('ממ"ד')
                    if row.get("has_parking"):  tags.append("חניה")
                    if row.get("has_balcony"):  tags.append("מרפסת")
                    if row.get("has_elevator"): tags.append("מעלית")
                    tags_str = " · ".join(tags)

                    link_html = (f'<a href="{row["post_url"]}" target="_blank" style="color:#e53e3e;">פתח מודעה ←</a>'
                                 if row.get("post_url") else "")

                    days = _days_on_market(row.to_dict())
                    days_str = f"{days} ימים בשוק" if days is not None else ""

                    popup_html = f"""
                    <div dir="rtl" style="font-family:Arial,sans-serif;min-width:220px;line-height:1.7">
                        <div style="font-size:.8em;color:#888">{source_str}</div>
                        <b style="font-size:1.05em">{addr_str}</b><br>
                        <span style="color:#e53e3e;font-size:1.2em;font-weight:bold">{price_str}</span><br>
                        <span>{" &nbsp;·&nbsp; ".join(filter(None, [rooms_str, size_str, floor_str]))}</span><br>
                        {"<span style='color:#2d7d46'>✓ " + tags_str + "</span><br>" if tags_str else ""}
                        {"<span style='color:#888;font-size:.85em'>⏱ " + days_str + "</span><br>" if days_str else ""}
                        {link_html}
                        <div style="color:#2563eb;font-size:.85em;margin-top:6px">👆 לחצו על הנקודה במפה לפרטים מלאים</div>
                    </div>
                    """

                    is_focused = is_focused_view and row.get("post_id") == focus_id
                    color = "#2563eb" if is_focused else ("#2d7d46" if row.get("seen") else "#e53e3e")
                    folium.CircleMarker(
                        location=[row["lat"], row["lon"]],
                        radius=16 if is_focused else 10,
                        color=color,
                        fill=True,
                        fill_color=color,
                        fill_opacity=0.85,
                        weight=3 if is_focused else 2,
                        popup=folium.Popup(popup_html, max_width=280, show=is_focused),
                        tooltip=f"{addr_str} | {price_str}",
                    ).add_to(m)

                map_result = st_folium(m, width="100%", height=820, returned_objects=["last_object_clicked"])
                st.caption(f"{len(map_df)} דירות על המפה  |  ירוק = ראיתי")

                # לחיצה על מרקר פותחת ישירות את הדיאלוג - מחליף את מנגנון
                # הכפתור-בתוך-הפופ-אפ הקודם (JS שניסה לחצות מ-iframe של
                # streamlit_folium אל document.top ולא הצליח בעקביות, כנראה
                # בגלל sandbox של ה-component; retry לא עזר, כלומר זו לא
                # הייתה בעיית תזמון). זה הערוץ המובנה של st_folium - לא JS
                # מותאם אישית, ולכן לא תלוי במבנה ה-iframe בכלל.
                #
                # באג שנתפס: st_folium מחזיר את אותו last_object_clicked בכל
                # rerun (גם reruns שלא קשורים בכלל למפה - כמו שינוי פילטר!),
                # לא רק כשבאמת קליק חדש קרה. השוואה מול open_dialog_post_id
                # לא הספיקה כי הוא מתאפס כשסוגרים דיאלוג - אז קליק "ישן" היה
                # שוב נראה "חדש" בכל שינוי פילטר, גורם ל-rerun מתמיד שמנע
                # מהפילטרים בכלל להיקלט. עוקבים אחרי קואורדינטות הקליק
                # האחרון שכבר טופל בנפרד (מתאפס רק בסגירת דיאלוג, לא בכל
                # rerun), כדי להבחין קליק אמיתי-חדש מ-replay של הישן.
                clicked = map_result.get("last_object_clicked") if map_result else None
                if clicked and isinstance(clicked, dict) and clicked.get("lat") is not None:
                    click_key = (clicked["lat"], clicked["lng"])
                    if click_key != st.session_state.get("_last_map_click_coords"):
                        st.session_state["_last_map_click_coords"] = click_key
                        dists = ((map_df["lat"] - clicked["lat"]) ** 2 + (map_df["lon"] - clicked["lng"]) ** 2)
                        clicked_pid = map_df.loc[dists.idxmin(), "post_id"]
                        if clicked_pid:
                            st.session_state["scroll_to_post_id"] = clicked_pid
                            st.session_state["open_dialog_post_id"] = clicked_pid
                            st.rerun()

            # המפה "צפה" בזמן גלילה - CSS position:sticky לא עובד כאן כי
            # ה-wrapper המיידי של Streamlit מתאים את גובהו לתוכן (למפה עצמה)
            # ולא לגובה השורה המלאה, אז אין ל-sticky "מרחב" לזוז בתוכו.
            # לכן fixed-positioning ידני ב-JS, מחושב מול הגלילה של stMain.
            components.html("""
            <script>
            (function() {
                const doc = window.parent.document;
                const mainEl = doc.querySelector('[data-testid="stMain"]');
                const wrapper = doc.querySelector('.st-key-map_sticky_container');
                if (!mainEl || !wrapper) return;

                // כל render מריץ iframe חדש (Streamlit יכול להרוס את הישן) -
                // מחליפים את ה-listener הקודם בחדש במקום לצבור כפילויות או
                // להישאר עם listener מת מ-iframe שכבר נהרס
                if (mainEl._floatingMapHandler) {
                    mainEl.removeEventListener('scroll', mainEl._floatingMapHandler);
                }
                if (window.parent._floatingMapResizeHandler) {
                    window.parent.removeEventListener('resize', window.parent._floatingMapResizeHandler);
                }

                const TOP_OFFSET = 20;

                // מודדים מחדש בכל scroll (לא שומרים מיקום בסיס פעם אחת) -
                // תוכן שמתארך מתחת (עוד דירות שנטענות) יכול לשנות את המיקום
                // הטבעי של המפה, אז מדידה חד-פעמית מתיישנת. מבטלים fixed
                // זמנית כדי לקבל את המיקום האמיתי בזרימה הרגילה.
                function onScroll() {
                    const wasFixed = wrapper.style.position === 'fixed';
                    if (wasFixed) wrapper.style.position = '';
                    const rect = wrapper.getBoundingClientRect();

                    if (rect.top <= TOP_OFFSET) {
                        wrapper.style.position = 'fixed';
                        wrapper.style.top = TOP_OFFSET + 'px';
                        wrapper.style.left = rect.left + 'px';
                        wrapper.style.width = rect.width + 'px';
                        // גובה מקסימלי עד תחתית המסך - כך שהמפה לא תיחתך
                        // ע"י קצה החלון, עם גלילה פנימית אם היא עדיין גדולה מדי
                        wrapper.style.maxHeight = `calc(100vh - ${TOP_OFFSET * 2}px)`;
                        wrapper.style.overflowY = 'auto';
                        wrapper.style.zIndex = 999;
                    } else if (wasFixed) {
                        wrapper.style.position = '';
                        wrapper.style.top = '';
                        wrapper.style.left = '';
                        wrapper.style.width = '';
                        wrapper.style.maxHeight = '';
                        wrapper.style.overflowY = '';
                        wrapper.style.zIndex = '';
                    }
                }
                mainEl._floatingMapHandler = onScroll;
                window.parent._floatingMapResizeHandler = onScroll;
                mainEl.addEventListener('scroll', onScroll);
                window.parent.addEventListener('resize', onScroll);

                // כיווץ/הרחבה של הסיידבר (הכפתור <</>>) לא מייצר scroll או
                // resize של window.parent - זה רק משנה את הרוחב של stMain.
                // בלי זה, אם המפה הייתה fixed כשלחצו על הסיידבר, ה-left/width
                // המחושבים נשארים מהפריסה הישנה ומרחפים במקום הלא נכון.
                // ResizeObserver תופס כל שינוי גודל של mainEl, מכל סיבה שהיא.
                if (mainEl._floatingMapResizeObserver) {
                    mainEl._floatingMapResizeObserver.disconnect();
                }
                const ro = new ResizeObserver(onScroll);
                ro.observe(mainEl);
                mainEl._floatingMapResizeObserver = ro;

                onScroll();
            })();
            </script>
            """, height=1)

        with col_grid:
            load_count = st.session_state["load_count"]
            visible_apts = apartments[:load_count]
            has_more = load_count < len(apartments)

            selected_for_merge = [
                a for a in visible_apts
                if st.session_state.get(f"mergesel_{a.get('post_id') or str(id(a))}")
            ]
            if len(selected_for_merge) >= 2:
                mbar1, mbar2 = st.columns([3, 1])
                with mbar1:
                    st.info(f"🔗 נבחרו {len(selected_for_merge)} דירות לאיחוד ידני")
                with mbar2:
                    if st.button("אחד דירות", type="primary", use_container_width=True):
                        all_ids = []
                        for a in selected_for_merge:
                            all_ids.extend(a.get("_member_post_ids") or [a.get("post_id")])
                        merge_manually(all_ids)
                        for a in selected_for_merge:
                            st.session_state.pop(f"mergesel_{a.get('post_id') or str(id(a))}", None)
                        st.success("הדירות אוחדו!")
                        st.rerun()

            CARDS_PER_ROW = 3
            for row_start in range(0, len(visible_apts), CARDS_PER_ROW):
                row_apts = visible_apts[row_start:row_start + CARDS_PER_ROW]
                cols = st.columns(CARDS_PER_ROW)
                for col, apt in zip(cols, row_apts):
                    with col:
                        _render_apt_card(apt)

            if scroll_target:
                # window.top ולא window.parent - הפופ-אפ במפה חי בתוך ה-iframe
                # של streamlit_folium, ו-window.top תמיד מגיע לדף העליון בלי
                # קשר לכמה רמות iframe יש בדרך (בניגוד ל-parent שעולה רמה אחת)
                components.html(f"""
                <script>
                (function() {{
                    const doc = window.top.document;
                    const card = doc.querySelector('.st-key-apt_card_{scroll_target}');
                    if (card) {{
                        card.scrollIntoView({{behavior: 'smooth', block: 'center'}});
                        card.style.transition = 'box-shadow .3s';
                        card.style.boxShadow = '0 0 0 4px #2563eb';
                        setTimeout(() => {{ card.style.boxShadow = ''; }}, 2500);
                    }}
                }})();
                </script>
                """, height=1)
                st.session_state.pop("scroll_to_post_id", None)

            if has_more:
                if st.button("⬇ טען עוד", key="_infinite_load_more", use_container_width=True):
                    st.session_state["load_count"] += LOAD_BATCH
                    st.rerun()

                # גלילה כמעט עד לכפתור "טען עוד" מפעילה אותו אוטומטית - מדמה
                # infinite scroll. חייב components.v1.html (לא st.html) כי
                # st.html מכניס תוכן דרך innerHTML שלא מריץ <script> בכלל;
                # components.html יוצר iframe אמיתי עם srcdoc שבו script רץ.
                # בדיקת מיקום ב-polling דרך window.frameElement (לא
                # IntersectionObserver) כי חציית גבול iframe עם root:null לא
                # אמינה בין דפדפנים. חייב תוכן ייחודי בכל render (load_count)
                # כדי שהאלמנט לא יחשב "זהה" ולא יטען מחדש.
                components.html(f"""
                <div data-load-count="{load_count}"></div>
                <script>
                (function() {{
                    let triggered = false;
                    const check = () => {{
                        if (triggered) return;
                        const rect = window.frameElement.getBoundingClientRect();
                        if (rect.top < window.parent.innerHeight + 600) {{
                            triggered = true;
                            clearInterval(timer);
                            const btn = Array.from(window.parent.document.querySelectorAll('button'))
                                .find(b => b.innerText.trim() === '⬇ טען עוד');
                            if (btn) btn.click();
                        }}
                    }};
                    const timer = setInterval(check, 300);
                    check();
                }})();
                </script>
                """, height=1)
    else:
        st.info("לא נמצאו דירות — נסה להרחיב את המסננים או להריץ סריקה")

    st.divider()
    if st.button("🔍 סרוק עכשיו", type="primary", use_container_width=True):
        import subprocess, sys

        status_box = st.empty()
        messages = []
        with st.spinner("סורק... (חלון דפדפן ייפתח)"):
            proc = subprocess.Popen(
                [sys.executable, "scrapers/scraper.py"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                cwd=str(APP_DIR),
            )
            results = {"new_apartments": 0, "groups_scanned": 0, "errors": []}
            for line in proc.stdout:
                line = line.strip()
                if line.startswith("__RESULT__:"):
                    import json as _j
                    results = _j.loads(line[len("__RESULT__:"):])
                else:
                    messages.append(line)
                    status_box.info("\n".join(messages[-5:]))
            proc.wait()

        st.success(f"הסריקה הסתיימה! {results['new_apartments']} דירות חדשות מתוך {results['groups_scanned']} קבוצות")
        if results["errors"]:
            st.warning("שגיאות: " + ", ".join(results["errors"]))
        st.rerun()

    missing_geo = sum(1 for a in apartments_all if a.get("address") and not a.get("lat"))
    if missing_geo:
        if st.button(f"📍 עדכן מיקומים חסרים במפה ({missing_geo})", use_container_width=True):
            import subprocess, sys

            geo_status = st.empty()
            with st.spinner(f"ממיר {missing_geo} כתובות לקואורדינטות... (כ-{missing_geo} שניות, מוגבל ל-1 בשנייה)"):
                proc = subprocess.Popen(
                    [sys.executable, "core/geocoder.py"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    cwd=str(APP_DIR),
                )
                for line in proc.stdout:
                    geo_status.info(line.strip())
                proc.wait()

            st.success("המיקומים עודכנו!")
            st.rerun()

# ── Settings page ─────────────────────────────────────────────────────────────

elif page == "הגדרות":
    st.title("הגדרות חיפוש")
    config = load_config()

    st.subheader("מיקום ומילות חיפוש")
    location = st.text_input("עיר / אזור", config["חיפוש"].get("מיקום", ""))
    search_terms_raw = st.text_area(
        "מילות חיפוש לקבוצות (כל שורה = מילה אחת)",
        "\n".join(config["חיפוש"].get("מילות_חיפוש_קבוצות", [])),
        height=100,
    )

    st.subheader("מסנני נתונים")
    c1, c2 = st.columns(2)
    with c1:
        min_rooms  = st.number_input("חדרים מינימום",   1.0, 10.0, float(config["חדרים"]["מינימום"]), 0.5)
        max_rooms  = st.number_input("חדרים מקסימום",   1.0, 10.0, float(config["חדרים"]["מקסימום"]), 0.5)
        min_price  = st.number_input("מחיר מינימום ₪",  0, 20_000_000, config["מחיר"]["מינימום"], 50_000)
        max_price  = st.number_input("מחיר מקסימום ₪",  0, 20_000_000, config["מחיר"]["מקסימום"], 50_000)
    with c2:
        min_size   = st.number_input("גודל מינימום מ״ר", 20, 500, config["גודל_במטר"]["מינימום"], 5)
        max_size   = st.number_input("גודל מקסימום מ״ר", 20, 500, config["גודל_במטר"]["מקסימום"], 5)
        only_price = st.checkbox("רק פוסטים עם מחיר", config["מחיר"].get("רק_פוסטים_עם_מחיר", True))
        scan_hours = st.number_input("סריקה אוטומטית כל X שעות", 1, 24, config["סריקה"].get("כל_כמה_שעות", 2))

    st.subheader("מקורות סריקה")
    include_facebook = st.checkbox(
        "כלול פייסבוק בסריקה",
        config["סריקה"].get("כלול_פייסבוק", True),
        help="בטל אם פייסבוק חוסם את הסריקה — הסריקה תרוץ רק על מדלן ויד2",
    )

    st.subheader("מילות מפתח")
    required_raw = st.text_area(
        "מילות חובה (כל שורה = מילה, ריק = בלי חובה)",
        "\n".join(config.get("מילות_מפתח_חובה", [])), height=80,
    )
    blocked_raw = st.text_area(
        "מילות חסימה", "\n".join(config.get("מילות_חסימה", [])), height=80,
    )

    if st.button("שמור הגדרות", type="primary"):
        config["חיפוש"]["מיקום"] = location
        config["חיפוש"]["מילות_חיפוש_קבוצות"] = [l.strip() for l in search_terms_raw.splitlines() if l.strip()]
        config["חדרים"]        = {"מינימום": min_rooms, "מקסימום": max_rooms}
        config["מחיר"]         = {"מינימום": min_price, "מקסימום": max_price, "רק_פוסטים_עם_מחיר": only_price}
        config["גודל_במטר"]    = {"מינימום": min_size,  "מקסימום": max_size}
        config["מילות_מפתח_חובה"] = [l.strip() for l in required_raw.splitlines() if l.strip()]
        config["מילות_חסימה"]  = [l.strip() for l in blocked_raw.splitlines() if l.strip()]
        config["סריקה"]["כל_כמה_שעות"] = scan_hours
        config["סריקה"]["כלול_פייסבוק"] = include_facebook
        save_config(config)
        st.success("ההגדרות נשמרו!")

# ── Groups page ───────────────────────────────────────────────────────────────

elif page == "קבוצות":
    st.title("קבוצות פייסבוק")
    groups = get_groups()
    if groups:
        df = pd.DataFrame(groups)[["group_name", "group_id", "added_at"]]
        df.columns = ["שם הקבוצה", "ID", "נוסף בתאריך"]
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("עדיין לא נמצאו קבוצות — הרץ סריקה ראשונה מעמוד התוצאות")
