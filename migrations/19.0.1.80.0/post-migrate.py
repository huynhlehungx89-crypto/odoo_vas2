# -*- coding: utf-8 -*-
"""L80: ops asset/vay/thuế — hành động lọc + bỏ Nộp thuế GTGT chung."""


def migrate(cr, version):
    # --- Tài sản: khấu hao → list move_kind=depreciation ---
    cr.execute(
        """
        UPDATE vas_ops_button b
           SET action_xmlid = 'connecta_vas.action_vas_move_depreciation'
          FROM ir_model_data d
         WHERE d.res_id = b.id
           AND d.module = 'connecta_vas'
           AND d.name = 'vas_ops_btn_asset_depreciate'
           AND d.model = 'vas.ops.button'
        """
    )

    # --- Thuế: gỡ nút Nộp thuế GTGT + next từ L06 ---
    cr.execute(
        """
        SELECT b.id
          FROM vas_ops_button b
          JOIN ir_model_data d ON d.res_id = b.id
         WHERE d.module = 'connecta_vas'
           AND d.model = 'vas.ops.button'
           AND d.name = 'vas_ops_btn_tax_pay'
        """
    )
    row = cr.fetchone()
    if row:
        tax_pay_id = row[0]
        cr.execute(
            "DELETE FROM vas_ops_button_next_rel WHERE button_id = %s OR next_id = %s",
            (tax_pay_id, tax_pay_id),
        )
        cr.execute("DELETE FROM vas_ops_button WHERE id = %s", (tax_pay_id,))
        cr.execute(
            """
            DELETE FROM ir_model_data
             WHERE module = 'connecta_vas'
               AND name = 'vas_ops_btn_tax_pay'
               AND model = 'vas.ops.button'
            """
        )

    # --- Vay: gỡ «Lịch trả lãi» khỏi chuỗi; nối lại 5 bước mới ---
    def _btn_id(xml_name):
        cr.execute(
            """
            SELECT res_id FROM ir_model_data
             WHERE module = 'connecta_vas'
               AND model = 'vas.ops.button'
               AND name = %s
            """,
            (xml_name,),
        )
        r = cr.fetchone()
        return r[0] if r else None

    schedule_id = _btn_id('vas_ops_btn_loan_schedule')
    if schedule_id:
        cr.execute(
            "DELETE FROM vas_ops_button_next_rel WHERE button_id = %s OR next_id = %s",
            (schedule_id, schedule_id),
        )
        cr.execute("DELETE FROM vas_ops_button WHERE id = %s", (schedule_id,))
        cr.execute(
            """
            DELETE FROM ir_model_data
             WHERE module = 'connecta_vas'
               AND name = 'vas_ops_btn_loan_schedule'
               AND model = 'vas.ops.button'
            """
        )

    # Cập nhật action/sequence cho nút còn lại (nút Trả lãi tạo mới bởi XML)
    updates = [
        ('vas_ops_btn_loan_accrue',
         'connecta_vas.action_vas_move_loan_interest', 20),
        ('vas_ops_btn_loan_repay',
         'connecta_vas.action_vas_payment_loan_repay', 40),
        ('vas_ops_btn_loan_settle',
         'connecta_vas.action_vas_loan', 50),
        ('vas_ops_btn_loan_contract',
         'connecta_vas.action_vas_loan', 10),
    ]
    for xml_name, action, seq in updates:
        cr.execute(
            """
            UPDATE vas_ops_button b
               SET action_xmlid = %s, sequence = %s
              FROM ir_model_data d
             WHERE d.res_id = b.id
               AND d.module = 'connecta_vas'
               AND d.name = %s
               AND d.model = 'vas.ops.button'
            """,
            (action, seq, xml_name),
        )

    # Xóa next cũ của các nút vay rồi gắn lại sau khi XML tạo nút Trả lãi
    for xml_name in (
        'vas_ops_btn_loan_contract',
        'vas_ops_btn_loan_accrue',
        'vas_ops_btn_loan_pay_interest',
        'vas_ops_btn_loan_repay',
        'vas_ops_btn_loan_settle',
    ):
        bid = _btn_id(xml_name)
        if bid:
            cr.execute(
                "DELETE FROM vas_ops_button_next_rel WHERE button_id = %s",
                (bid,),
            )

    chain = [
        ('vas_ops_btn_loan_contract', 'vas_ops_btn_loan_accrue'),
        ('vas_ops_btn_loan_accrue', 'vas_ops_btn_loan_pay_interest'),
        ('vas_ops_btn_loan_pay_interest', 'vas_ops_btn_loan_repay'),
        ('vas_ops_btn_loan_repay', 'vas_ops_btn_loan_settle'),
    ]
    for src, dst in chain:
        a, b = _btn_id(src), _btn_id(dst)
        if a and b:
            cr.execute(
                """
                SELECT 1 FROM vas_ops_button_next_rel
                 WHERE button_id = %s AND next_id = %s
                """,
                (a, b),
            )
            if not cr.fetchone():
                cr.execute(
                    """
                    INSERT INTO vas_ops_button_next_rel (button_id, next_id)
                    VALUES (%s, %s)
                    """,
                    (a, b),
                )
