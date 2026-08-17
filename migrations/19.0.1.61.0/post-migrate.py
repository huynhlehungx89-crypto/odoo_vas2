# -*- coding: utf-8 -*-
"""W7 pivot: gỡ nhãn misc JE Odoo (V02/V06) — cảnh báo dữ liệu cũ, không auto-convert."""
import logging

_logger = logging.getLogger(__name__)

_LEGACY_OPS = ('loan_disburse_vendor', 'capital_in_kind')
_GUIDE = (
    'Nhập lại bằng chứng từ VAS: giải ngân trên thẻ vay (vas.loan.disbursement) '
    'hoặc góp vốn hiện vật (vas.capital.in.kind). Không tự chuyển đổi.'
)


def warn_legacy_w7_misc_labels(cr):
    """Ghi WARNING nếu còn bút toán tổng hợp mang nhãn V02/V06 cũ.

    Trả về list (id, name, op) đã cảnh báo — dùng cho test.
    """
    cr.execute("""
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'account_move'
           AND column_name = 'vas_operation_type'
    """)
    if not cr.fetchone():
        return []

    cr.execute("""
        SELECT id, name, vas_operation_type
          FROM account_move
         WHERE vas_operation_type IN %s
         ORDER BY id
    """, (_LEGACY_OPS,))
    rows = cr.fetchall()
    warned = []
    for move_id, name, op in rows:
        warned.append((move_id, name, op))
        _logger.warning(
            'VAS W7 legacy misc JE còn nhãn cũ: id=%s name=%s op=%s. %s',
            move_id, name, op, _GUIDE,
        )
    if warned:
        names = ', '.join('%s(%s)' % (n or '?', i) for i, n, _op in warned)
        _logger.warning(
            'VAS W7: %s bút toán tổng hợp mang nhãn loan_disburse_vendor/'
            'capital_in_kind — liệt kê: %s. %s',
            len(warned), names, _GUIDE,
        )
    return warned


def _drop_legacy_columns(cr):
    for col in (
        'vas_operation_type',
        'vas_loan_id',
        'vas_spawn_fixed_asset',
    ):
        cr.execute("""
            SELECT 1 FROM information_schema.columns
             WHERE table_name = 'account_move'
               AND column_name = %s
        """, (col,))
        if cr.fetchone():
            cr.execute(
                'ALTER TABLE account_move DROP COLUMN IF EXISTS %s' % col
            )


def migrate(cr, version):
    warn_legacy_w7_misc_labels(cr)
    _drop_legacy_columns(cr)
