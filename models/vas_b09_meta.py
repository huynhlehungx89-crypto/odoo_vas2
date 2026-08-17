# -*- coding: utf-8 -*-
"""Phân loại dòng B09-DNN — nguồn sự thật cho seed + migration + test.

fill_kind:
  machine_now — máy lấy được ngay (sổ hoặc bản B01a/B02)
  machine_gap — máy lấy được nếu bổ sung dữ liệu/engine
  manual — kế toán tự điền
  na — không áp dụng
  section — mục/khung (không phải ô số chi tiết)

table_status (trên dòng mục bảng):
  full — máy điền đủ
  total_ok_detail_open — máy điền tổng; chi tiết còn mở (tự điền / chưa nối / thiếu data)
  none_yet — máy chưa lấy được số
  manual_all — kế toán tự điền toàn bộ
"""

# (fill_kind, basis_kind, basis_or_source_note, gap_reason_or_empty)
# basis_kind chỉ bắt buộc với machine_now / machine_gap.

def _m(fill, basis, note, gap=''):
    return {
        'fill_kind': fill,
        'basis_kind': basis,
        'basis_note': note,
        'gap_reason': gap,
    }


LINE_META = {}

# ---- I manual ----
LINE_META['I'] = _m('section', 'trich_tt133', '15583 trang 9; 15581 §2.5.4.1')
for i in range(1, 7):
    LINE_META['I.%s' % i] = _m(
        'manual', 'trich_tt133', '15583 trang 9 — diễn giải đặc điểm HĐDN',
    )

# ---- II: kỳ KT / ĐVTT — máy có nguồn company/FY nhưng text chưa điền → machine_now nguồn rõ ----
LINE_META['II'] = _m('section', 'trich_tt133', '15583 trang 9; 15581 §2.5.4.2')
LINE_META['II.1'] = _m(
    'machine_now', 'chot_connecta',
    'vas.fiscalyear date_from/date_to công ty',
)
LINE_META['II.2'] = _m(
    'machine_now', 'chot_connecta',
    'res.company.currency_id',
)

# ---- III manual ----
LINE_META['III'] = _m('section', 'trich_tt133', '15583 trang 9; 15581 §2.5.4.3')
LINE_META['III.1'] = _m('manual', 'trich_tt133', 'Tuyên bố tuân thủ — nhập tay')

# ---- IV manual ----
LINE_META['IV'] = _m('section', 'trich_tt133', '15583 trang 9–10; 15581 §2.5.4.4')
for i in range(1, 13):
    LINE_META['IV.%s' % i] = _m('manual', 'trich_tt133', 'Chính sách KT — nhập tay')

# ---- V ----
LINE_META['V'] = _m('section', 'trich_tt133', '15583 trang 10; 15581 §2.5.5')

LINE_META['V.1'] = _m('section', 'trich_tt133', '15583 trang 10')
LINE_META['V.1.cash'] = _m('machine_now', 'trich_tt133', 'SD Nợ TK 111 (+ con)')
LINE_META['V.1.bank'] = _m('machine_now', 'trich_tt133', 'SD Nợ TK 112 (+ con)')
LINE_META['V.1.equiv'] = _m(
    'machine_gap', 'chot_connecta', '15583 trang 10',
    'thiếu cờ tương đương tiền trên 1281/1288 (C1)',
)
LINE_META['V.1.total'] = _m('machine_now', 'trich_tt133', 'Bản B01a đã lập — mã 110')

LINE_META['V.2'] = _m('section', 'trich_tt133', '15583 trang 10')
LINE_META['V.2a'] = _m('section', 'trich_tt133', '15583 trang 10')
LINE_META['V.2a.stock'] = _m(
    'machine_gap', 'trich_tt133', '15583 trang 10',
    'thiếu phân loại cổ phiếu trên sổ / thẻ đầu tư',
)
LINE_META['V.2a.bond'] = _m(
    'machine_gap', 'trich_tt133', '15583 trang 10',
    'thiếu phân loại trái phiếu trên sổ / thẻ đầu tư',
)
LINE_META['V.2a.other'] = _m(
    'machine_gap', 'trich_tt133', '15583 trang 10',
    'thiếu phân loại chứng khoán khác trên sổ',
)
LINE_META['V.2a.total'] = _m('machine_now', 'trich_tt133', 'Bản B01a đã lập — mã 121')

LINE_META['V.2b'] = _m('section', 'trich_tt133', '15583 trang 10')
LINE_META['V.2b.deposit'] = _m('machine_now', 'trich_tt133', 'SD Nợ TK 1281 (+ con)')
LINE_META['V.2b.other'] = _m('machine_now', 'trich_tt133', 'SD Nợ TK 1288 (+ con)')
LINE_META['V.2b.total'] = _m('machine_now', 'trich_tt133', 'Bản B01a đã lập — mã 122')

LINE_META['V.2c'] = _m('section', 'trich_tt133', '15583 trang 10')
LINE_META['V.2c.sec'] = _m('machine_now', 'trich_tt133', 'SD Có TK 2291')
LINE_META['V.2c.other'] = _m('machine_now', 'trich_tt133', 'SD Có TK 2292')
LINE_META['V.2c.total'] = _m('machine_now', 'trich_tt133', 'Bản B01a đã lập — mã 124')

LINE_META['V.3'] = _m('section', 'trich_tt133', '15583 trang 10–11')
LINE_META['V.3a'] = _m('section', 'trich_tt133', '15583 trang 10')
LINE_META['V.3a.related'] = _m(
    'machine_gap', 'trich_tt133', '15583 trang 10',
    'thiếu master/cờ bên liên quan trên partner',
)
LINE_META['V.3a.total'] = _m('machine_now', 'trich_tt133', 'Bản B01a đã lập — mã 131')

LINE_META['V.3b'] = _m('section', 'trich_tt133', '15583 trang 10')
LINE_META['V.3b.related'] = _m(
    'machine_gap', 'trich_tt133', '15583 trang 10',
    'thiếu cờ bên liên quan trên partner',
)
LINE_META['V.3b.total'] = _m('machine_now', 'trich_tt133', 'Bản B01a đã lập — mã 132')

LINE_META['V.3c'] = _m('section', 'trich_tt133', '15583 trang 11')
LINE_META['V.3c.loan'] = _m(
    'machine_gap', 'chot_connecta', '15583 trang 11',
    'thiếu tách cho vay trên 1288 (C1)',
)
LINE_META['V.3c.advance'] = _m('machine_now', 'trich_tt133', 'SD Nợ TK 141 (+ con)')
LINE_META['V.3c.internal'] = _m(
    'machine_now', 'trich_tt133', 'SD Nợ TK 1361,1368 (+ con)',
)
LINE_META['V.3c.other'] = _m('machine_now', 'trich_tt133', 'SD Nợ TK 1388 (+ con)')
LINE_META['V.3c.total'] = _m('machine_now', 'trich_tt133', 'Bản B01a đã lập — mã 134')

LINE_META['V.3d'] = _m('section', 'trich_tt133', '15583 trang 11')
for suf, gap in [
    ('cash', 'thiếu phân loại TS thiếu = tiền trên dòng'),
    ('inv', 'thiếu phân loại TS thiếu = HTK trên dòng'),
    ('fa', 'thiếu phân loại TS thiếu = TSCĐ trên dòng'),
    ('other', 'thiếu phân loại TS thiếu = khác trên dòng'),
]:
    LINE_META['V.3d.%s' % suf] = _m(
        'machine_gap', 'trich_tt133', '15583 trang 11', gap,
    )
LINE_META['V.3d.total'] = _m('machine_now', 'trich_tt133', 'Bản B01a đã lập — mã 135')

LINE_META['V.3đ'] = _m('section', 'trich_tt133', '15583 trang 11')
LINE_META['V.3đ.total'] = _m(
    'machine_gap', 'trich_tt133', '15583 trang 11 — Nợ xấu',
    'thiếu model phân loại nợ xấu / tuổi nợ VAS',
)

LINE_META['V.4'] = _m('section', 'trich_tt133', '15583 trang 11')
for code, note in [
    ('V.4.transit', 'SD TK 151'),
    ('V.4.material', 'SD TK 152'),
    ('V.4.tool', 'SD TK 153'),
    ('V.4.wip', 'SD TK 154'),
    ('V.4.fg', 'SD TK 155'),
    ('V.4.merch', 'SD TK 156'),
    ('V.4.consign', 'SD TK 157'),
]:
    LINE_META[code] = _m('machine_now', 'trich_tt133', note)
LINE_META['V.4.total'] = _m('machine_now', 'trich_tt133', 'Bản B01a đã lập — mã 141')
LINE_META['V.4.stagnant'] = _m(
    'machine_gap', 'trich_tt133', '15583 trang 11',
    'thiếu cờ HTK ứ đọng / kém phẩm chất',
)
LINE_META['V.4.pledged'] = _m(
    'machine_gap', 'trich_tt133', '15583 trang 11',
    'thiếu cờ HTK thế chấp / cầm cố',
)

LINE_META['V.5'] = _m('section', 'trich_tt133', '15583 trang 11–12')
_V5_BLOCKS = {
    'tangible': ('2111', '2141', 'HH'),
    'intangible': ('2113', '2143', 'VH'),
    'lease': ('2112', '2142', 'thuê TC'),
}
for block, (cost_tk, accum_tk, label) in _V5_BLOCKS.items():
    LINE_META['V.5.%s' % block] = _m('section', 'trich_tt133', '15583 trang 11–12')
    LINE_META['V.5.%s.cost' % block] = _m(
        'machine_now', 'trich_tt133',
        'SD/PS TK %s — bảng tăng giảm TSCĐ %s' % (cost_tk, label),
    )
    LINE_META['V.5.%s.accum' % block] = _m(
        'machine_now', 'trich_tt133',
        'SD/PS TK %s — hao mòn TSCĐ %s' % (accum_tk, label),
    )
    LINE_META['V.5.%s.net' % block] = _m(
        'machine_now', 'trich_tt133',
        'Nguyên giá − hao mòn lũy kế (%s)' % label,
    )

LINE_META['V.6'] = _m('section', 'trich_tt133', '15583 trang 12')
LINE_META['V.6.cost'] = _m(
    'machine_now', 'trich_tt133', 'SD/PS TK 217 — bảng tăng giảm BĐSĐT',
)
LINE_META['V.6.accum'] = _m(
    'machine_now', 'trich_tt133', 'SD/PS TK 2147 — hao mòn BĐSĐT',
)
LINE_META['V.6.net'] = _m(
    'machine_now', 'trich_tt133', 'Nguyên giá − hao mòn lũy kế (BĐSĐT)',
)
LINE_META['V.6.rent'] = _m(
    'machine_gap', 'trich_tt133', '15583 trang 12',
    'thiếu phân loại BĐSĐT cho thuê vs chờ tăng giá (TK 217 chung)',
)
LINE_META['V.6.hold'] = _m(
    'machine_gap', 'trich_tt133', '15583 trang 12',
    'thiếu phân loại BĐSĐT chờ tăng giá (TK 217 chung)',
)

LINE_META['V.7'] = _m('section', 'trich_tt133', '15583 trang 13')
LINE_META['V.7.buy'] = _m('machine_now', 'trich_tt133', 'SD Nợ TK 2411 (+ con)')
LINE_META['V.7.cip'] = _m('machine_now', 'trich_tt133', 'SD Nợ TK 2412 (+ con)')
LINE_META['V.7.repair'] = _m('machine_now', 'trich_tt133', 'SD Nợ TK 2413 (+ con)')
LINE_META['V.7.total'] = _m('machine_now', 'trich_tt133', 'Bản B01a đã lập — mã 170')

LINE_META['V.8'] = _m('section', 'trich_tt133', '15583 trang 13')
LINE_META['V.8.prepaid'] = _m(
    'machine_gap', 'trich_tt133', '15583 trang 13',
    'thiếu tách ngắn/dài hạn trên 242',
)
LINE_META['V.8.tax_recv'] = _m(
    'machine_now', 'trich_tt133', 'SD Nợ TK 333 (+ con) — phải thu NSNN',
)

LINE_META['V.9'] = _m('section', 'trich_tt133', '15583 trang 13')
LINE_META['V.9a'] = _m('section', 'trich_tt133', '15583 trang 13')
LINE_META['V.9a.related'] = _m(
    'machine_gap', 'trich_tt133', '15583 trang 13',
    'thiếu cờ bên liên quan',
)
LINE_META['V.9a.total'] = _m('machine_now', 'trich_tt133', 'Bản B01a đã lập — mã 311')
LINE_META['V.9b'] = _m('section', 'trich_tt133', '15583 trang 13')
LINE_META['V.9b.related'] = _m(
    'machine_gap', 'trich_tt133', '15583 trang 13',
    'thiếu cờ bên liên quan',
)
LINE_META['V.9b.total'] = _m('machine_now', 'trich_tt133', 'Bản B01a đã lập — mã 312')
LINE_META['V.9c'] = _m('section', 'trich_tt133', '15583 trang 13')
LINE_META['V.9c.accrued'] = _m('machine_now', 'trich_tt133', 'SD Có TK 335 (+ con)')
LINE_META['V.9c.internal'] = _m(
    'machine_now', 'trich_tt133', 'SD Có TK 3361,3368 (+ con)',
)
LINE_META['V.9c.other'] = _m('machine_now', 'trich_tt133', 'SD Có TK 3388 (+ con)')
LINE_META['V.9c.total'] = _m('machine_now', 'trich_tt133', 'Bản B01a đã lập — mã 315')
LINE_META['V.9d'] = _m(
    'machine_gap', 'trich_tt133', '15583 trang 13',
    'thiếu tuổi nợ phải trả',
)

LINE_META['V.10'] = _m('section', 'trich_tt133', '15583 trang 13–14')
LINE_META['V.10.total'] = _m(
    'machine_gap', 'trich_tt133', '15583 trang 13–14 — thuế NSNN',
    'thiếu nhận diện số đã thực nộp thuế (nhãn thanh toán)',
)

LINE_META['V.11'] = _m('section', 'trich_tt133', '15583 trang 14')
LINE_META['V.11.st'] = _m(
    'machine_gap', 'trich_tt133', '15583 trang 14',
    'thiếu tách vay ngắn hạn trên báo cáo / 341',
)
LINE_META['V.11.lt'] = _m(
    'machine_gap', 'trich_tt133', '15583 trang 14',
    'thiếu tách vay dài hạn trên báo cáo / 341',
)
LINE_META['V.11.lease'] = _m('machine_now', 'trich_tt133', 'SD Có TK 3412 (+ con)')
LINE_META['V.11.total'] = _m('machine_now', 'trich_tt133', 'Bản B01a đã lập — mã 316')

LINE_META['V.12'] = _m('section', 'trich_tt133', '15583 trang 14')
LINE_META['V.12.warranty'] = _m('machine_now', 'trich_tt133', 'SD Có TK 3521 (+ con)')
LINE_META['V.12.construction'] = _m(
    'machine_now', 'trich_tt133', 'SD Có TK 3522 (+ con)',
)
LINE_META['V.12.other'] = _m('machine_now', 'trich_tt133', 'SD Có TK 3524 (+ con)')
LINE_META['V.12.total'] = _m('machine_now', 'trich_tt133', 'Bản B01a đã lập — mã 318')

LINE_META['V.13'] = _m('section', 'trich_tt133', '15583 trang 14–15')
LINE_META['V.13a'] = _m(
    'machine_gap', 'trich_tt133', '15583 trang 14–15',
    'thiếu bảng biến động VCSH đủ cột (tách quỹ vs LNST); nguyên nhân biến động',
)
LINE_META['V.13b'] = _m('manual', 'trich_tt133', 'Thuyết minh VCSH khác — nhập tay')

LINE_META['V.14'] = _m('section', 'trich_tt133', '15583 trang 15')
for code, gap in [
    ('V.14a', 'thiếu sổ ngoài bảng — tài sản thuê ngoài'),
    ('V.14b', 'thiếu sổ ngoài bảng — tài sản nhận giữ hộ'),
    ('V.14c', 'thiếu sổ ngoài bảng / memorandum nguyên tệ'),
    ('V.14d', 'thiếu sổ ngoài bảng — nợ khó đòi đã xử lý'),
    ('V.14đ', 'thiếu sổ ngoài bảng — phạt / lãi trả chậm không ghi DT'),
    ('V.14f', 'thiếu sổ ngoài bảng — thông tin khác'),
]:
    LINE_META[code] = _m('machine_gap', 'trich_tt133', '15583 trang 15', gap)

LINE_META['V.15'] = _m(
    'machine_gap', 'trich_tt133', '15583 trang 15',
    'thiếu master bên liên quan + giao dịch',
)
LINE_META['V.16'] = _m('manual', 'trich_tt133', 'Thông tin khác — nhập tay')

# ---- VI ----
LINE_META['VI'] = _m('section', 'trich_tt133', '15583 trang 15; 15581 §2.5.6')
LINE_META['VI.1'] = _m('section', 'trich_tt133', '15583 trang 15–16')
LINE_META['VI.1a'] = _m('section', 'trich_tt133', '15583 trang 15–16')
LINE_META['VI.1a.goods'] = _m(
    'machine_now', 'trich_tt133_chot_connecta', 'PS Có TK 5111 (+ con)',
)
LINE_META['VI.1a.fg'] = _m(
    'machine_now', 'trich_tt133_chot_connecta', 'PS Có TK 5112 (+ con)',
)
LINE_META['VI.1a.svc'] = _m(
    'machine_now', 'trich_tt133_chot_connecta', 'PS Có TK 5113 (+ con)',
)
LINE_META['VI.1a.other'] = _m(
    'machine_now', 'trich_tt133_chot_connecta', 'PS Có TK 5118 (+ con)',
)
LINE_META['VI.1a.total'] = _m('machine_now', 'trich_tt133', 'Bản B02 đã lập — mã 01')
LINE_META['VI.1b'] = _m(
    'machine_gap', 'trich_tt133', '15583 trang 15–16',
    'thiếu cờ bên liên quan trên doanh thu',
)
LINE_META['VI.1c'] = _m(
    'machine_gap', 'trich_tt133', '15583 trang 15–16',
    'thiếu lịch phân bổ DT nhận trước / 3387',
)

LINE_META['VI.2'] = _m('section', 'trich_tt133', '15583 trang 16')
for code, gap in [
    ('VI.2.discount', 'thiếu tách chiết khấu thương mại trên sổ'),
    ('VI.2.markdown', 'thiếu tách giảm giá hàng bán trên sổ'),
    ('VI.2.return', 'thiếu tách hàng bán bị trả lại trên sổ'),
]:
    LINE_META[code] = _m('machine_gap', 'trich_tt133', '15583 trang 16', gap)
LINE_META['VI.2.total'] = _m('machine_now', 'trich_tt133', 'Bản B02 đã lập — mã 02')

LINE_META['VI.3'] = _m('section', 'trich_tt133', '15583 trang 16')
for code, gap in [
    ('VI.3.goods', 'thiếu tách GV hàng hóa'),
    ('VI.3.fg', 'thiếu tách GV thành phẩm'),
    ('VI.3.svc', 'thiếu tách GV dịch vụ'),
    ('VI.3.other', 'thiếu tách GV khác'),
    ('VI.3.extra', 'thiếu nhận diện CP khác vào GV'),
    ('VI.3.reduce', 'thiếu nhận diện ghi giảm GV'),
]:
    LINE_META[code] = _m('machine_gap', 'trich_tt133', '15583 trang 16', gap)
LINE_META['VI.3.total'] = _m('machine_now', 'trich_tt133', 'Bản B02 đã lập — mã 11')

LINE_META['VI.4'] = _m('section', 'trich_tt133', '15583 trang 16')
for code, gap in [
    ('VI.4.deposit', 'thiếu nhãn lãi TG/cho vay trên 515'),
    ('VI.4.sale', 'thiếu nhãn lãi bán đầu tư trên 515'),
    ('VI.4.div', 'thiếu nhãn cổ tức trên 515'),
    ('VI.4.fx', 'thiếu nhãn lãi FX trên 515'),
    ('VI.4.term', 'thiếu nhãn lãi trả chậm/CKTT trên 515'),
    ('VI.4.other', 'thiếu nhãn DT TC khác trên 515'),
]:
    LINE_META[code] = _m('machine_gap', 'trich_tt133', '15583 trang 16', gap)
LINE_META['VI.4.total'] = _m('machine_now', 'trich_tt133', 'Bản B02 đã lập — mã 21')

LINE_META['VI.5'] = _m('section', 'trich_tt133', '15583 trang 16–17')
LINE_META['VI.5.loan'] = _m('machine_now', 'trich_tt133_chot_connecta', 'Bản B02 đã lập — mã 23')
for code, gap in [
    ('VI.5.discount', 'thiếu nhãn CKTT / lãi mua trả chậm trên 635'),
    ('VI.5.sale_loss', 'thiếu nhãn lỗ bán đầu tư trên 635'),
    ('VI.5.fx', 'thiếu nhãn lỗ FX trên 635'),
    ('VI.5.provision', 'thiếu nhãn DP đầu tư trên 635'),
    ('VI.5.other', 'thiếu nhãn CP TC khác trên 635'),
    ('VI.5.reduce', 'thiếu nhãn ghi giảm CP TC trên 635'),
]:
    LINE_META[code] = _m('machine_gap', 'trich_tt133', '15583 trang 16–17', gap)
LINE_META['VI.5.total'] = _m('machine_now', 'trich_tt133', 'Bản B02 đã lập — mã 22')

LINE_META['VI.6'] = _m('section', 'trich_tt133', '15583 trang 17')
LINE_META['VI.6.admin'] = _m(
    'machine_now', 'chot_connecta',
    'PS Có 6422↔911 (cùng công thức B02 mã 24)',
)
LINE_META['VI.6.selling'] = _m(
    'machine_now', 'chot_connecta',
    'PS Có 6421↔911 (cùng công thức B02 mã 24)',
)
LINE_META['VI.6.reduce'] = _m(
    'machine_gap', 'trich_tt133', '15583 trang 17',
    'thiếu nhận diện hoàn nhập DP / ghi giảm CP QLDN',
)
LINE_META['VI.6.total'] = _m('machine_now', 'trich_tt133', 'Bản B02 đã lập — mã 24')

LINE_META['VI.7'] = _m('section', 'trich_tt133', '15583 trang 17')
for code, gap in [
    ('VI.7.disposal', 'thiếu sự kiện TL/NB TSCĐ (C4) tách lãi'),
    ('VI.7.reval', 'thiếu nhận diện lãi đánh giá lại trên 711'),
    ('VI.7.penalty', 'thiếu nhận diện tiền phạt thu trên 711'),
    ('VI.7.tax', 'thiếu nhận diện thuế được giảm/hoàn trên 711'),
    ('VI.7.other', 'thiếu tách TN khác trên 711'),
]:
    LINE_META[code] = _m('machine_gap', 'trich_tt133', '15583 trang 17', gap)
LINE_META['VI.7.total'] = _m('machine_now', 'trich_tt133', 'Bản B02 đã lập — mã 31')

LINE_META['VI.8'] = _m('section', 'trich_tt133', '15583 trang 17')
for code, gap in [
    ('VI.8.disposal', 'thiếu sự kiện TL/NB TSCĐ (C4) tách lỗ'),
    ('VI.8.reval', 'thiếu nhận diện lỗ đánh giá lại trên 811'),
    ('VI.8.penalty', 'thiếu nhận diện khoản bị phạt trên 811'),
    ('VI.8.other', 'thiếu tách CP khác trên 811'),
]:
    LINE_META[code] = _m('machine_gap', 'trich_tt133', '15583 trang 17', gap)
LINE_META['VI.8.total'] = _m('machine_now', 'trich_tt133', 'Bản B02 đã lập — mã 32')

LINE_META['VI.9'] = _m('section', 'trich_tt133', '15583 trang 17')
LINE_META['VI.9.current'] = _m(
    'machine_gap', 'trich_tt133', '15583 trang 17',
    'thiếu tách CP thuế trên TNCT năm nay vs điều chỉnh',
)
LINE_META['VI.9.prior'] = _m(
    'machine_gap', 'trich_tt133', '15583 trang 17',
    'thiếu tách điều chỉnh thuế TNDN năm trước',
)
LINE_META['VI.9.total'] = _m('machine_now', 'trich_tt133', 'Bản B02 đã lập — mã 51')

# ---- VII / VIII ----
LINE_META['VII'] = _m('section', 'trich_tt133', '15583 trang 17; 15581 §2.5.7')
LINE_META['VII.1'] = _m(
    'manual', 'chot_connecta',
    'Thuyết minh tiền/TĐT nắm giữ nhưng không được sử dụng — nhập tay (giá trị + lý do)',
)
LINE_META['VIII'] = _m('section', 'trich_tt133', '15583 trang 18; 15581 §2.5.8')
for i in range(1, 6):
    LINE_META['VIII.%s' % i] = _m('manual', 'trich_tt133', 'Thông tin khác — nhập tay')

# Trạng thái bảng (mã mục)
TABLE_STATUS = {
    'V.1': ('total_ok_detail_open', 'Tổng B01a 110; tiền mặt/TGNH từ sổ; TĐT thiếu cờ C1'),
    'V.2a': ('total_ok_detail_open', 'Tổng B01a 121; chi tiết thiếu phân loại CK trên sổ'),
    'V.2b': ('total_ok_detail_open', 'Tổng B01a 122; chi tiết 1281/1288 từ sổ'),
    'V.2c': ('full', 'Tổng B01a 124; chi tiết 2291/2292 từ sổ'),
    'V.3a': ('total_ok_detail_open', 'Tổng B01a 131; «trong đó bên liên quan» thiếu cờ'),
    'V.3b': ('total_ok_detail_open', 'Tổng B01a 132; «trong đó bên liên quan» thiếu cờ'),
    'V.3c': ('total_ok_detail_open', 'Tổng B01a 134; tạm ứng/nội bộ/khác từ sổ; cho vay còn mở'),
    'V.3d': ('total_ok_detail_open', 'Tổng B01a 135; chi tiết thiếu phân loại trên dòng'),
    'V.3đ': ('none_yet', 'Thiếu model nợ xấu / tuổi nợ'),
    'V.4': ('total_ok_detail_open', 'Tổng B01a 141; 151–157 từ sổ; ứ đọng/thế chấp thiếu cờ'),
    'V.5': (
        'full',
        'Bảng tăng/giảm từ sổ 211x/214x; giảm có số thì cảnh báo chưa phân tích nguyên nhân TL',
    ),
    'V.6': (
        'total_ok_detail_open',
        'Bảng 217/2147 từ sổ; tách cho thuê/chờ tăng giá còn mở',
    ),
    'V.7': ('total_ok_detail_open', 'Tổng B01a 170; chi tiết 2411/2412/2413 từ sổ'),
    'V.8': (
        'total_ok_detail_open',
        'Phải thu NSNN 333 từ sổ; thiếu tách ngắn/dài 242',
    ),
    'V.9a': ('total_ok_detail_open', 'Tổng B01a 311; bên liên quan thiếu cờ'),
    'V.9b': ('total_ok_detail_open', 'Tổng B01a 312; bên liên quan thiếu cờ'),
    'V.9c': ('total_ok_detail_open', 'Tổng B01a 315; 335/336x/3388 từ sổ'),
    'V.9d': ('none_yet', 'Thiếu tuổi nợ phải trả'),
    'V.10': ('none_yet', 'Thiếu nhận diện số đã thực nộp thuế'),
    'V.11': (
        'total_ok_detail_open',
        'Tổng B01a 316; thuê TC 3412 từ sổ; NH/DH còn mở',
    ),
    'V.12': (
        'total_ok_detail_open',
        'Tổng B01a 318; chi tiết 3521/3522/3524 từ sổ',
    ),
    'V.13': ('none_yet', 'Bảng biến động VCSH chưa đủ; thuyết minh khác nhập tay'),
    'V.14': ('none_yet', 'Thiếu sổ ngoài bảng VAS'),
    'V.15': ('none_yet', 'Thiếu master bên liên quan'),
    'V.16': ('manual_all', 'Nhập tay'),
    'VI.1a': (
        'total_ok_detail_open',
        'Tổng B02 01; chi tiết 5111–5118 từ sổ (ghi cha 511 không vào lá)',
    ),
    'VI.1b': ('none_yet', 'Thiếu cờ bên liên quan'),
    'VI.1c': ('none_yet', 'Thiếu lịch DT nhận trước'),
    'VI.2': ('total_ok_detail_open', 'Tổng B02 02; thiếu tách 3 loại giảm trừ'),
    'VI.3': ('total_ok_detail_open', 'Tổng B02 11; thiếu tách loại GV'),
    'VI.4': ('total_ok_detail_open', 'Tổng B02 21; thiếu nhãn chi tiết 515'),
    'VI.5': ('total_ok_detail_open', 'Tổng B02 22 + lãi vay 23; chi tiết 635 còn lại thiếu nhãn'),
    'VI.6': ('total_ok_detail_open', 'Tổng B02 24; 6421/6422 từ sổ; ghi giảm thiếu nhận diện'),
    'VI.7': ('total_ok_detail_open', 'Tổng B02 31; chi tiết thiếu TL-NB / nhãn 711'),
    'VI.8': ('total_ok_detail_open', 'Tổng B02 32; chi tiết thiếu TL-NB / nhãn 811'),
    'VI.9': ('total_ok_detail_open', 'Tổng B02 51; thiếu tách năm nay vs điều chỉnh'),
    'I': ('manual_all', 'Nhập tay đặc điểm HĐDN'),
    'II': ('full', 'Kỳ KT / ĐVTT lấy từ FY và currency công ty'),
    'III': ('manual_all', 'Tuyên bố CMKT — nhập tay'),
    'IV': ('manual_all', 'Chính sách KT — nhập tay'),
    'VII': (
        'manual_all',
        'Thuyết minh tiền hạn chế sử dụng — nhập tay (không bảng số B03)',
    ),
    'VIII': ('manual_all', 'Thông tin khác — nhập tay'),
}

# Lưới tự kiểm: tổng (B01a/B02) ↔ tổng các dòng chi tiết cộng được.
# Bỏ «trong đó» (.related) và thuyết minh ngoài tổng (stagnant/pledged).
# source_label = nhãn chỉ tiêu nguồn trên B01a/B02.
B09_DETAIL_SUM_CHECKS = {
    'V.1.total': {
        'details': ('V.1.cash', 'V.1.bank', 'V.1.equiv'),
        'source_label': 'B01a mã 110',
        'check_opening': True,
    },
    'V.2a.total': {
        'details': ('V.2a.stock', 'V.2a.bond', 'V.2a.other'),
        'source_label': 'B01a mã 121',
        'check_opening': True,
    },
    'V.2b.total': {
        'details': ('V.2b.deposit', 'V.2b.other'),
        'source_label': 'B01a mã 122',
        'check_opening': True,
    },
    'V.2c.total': {
        'details': ('V.2c.sec', 'V.2c.other'),
        'source_label': 'B01a mã 124',
        'check_opening': True,
    },
    'V.3c.total': {
        'details': (
            'V.3c.loan', 'V.3c.advance', 'V.3c.internal', 'V.3c.other',
        ),
        'source_label': 'B01a mã 134',
        'check_opening': True,
    },
    'V.3d.total': {
        'details': ('V.3d.cash', 'V.3d.inv', 'V.3d.fa', 'V.3d.other'),
        'source_label': 'B01a mã 135',
        'check_opening': True,
    },
    'V.4.total': {
        'details': (
            'V.4.transit', 'V.4.material', 'V.4.tool', 'V.4.wip',
            'V.4.fg', 'V.4.merch', 'V.4.consign',
        ),
        'source_label': 'B01a mã 141',
        'check_opening': True,
    },
    'V.7.total': {
        'details': ('V.7.buy', 'V.7.cip', 'V.7.repair'),
        'source_label': 'B01a mã 170',
        'check_opening': True,
    },
    'V.9c.total': {
        'details': ('V.9c.accrued', 'V.9c.internal', 'V.9c.other'),
        'source_label': 'B01a mã 315',
        'check_opening': True,
    },
    'V.11.total': {
        'details': ('V.11.st', 'V.11.lt', 'V.11.lease'),
        'source_label': 'B01a mã 316',
        'check_opening': True,
    },
    'V.12.total': {
        'details': ('V.12.warranty', 'V.12.construction', 'V.12.other'),
        'source_label': 'B01a mã 318',
        'check_opening': True,
    },
    'VI.1a.total': {
        'details': (
            'VI.1a.goods', 'VI.1a.fg', 'VI.1a.svc', 'VI.1a.other',
        ),
        'source_label': 'B02 mã 01',
        'check_opening': False,
    },
    'VI.2.total': {
        'details': ('VI.2.discount', 'VI.2.markdown', 'VI.2.return'),
        'source_label': 'B02 mã 02',
        'check_opening': False,
    },
    'VI.3.total': {
        'details': (
            'VI.3.goods', 'VI.3.fg', 'VI.3.svc', 'VI.3.other',
            'VI.3.extra', 'VI.3.reduce',
        ),
        'source_label': 'B02 mã 11',
        'check_opening': False,
    },
    'VI.4.total': {
        'details': (
            'VI.4.deposit', 'VI.4.sale', 'VI.4.div', 'VI.4.fx',
            'VI.4.term', 'VI.4.other',
        ),
        'source_label': 'B02 mã 21',
        'check_opening': False,
    },
    'VI.5.total': {
        'details': (
            'VI.5.loan', 'VI.5.discount', 'VI.5.sale_loss', 'VI.5.fx',
            'VI.5.provision', 'VI.5.other', 'VI.5.reduce',
        ),
        'source_label': 'B02 mã 22',
        'check_opening': False,
    },
    'VI.6.total': {
        'details': ('VI.6.selling', 'VI.6.admin', 'VI.6.reduce'),
        'source_label': 'B02 mã 24',
        'check_opening': False,
    },
    'VI.7.total': {
        'details': (
            'VI.7.disposal', 'VI.7.reval', 'VI.7.penalty',
            'VI.7.tax', 'VI.7.other',
        ),
        'source_label': 'B02 mã 31',
        'check_opening': False,
    },
    'VI.8.total': {
        'details': (
            'VI.8.disposal', 'VI.8.reval', 'VI.8.penalty', 'VI.8.other',
        ),
        'source_label': 'B02 mã 32',
        'check_opening': False,
    },
    'VI.9.total': {
        'details': ('VI.9.current', 'VI.9.prior'),
        'source_label': 'B02 mã 51',
        'check_opening': False,
    },
}

# Rename map (mã cũ → mới) cho migration
CODE_RENAMES = {
    'V.3e': 'V.3đ',
    'V.3e.total': 'V.3đ.total',
    'V.14e': 'V.14đ',
}
XMLID_RENAMES = {
    'vas_report_line_b09_V_3e': 'vas_report_line_b09_V_3đ',
    'vas_report_line_b09_V_3e_total': 'vas_report_line_b09_V_3đ_total',
    'vas_report_line_b09_V_14e': 'vas_report_line_b09_V_14đ',
}
