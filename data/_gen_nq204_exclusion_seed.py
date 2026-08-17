# -*- coding: utf-8 -*-
"""Sinh seed danh mục KHÔNG được giảm thuế NQ 204 / NĐ 174 từ OCR đã có.

Không chôn mức giảm / hiệu lực vào Python nghiệp vụ — chỉ script sinh XML một lần.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3] / 'docs' / 'nguon' / '_gtgt_law_extract'
OUT = Path(__file__).with_name('vas_gtgt_reduction_exclusion_seed.xml')

DATE_START = '2025-07-01'
DATE_END = '2026-12-31'

# Nhóm cấp cao (Điều 1 NĐ 174 + cấu trúc Phụ lục I) — mã VSIC Cap.
MANUAL_VSIC = [
    ('06', 'Sản phẩm khai khoáng — dầu khí (nhóm)', 'I'),
    ('07', 'Quặng kim loại và tinh quặng kim loại (nhóm)', 'I'),
    ('08', 'Sản phẩm khai khoáng khác (nhóm)', 'I'),
    ('24', 'Sản phẩm kim loại (nhóm)', 'I'),
    ('61', 'Viễn thông (nhóm)', 'I'),
    ('64', 'Dịch vụ tài chính (trừ BH và quỹ hưu trí) (nhóm)', 'I'),
    ('65', 'Bảo hiểm, tái BH và quỹ hưu trí (nhóm)', 'I'),
    ('66', 'Hoạt động hỗ trợ dịch vụ tài chính (nhóm)', 'I'),
    ('68', 'Dịch vụ kinh doanh bất động sản (nhóm)', 'I'),
]

# Phụ lục II — HH/DV chịu TTĐB (trừ xăng). Nhận diện theo mã nhóm TTĐB.
TTDB = [
    ('TTDB_TOBACCO', 'Thuốc lá / chế phẩm từ cây thuốc lá'),
    ('TTDB_ALCOHOL', 'Rượu'),
    ('TTDB_BEER', 'Bia'),
    ('TTDB_CAR', 'Xe ô tô dưới 24 chỗ / pick-up (TTĐB)'),
    ('TTDB_MOTO', 'Xe mô tô dung tích trên 125 cm³'),
    ('TTDB_AIRCRAFT', 'Tàu bay / máy bay / trực thăng / tàu lượn / du thuyền'),
    ('TTDB_AC', 'Điều hòa nhiệt độ thuộc diện TTĐB'),
    ('TTDB_PLAYING_CARDS', 'Bài lá'),
    ('TTDB_VOTIVE', 'Vàng mã, hàng mã (trừ đồ chơi / đồ dùng dạy học theo PL II)'),
    ('TTDB_SOFTDRINK_SUGAR', 'Nước giải khát đường >5g/100ml (từ 01/01/2026)'),
    ('TTDB_DISCotheque', 'Kinh doanh vũ trường'),
    ('TTDB_MASSAGE_KARAOKE', 'Kinh doanh massage, karaoke'),
    ('TTDB_CASINO', 'Casino / trò chơi điện tử có thưởng'),
    ('TTDB_BETTING', 'Kinh doanh đặt cược'),
    ('TTDB_GOLF', 'Kinh doanh golf'),
    ('TTDB_LOTTERY', 'Kinh doanh xổ số'),
]


def _load_ocr() -> str:
    parts = []
    for name in ('174_ocr.txt', '174_tail_ocr.txt'):
        p = ROOT / name
        if p.exists():
            parts.append(p.read_text(encoding='utf-8', errors='ignore'))
    return '\n'.join(parts)


def _extract_vsic(text: str) -> list[tuple[str, str]]:
    # Mã Cap 2–7 chữ số bắt đầu 0/1/2/6 (khớp cấu trúc PL I trong OCR)
    found = sorted(set(re.findall(
        r'\b((?:0[6-9]|1[0-9]|2[0-4]|6[0-9])\d{0,5})\b', text,
    )), key=lambda c: (len(c), c))
    rows = []
    for code in found:
        if len(code) < 2:
            continue
        rows.append((code, 'PL I — mã Cap %s (OCR NĐ 174)' % code))
    return rows


def _extract_hs(text: str) -> list[tuple[str, str]]:
    found = sorted(set(re.findall(r'\b(\d{4}\.\d{2}(?:\.\d{2})?)\b', text)))
    return [(hs, 'PL I — mã HS %s (khâu NK)' % hs) for hs in found]


def main():
    text = _load_ocr()
    vsic_auto = _extract_vsic(text)
    hs_auto = _extract_hs(text)

    seen = set()
    records = []

    def add(xml_id, code, name, kind, annex):
        key = (kind, code)
        if key in seen:
            return
        seen.add(key)
        records.append((xml_id, code, name, kind, annex))

    for code, name, annex in MANUAL_VSIC:
        add('excl_vsic_%s' % code, code, name, 'vsic', annex)
    for code, name in vsic_auto:
        add('excl_vsic_%s' % code, code, name, 'vsic', 'I')
    for hs, name in hs_auto:
        xid = 'excl_hs_%s' % hs.replace('.', '_')
        add(xid, hs, name, 'hs', 'I')
    for code, name in TTDB:
        add('excl_%s' % code.lower(), code, name, 'ttdb', 'II')

    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<odoo noupdate="1">',
        '    <!-- Danh mục HH/DV KHÔNG được giảm GTGT — NĐ 174/2025 Phụ lục I+II.',
        '         Hiệu lực: 01/07/2025 → 31/12/2026 (NQ 204 + NĐ 174).',
        '         Sinh từ OCR + nhóm cấp cao; gia hạn/đổi danh mục → chỉ sửa dữ liệu. -->',
    ]
    for i, (xid, code, name, kind, annex) in enumerate(records, 1):
        lines += [
            '    <record id="%s" model="vas.gtgt.reduction.exclusion">' % xid,
            '        <field name="sequence">%s</field>' % (i * 10),
            '        <field name="code">%s</field>' % code,
            '        <field name="name">%s</field>' % name.replace('&', '&amp;'),
            '        <field name="code_kind">%s</field>' % kind,
            '        <field name="annex">%s</field>' % annex,
            '        <field name="date_start">%s</field>' % DATE_START,
            '        <field name="date_end">%s</field>' % DATE_END,
            '    </record>',
        ]
    lines.append('</odoo>')
    OUT.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('Wrote', OUT, 'records', len(records))


if __name__ == '__main__':
    main()
