# -*- coding: utf-8 -*-
"""B03-4: B09 VII nhập tay; cột thuyết minh B01a/B02; (gợi ý IV.7 = code)."""

# Ánh xạ ngược B09 ← B01a/B02 (ổn định theo mã chỉ tiêu B09, không dùng sequence).
NOTE_B01A = {
    '110': 'V.1.total',
    '121': 'V.2a.total',
    '122': 'V.2b.total',
    '124': 'V.2c.total',
    '131': 'V.3a.total',
    '132': 'V.3b.total',
    '134': 'V.3c.total',
    '135': 'V.3d.total',
    '141': 'V.4.total',
    '170': 'V.7.total',
    '311': 'V.9a.total',
    '312': 'V.9b.total',
    '315': 'V.9c.total',
    '316': 'V.11.total',
    '318': 'V.12.total',
}
NOTE_B02 = {
    '01': 'VI.1a.total',
    '02': 'VI.2.total',
    '11': 'VI.3.total',
    '21': 'VI.4.total',
    '22': 'VI.5.total',
    '23': 'VI.5.loan',
    '24': 'VI.6.total',
    '31': 'VI.7.total',
    '32': 'VI.8.total',
    '51': 'VI.9.total',
}


def migrate(cr, version):
    # Mục VII — từ machine_gap / none_yet → nhập tay (làm được)
    cr.execute("""
        UPDATE vas_report_line
           SET b09_fill_kind = 'section',
               b09_table_status = 'manual_all',
               b09_table_status_note = %s,
               b09_gap_reason = NULL
         WHERE form_code = 'B09-DNN' AND code = 'VII'
    """, (
        'Thuyết minh tiền hạn chế sử dụng — nhập tay (không bảng số B03)',
    ))
    cr.execute("""
        UPDATE vas_report_line
           SET b09_fill_kind = 'manual',
               basis_note = %s,
               b09_gap_reason = NULL,
               code_custom_key = 'b09_unavailable'
         WHERE form_code = 'B09-DNN' AND code = 'VII.1'
    """, (
        'Thuyết minh tiền/TĐT nắm giữ nhưng không được sử dụng — '
        'nhập tay (giá trị + lý do)',
    ))

    # Cột thuyết minh B01a / B02
    for code, note in NOTE_B01A.items():
        cr.execute("""
            UPDATE vas_report_line
               SET note_b09_code = %s
             WHERE form_code = 'B01a-DNN' AND code = %s
        """, (note, code))
    for code, note in NOTE_B02.items():
        cr.execute("""
            UPDATE vas_report_line
               SET note_b09_code = %s
             WHERE form_code = 'B02-DNN' AND code = %s
        """, (note, code))
