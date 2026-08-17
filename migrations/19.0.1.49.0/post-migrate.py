# -*- coding: utf-8 -*-
"""W10: thứ tự KC theo sequence + meta MANUAL/C01; cửa đề xuất dùng chung."""


def migrate(cr, version):
    # Tạo meta rule nếu chưa có (noupdate XML không thêm trên DB cũ)
    cr.execute(
        """
        INSERT INTO vas_closing_rule (
            code, name, regime_id, rule_layer, group_code, timing,
            sequence, active, is_system, create_uid, write_uid,
            create_date, write_date
        )
        SELECT
            v.code, v.name, r.id, v.rule_layer, v.group_code, v.timing,
            v.sequence, TRUE, TRUE, 1, 1, NOW(), NOW()
        FROM (VALUES
            ('MANUAL', 'Trích/dự phòng nhập tay (C02–C07/C10)',
             'B_accrual', 'provision', 'period_end', 10),
            ('C01', 'Phân bổ chi phí trả trước 242',
             'B_accrual', 'prepaid', 'period_end', 20)
        ) AS v(code, name, rule_layer, group_code, timing, sequence)
        JOIN vas_regime r ON r.code = 'TT133'
        WHERE NOT EXISTS (
            SELECT 1 FROM vas_closing_rule x
             WHERE x.regime_id = r.id AND x.code = v.code
        )
        """
    )
    # ir.model.data cho seed bảo vệ
    for xmlid, code in (
        ('vas_closing_rule_tt133_MANUAL', 'MANUAL'),
        ('vas_closing_rule_tt133_C01', 'C01'),
    ):
        cr.execute(
            """
            INSERT INTO ir_model_data (
                name, module, model, res_id, noupdate
            )
            SELECT %s, 'connecta_vas', 'vas.closing.rule', r.id, TRUE
              FROM vas_closing_rule r
              JOIN vas_regime g ON g.id = r.regime_id AND g.code = 'TT133'
             WHERE r.code = %s
               AND NOT EXISTS (
                   SELECT 1 FROM ir_model_data d
                    WHERE d.module = 'connecta_vas' AND d.name = %s
               )
            """,
            [xmlid, code, xmlid],
        )

    seq_map = {
        'MANUAL': 10, 'C01': 20, 'L06': 30, 'V09': 40,
        '413-515': 50, '413-635': 55, 'CIT': 60,
        '511-911': 100, '5111-911': 101, '5112-911': 102,
        '5113-911': 103, '5118-911': 104,
        '515-911': 110, '711-911': 120, '632-911': 130, '635-911': 140,
        '6421-911': 150, '6422-911': 160, '811-911': 170,
        '821-911-debit': 180, '821-911-credit': 185,
        '911-4212-credit': 190, '911-4212-debit': 195,
        '4212-4211-credit': 200, '4212-4211-debit': 205,
        'KKDK-24': 280,
    }
    for code, seq in seq_map.items():
        cr.execute(
            """
            UPDATE vas_closing_rule r
               SET sequence = %s
              FROM vas_regime g
             WHERE r.regime_id = g.id
               AND g.code = 'TT133'
               AND r.code = %s
            """,
            [seq, code],
        )
