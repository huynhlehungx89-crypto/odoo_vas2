# -*- coding: utf-8 -*-
"""B09: nối 28 dòng (A) + bảng tăng/giảm V.5/V.6; B02 ghi phương án tạm 31/32."""


LEDGER_BALANCE = {
    'V.2b.deposit': ('1281', 'debit'),
    'V.2b.other': ('1288', 'debit'),
    'V.3c.advance': ('141', 'debit'),
    'V.3c.internal': ('1361,1368', 'debit'),
    'V.3c.other': ('1388', 'debit'),
    'V.7.buy': ('2411', 'debit'),
    'V.7.cip': ('2412', 'debit'),
    'V.7.repair': ('2413', 'debit'),
    'V.8.tax_recv': ('333', 'debit'),
    'V.9c.internal': ('3361,3368', 'credit'),
    'V.9c.other': ('3388', 'credit'),
    'V.11.lease': ('3412', 'credit'),
    'V.12.warranty': ('3521', 'credit'),
    'V.12.construction': ('3522', 'credit'),
    'V.12.other': ('3524', 'credit'),
}

MOVEMENT = {
    'V.5.tangible.cost': ('2111', 'cost'),
    'V.5.tangible.accum': ('2141', 'accum'),
    'V.5.intangible.cost': ('2113', 'cost'),
    'V.5.intangible.accum': ('2143', 'accum'),
    'V.5.lease.cost': ('2112', 'cost'),
    'V.5.lease.accum': ('2142', 'accum'),
    'V.6.cost': ('217', 'cost'),
    'V.6.accum': ('2147', 'accum'),
}

NET = {
    'V.5.tangible.net': 'b09_from_net:V.5.tangible.cost,V.5.tangible.accum',
    'V.5.intangible.net': 'b09_from_net:V.5.intangible.cost,V.5.intangible.accum',
    'V.5.lease.net': 'b09_from_net:V.5.lease.cost,V.5.lease.accum',
    'V.6.net': 'b09_from_net:V.6.cost,V.6.accum',
}

GROSS = {
    'VI.1a.goods': '5111',
    'VI.1a.fg': '5112',
    'VI.1a.svc': '5113',
    'VI.1a.other': '5118',
}


def migrate(cr, version):
    from odoo.addons.connecta_vas.models.vas_b09_meta import LINE_META, TABLE_STATUS

    for code, (acc, side) in LEDGER_BALANCE.items():
        cr.execute(
            """
            UPDATE vas_report_line
               SET code_custom_key = 'b09_from_ledger',
                   account_codes = %s,
                   balance_side = %s,
                   turnover_mode = NULL,
                   source_side = NULL,
                   counterpart_account_codes = NULL,
                   counterpart_side = NULL,
                   warn_message = NULL,
                   b09_gap_reason = NULL
             WHERE form_code = 'B09-DNN' AND code = %s
            """,
            [acc, side, code],
        )

    for code, (acc, kind) in MOVEMENT.items():
        side = 'debit' if kind == 'cost' else 'credit'
        cr.execute(
            """
            UPDATE vas_report_line
               SET code_custom_key = %s,
                   account_codes = %s,
                   balance_side = %s,
                   turnover_mode = NULL,
                   source_side = NULL,
                   counterpart_account_codes = NULL,
                   counterpart_side = NULL,
                   warn_message = NULL,
                   b09_gap_reason = NULL
             WHERE form_code = 'B09-DNN' AND code = %s
            """,
            ['b09_from_movement:%s' % kind, acc, side, code],
        )

    for code, key in NET.items():
        cr.execute(
            """
            UPDATE vas_report_line
               SET code_custom_key = %s,
                   account_codes = NULL,
                   balance_side = NULL,
                   turnover_mode = NULL,
                   source_side = NULL,
                   counterpart_account_codes = NULL,
                   counterpart_side = NULL,
                   warn_message = NULL,
                   b09_gap_reason = NULL
             WHERE form_code = 'B09-DNN' AND code = %s
            """,
            [key, code],
        )

    for code, acc in GROSS.items():
        cr.execute(
            """
            UPDATE vas_report_line
               SET code_custom_key = 'b09_from_ledger',
                   account_codes = %s,
                   balance_side = NULL,
                   turnover_mode = 'gross',
                   source_side = 'credit',
                   counterpart_account_codes = NULL,
                   counterpart_side = NULL,
                   warn_message = NULL,
                   b09_gap_reason = NULL
             WHERE form_code = 'B09-DNN' AND code = %s
            """,
            [acc, code],
        )

    cr.execute(
        """
        UPDATE vas_report_line
           SET code_custom_key = 'b09_unavailable',
               warn_message = NULL
         WHERE form_code = 'B09-DNN' AND code = 'VII.1'
        """
    )

    for code, info in LINE_META.items():
        cr.execute(
            """
            UPDATE vas_report_line
               SET b09_fill_kind = %s,
                   b09_gap_reason = %s,
                   basis_kind = %s,
                   basis_note = %s
             WHERE form_code = 'B09-DNN' AND code = %s
            """,
            [
                info['fill_kind'],
                info.get('gap_reason') or None,
                info['basis_kind'],
                info.get('basis_note') or None,
                code,
            ],
        )

    for code, (status, note) in TABLE_STATUS.items():
        cr.execute(
            """
            UPDATE vas_report_line
               SET b09_table_status = %s,
                   b09_table_status_note = %s,
                   warn_message = NULL
             WHERE form_code = 'B09-DNN' AND code = %s
            """,
            [status, note, code],
        )

    # V.6.cost/accum/net — tạo nếu DB sống chưa có (noupdate XML)
    cr.execute(
        """
        SELECT id FROM vas_regime WHERE code = 'tt133' LIMIT 1
        """
    )
    row = cr.fetchone()
    if row:
        regime_id = row[0]
        for code, name, seq, key, acc, side, note in [
            (
                'V.6.cost', 'Nguyên giá', 915,
                'b09_from_movement:cost', '217', 'debit',
                'SD/PS TK 217 — bảng tăng giảm BĐSĐT',
            ),
            (
                'V.6.accum', 'Giá trị hao mòn lũy kế', 917,
                'b09_from_movement:accum', '2147', 'credit',
                'SD/PS TK 2147 — hao mòn BĐSĐT',
            ),
            (
                'V.6.net', 'Giá trị còn lại', 919,
                'b09_from_net:V.6.cost,V.6.accum', None, None,
                'Nguyên giá − hao mòn lũy kế (BĐSĐT)',
            ),
        ]:
            cr.execute(
                """
                SELECT id FROM vas_report_line
                 WHERE form_code = 'B09-DNN' AND code = %s AND regime_id = %s
                """,
                [code, regime_id],
            )
            if cr.fetchone():
                continue
            cr.execute(
                """
                INSERT INTO vas_report_line (
                    sequence, code, name, form_code, regime_id, line_role,
                    amount_source, code_custom_key, account_codes, balance_side,
                    sign_negative, show_negative_paren, basis_kind, basis_note,
                    warn_kind, b09_fill_kind, is_system, active,
                    create_uid, write_uid, create_date, write_date
                ) VALUES (
                    %s, %s, %s, 'B09-DNN', %s, 'detail',
                    'code_custom', %s, %s, %s,
                    FALSE, FALSE, 'trich_tt133', %s,
                    'none', 'machine_now', TRUE, TRUE,
                    1, 1, NOW() AT NOW() AT
                )
                """,
                [seq, code, name, regime_id, key, acc, side, note],
            )

    cr.execute(
        """
        UPDATE vas_report_line
           SET basis_kind = 'trich_tt133_chot_connecta',
               basis_note = 'PHƯƠNG ÁN TẠM: PS Nợ 711↔911 trọn (chưa tách TL/NB — chưa có chức năng thanh lý)'
         WHERE form_code = 'B02-DNN' AND code = '31'
        """
    )
    cr.execute(
        """
        UPDATE vas_report_line
           SET basis_kind = 'trich_tt133_chot_connecta',
               basis_note = 'PHƯƠNG ÁN TẠM: PS Có 811↔911 trọn (chưa tách TL/NB — chưa có chức năng thanh lý)'
         WHERE form_code = 'B02-DNN' AND code = '32'
        """
    )
