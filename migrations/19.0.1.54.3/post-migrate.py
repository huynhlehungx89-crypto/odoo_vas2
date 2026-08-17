# -*- coding: utf-8 -*-
"""12811 mẫu dưới 1281 + B01a 122 đọc mã con (C1)."""


def migrate(cr, version):
    cr.execute(
        """
        INSERT INTO vas_account (
            code, name, regime_id, ending_balance_policy, account_type,
            parent_id, reconcile, active,
            create_uid, create_date, write_uid, write_date
        )
        SELECT
            '12811',
            'Tiền gửi có kỳ hạn (mẫu)',
            r.id,
            'debit',
            'asset',
            p.id,
            FALSE,
            TRUE,
            1, NOW(), 1, NOW()
        FROM vas_regime r
        JOIN vas_account p
          ON p.regime_id = r.id AND p.code = '1281'
        WHERE r.code = 'TT133'
          AND NOT EXISTS (
              SELECT 1 FROM vas_account a
               WHERE a.regime_id = r.id AND a.code = '12811'
          )
        RETURNING id
        """
    )
    row = cr.fetchone()
    if row:
        acc_id = row[0]
    else:
        cr.execute(
            """
            SELECT a.id
              FROM vas_account a
              JOIN vas_regime r ON r.id = a.regime_id
             WHERE r.code = 'TT133' AND a.code = '12811'
             LIMIT 1
            """
        )
        found = cr.fetchone()
        acc_id = found[0] if found else None
    if acc_id:
        cr.execute(
            """
            INSERT INTO ir_model_data (
                module, name, model, res_id, noupdate,
                create_uid, create_date, write_uid, write_date
            )
            SELECT
                'connecta_vas', 'vas_account_tt133_12811', 'vas.account',
                %s, TRUE,
                1, NOW(), 1, NOW()
            WHERE NOT EXISTS (
                SELECT 1 FROM ir_model_data
                 WHERE module = 'connecta_vas'
                   AND name = 'vas_account_tt133_12811'
            )
            """,
            (acc_id,),
        )
    cr.execute(
        """
        UPDATE vas_report_line
           SET account_codes = CASE
                 WHEN account_codes IS NULL OR BTRIM(account_codes) = ''
                   THEN '12811'
                 WHEN account_codes ~ '(^|,)12811(,|$)'
                   THEN account_codes
                 ELSE account_codes || ',12811'
               END
         WHERE form_code = 'B01a-DNN' AND code = '122'
        """
    )
