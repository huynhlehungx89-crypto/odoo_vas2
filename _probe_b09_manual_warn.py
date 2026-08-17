# -*- coding: utf-8 -*-
"""Đối chiếu đếm cảnh báo người điền B09 trên W11 — chỉ đọc, không sửa kho."""
from odoo.addons.connecta_vas.models.vas_b09_entry import (
    B09_AMOUNT_CODES,
    B09_TABLE_CODES,
    B09_TEXT_CODES,
)

env['res.company']._vas_w11_ensure_bctc_demo()
co = env['res.company'].search([('name', '=', 'W11-Thử BCTC')], limit=1)
p01 = env['vas.period'].search([
    ('fiscalyear_id.company_id', '=', co.id),
    ('date_start', '=', '2026-01-01'),
], limit=1)
p12 = env['vas.period'].search([
    ('fiscalyear_id.company_id', '=', co.id),
    ('date_start', '=', '2026-12-01'),
], limit=1)
# Lập B01a/B02/B09 mới để lấy cảnh báo đếm (không xóa entry sẵn có trên DB sống)
Snap = env['vas.report.snapshot']
if not Snap._find_period_snapshot('B01a-DNN', co, p01, p12):
    Snap.generate_b01a(co, p01, p12, hide_reversed=True)
if not Snap._find_period_snapshot('B02-DNN', co, p01, p12):
    Snap.generate_b02(co, p01, p12, hide_reversed=True)
# Đảm bảo gợi ý/đếm theo đúng generate
snap = Snap.generate_b09(co, p01, p12, hide_reversed=True, copy_prior_year=True)
by_entry = env['vas.b09.entry'].map_for_period(co, p01, p12)


def _empty(kind_codes):
    n = 0
    for c in kind_codes:
        e = by_entry.get(c)
        if not e or not e.is_filled():
            n += 1
    return n


empty_text = _empty(B09_TEXT_CODES)
empty_amt = _empty(B09_AMOUNT_CODES)
empty_tab = _empty(B09_TABLE_CODES)
empty_hand = empty_text + empty_amt + empty_tab
unconf_hand = 0
for c in (B09_TEXT_CODES + B09_AMOUNT_CODES + B09_TABLE_CODES):
    e = by_entry.get(c)
    if e and e.is_filled() and (not e.is_confirmed) and e.origin in (
        'suggestion', 'copied_prior',
    ):
        unconf_hand += 1

import json
meta = json.loads(snap.meta_json or '{}')
print('WARN_RAW_EMPTY')
for line in (snap.warning_text or '').splitlines():
    if 'trống' in line or 'xác nhận' in line or 'người điền' in line:
        print(line)
print('META_EMPTY', meta.get('b09_manual_empty_count'))
print('META_UNCONF', meta.get('b09_manual_unconfirmed_count'))
print('HAND_EMPTY_TEXT', empty_text, 'of', len(B09_TEXT_CODES))
print('HAND_EMPTY_AMT', empty_amt, 'of', len(B09_AMOUNT_CODES))
print('HAND_EMPTY_TAB', empty_tab, 'of', len(B09_TABLE_CODES))
print('HAND_EMPTY_TOTAL', empty_hand)
print('HAND_UNCONF', unconf_hand)
print('MATCH_EMPTY', empty_hand == meta.get('b09_manual_empty_count'))
print('MATCH_UNCONF', unconf_hand == meta.get('b09_manual_unconfirmed_count'))
# Liệt kê mã trống theo dạng
print('EMPTY_TEXT_CODES', [c for c in B09_TEXT_CODES if c not in by_entry or not by_entry[c].is_filled()])
print('EMPTY_AMT_CODES', [c for c in B09_AMOUNT_CODES if c not in by_entry or not by_entry[c].is_filled()])
print('EMPTY_TAB_CODES', [c for c in B09_TABLE_CODES if c not in by_entry or not by_entry[c].is_filled()])
filled = [c for c in (B09_TEXT_CODES + B09_AMOUNT_CODES + B09_TABLE_CODES)
          if c in by_entry and by_entry[c].is_filled()]
print('FILLED', [(c, by_entry[c].origin, by_entry[c].is_confirmed) for c in filled])
