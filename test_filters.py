import sys
sys.path.insert(0, '.')
from scraper import passes_filters, extract_price, extract_rooms, extract_size

config = {
    'חדרים': {'מינימום': 4, 'מקסימום': 5},
    'מחיר': {'רק_פוסטים_עם_מחיר': True, 'מינימום': 3_000_000, 'מקסימום': 4_000_000},
    'גודל_במטר': {'מינימום': 95, 'מקסימום': 150},
    'מילות_מפתח_חובה': [],
    'מילות_חסימה': ['שותפים', 'שותף', 'דרושים'],
}

tests = [
    ('עובר - תקין',          'דירת 4 חדרים 110 מ"ר קומה 3, ממ"ד, חניה, מחיר 3,500,000 שח'),
    ('נכשל - יקר מדי',       'דירת 4 חדרים 110 מ"ר ממ"ד חניה מחיר 5,000,000 שח'),
    ('נכשל - קטן מדי',       'דירת 4 חדרים 80 מ"ר ממ"ד מחיר 3,200,000 שח'),
    ('נכשל - מעט חדרים',     'דירת 3 חדרים 120 מ"ר מחיר 3,400,000 שח'),
    ('נכשל - אין מחיר',      'דירת 4 חדרים 100 מ"ר ממ"ד חניה'),
    ('עובר - גבול עליון',    'דירת 5 חדרים 150 מ"ר ממ"ד חניה מחיר 4,000,000 שח'),
    ('נכשל - מילת חסימה',    'דירת 4 חדרים 110 מ"ר שותפים מחיר 3,500,000 שח'),
]

import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

print(f"{'תיאור':<25} {'מחיר':>12} {'חדרים':>7} {'מר':>5} {'עובר?':>7}")
print('-' * 60)
for label, text in tests:
    price = extract_price(text)
    rooms = extract_rooms(text)
    size  = extract_size(text)
    data  = {'text': text, 'price': price, 'rooms': rooms, 'size_sqm': size}
    result = passes_filters(data, config)
    mark = 'V' if result else 'X'
    print(f"{label:<25} {str(price or '-'):>12} {str(rooms or '-'):>7} {str(size or '-'):>5} {mark:>7}")
