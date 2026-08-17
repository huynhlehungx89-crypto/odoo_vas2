# -*- coding: utf-8 -*-
"""Gắn closing_entry_id từ move_id / fx_move_id cũ; cảnh báo chứng từ gộp hai vế."""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

_WARN_GUIDE = (
    'Phải đảo phiếu kết chuyển chứa chứng từ trên rồi ghi sổ lại '
    'để máy sinh theo lô mới (mỗi cặp Nợ–Có một chứng từ). '
    'Migration không tự tách chứng từ gộp.'
)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    cr.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'vas_closing_entry'
          AND column_name IN ('move_id', 'fx_move_id')
    """)
    legacy = {row[0] for row in cr.fetchall()}

    cr.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'vas_move' AND column_name = 'closing_entry_id'
    """)
    has_link = bool(cr.fetchone())
    if not has_link:
        _logger.warning('vas.move.closing_entry_id missing — skip link backfill + scan')
        return

    if legacy:
        if 'move_id' in legacy:
            cr.execute("""
                UPDATE vas_move AS m
                   SET closing_entry_id = e.id
                  FROM vas_closing_entry AS e
                 WHERE e.move_id = m.id
                   AND (m.closing_entry_id IS NULL OR m.closing_entry_id = e.id)
            """)
            _logger.info('Linked closing moves from move_id: %s', cr.rowcount)
        if 'fx_move_id' in legacy:
            cr.execute("""
                UPDATE vas_move AS m
                   SET closing_entry_id = e.id
                  FROM vas_closing_entry AS e
                 WHERE e.fx_move_id = m.id
                   AND (m.closing_entry_id IS NULL OR m.closing_entry_id = e.id)
            """)
            _logger.info('Linked forex_reval moves from fx_move_id: %s', cr.rowcount)
        for col in ('move_id', 'fx_move_id'):
            if col in legacy:
                cr.execute(
                    'ALTER TABLE vas_closing_entry DROP COLUMN IF EXISTS %s' % col
                )
                _logger.info('Dropped vas_closing_entry.%s', col)
    else:
        _logger.info('vas.closing.entry: no legacy move_id/fx_move_id — link skip')

    # Sau gắn link (hoặc đã gắn từ lần trước): kêu to nếu còn chứng từ gộp hai vế.
    _warn_both_side_batch_moves(cr)


def _warn_both_side_batch_moves(cr):
    """Đếm vas.move thuộc lô có cùng TK ở cả hai vế — WARNING + hướng dẫn, không tách."""
    cr.execute("""
        SELECT m.id, m.name, m.move_kind, a.code,
               SUM(ml.debit) AS debit, SUM(ml.credit) AS credit,
               m.closing_entry_id, e.name AS entry_name
          FROM vas_move_line ml
          JOIN vas_move m ON m.id = ml.move_id
          JOIN vas_account a ON a.id = ml.account_id
          LEFT JOIN vas_closing_entry e ON e.id = m.closing_entry_id
         WHERE m.closing_entry_id IS NOT NULL
           AND COALESCE(m.is_reversal, FALSE) = FALSE
         GROUP BY m.id, m.name, m.move_kind, a.code, m.closing_entry_id, e.name
        HAVING SUM(ml.debit) > 0.0001 AND SUM(ml.credit) > 0.0001
         ORDER BY m.id, a.code
    """)
    rows = cr.fetchall()
    if not rows:
        _logger.info(
            'vas.closing.entry batch scan: 0 chứng từ lô có TK đứng cả hai vế — OK'
        )
        return

    # Gom theo move để liệt kê số hiệu
    by_move = {}
    for mid, name, kind, code, debit, credit, entry_id, entry_name in rows:
        by_move.setdefault(
            mid, {'name': name, 'kind': kind, 'entry': entry_name or entry_id, 'codes': []}
        )
        by_move[mid]['codes'].append('%s (N=%.2f/C=%.2f)' % (code, debit, credit))

    lines = []
    for mid, info in sorted(by_move.items()):
        lines.append(
            '  - %s (id=%s, kind=%s, phiếu=%s): TK hai vế %s' % (
                info['name'] or '/',
                mid,
                info['kind'],
                info['entry'],
                ', '.join(info['codes']),
            )
        )
    _logger.warning(
        'vas.closing.entry: phát hiện %s chứng từ thuộc lô kết chuyển còn cùng '
        'một tài khoản ở CẢ HAI vế Nợ/Có (chứng từ gộp kiểu cũ).\n%s\n%s',
        len(by_move),
        '\n'.join(lines),
        _WARN_GUIDE,
    )
