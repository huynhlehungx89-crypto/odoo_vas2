# -*- coding: utf-8 -*-
"""Đảo JE R06 ghi sai trên phiếu trả NCC (dest=supplier) rồi chạy lại R09s.

Bug: domain R06 cũ bắt ``purchase_line_id`` cả return → JE ``move_kind=stock``
cùng chiều nhập → R09s bị ``_already_synced`` skip → 156/331 đôi.

Sau khi domain R06 đã loại ``location_dest_usage=supplier``, migration:
1. Tìm JE sống kind=stock gắn stock.move đích NCC → ``action_reverse``.
2. ``_sync_purchase_return_stocks`` theo company để sinh R09s đúng.

GIT (151) × phiếu trả: R09s vẫn Nợ 331/Có 156 — chưa tinh chỉnh Có 151;
gắn cờ theo dõi (không xử trong migration này).
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def _bad_r06_return_move_ids(cr):
    """vas.move id: R06-nhầm trên return (dest location usage=supplier)."""
    cr.execute(
        """
        SELECT m.id
          FROM vas_move m
          JOIN stock_move sm ON sm.id = m.source_res_id
          JOIN stock_location dest ON dest.id = sm.location_dest_id
         WHERE m.source_model = 'stock.move'
           AND m.move_kind = 'stock'
           AND COALESCE(m.is_reversal, false) = false
           AND m.state NOT IN ('reversed', 'cancelled')
           AND dest.usage = 'supplier'
         ORDER BY m.id
        """
    )
    return [row[0] for row in cr.fetchall()]


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    move_ids = _bad_r06_return_move_ids(cr)
    if not move_ids:
        _logger.info(
            'connecta_vas 19.0.1.26.0: khong co JE R06-sai tren phieu tra NCC'
        )
        return

    Move = env['vas.move']
    moves = Move.browse(move_ids).exists()
    reversed_count = 0
    errors = 0
    companies = env['res.company']
    for move in moves:
        try:
            move.action_reverse()
            reversed_count += 1
            companies |= move.company_id
            _logger.info(
                'connecta_vas: dao JE R06-sai tren return id=%s %s company=%s',
                move.id, move.name, move.company_id.id,
            )
        except Exception:
            errors += 1
            _logger.exception(
                'connecta_vas: khong dao duoc vas.move id=%s %s',
                move.id, move.name,
            )

    # Sinh R09s cho phiếu trả (domain R06 mới không còn nuốt).
    Sync = env['vas.sync']
    for company in companies:
        if not company.vas_regime_id:
            continue
        try:
            stats = Sync._sync_purchase_return_stocks(company, None, None)
            _logger.info(
                'connecta_vas: R09s sau migration company=%s stats=%s',
                company.id, stats,
            )
        except Exception:
            errors += 1
            _logger.exception(
                'connecta_vas: R09s sync that bai company=%s', company.id,
            )

    _logger.warning(
        'connecta_vas 19.0.1.26.0: da dao %s JE R06-sai tren return; '
        'errors=%s. LUU Y: GIT(151)×phieu tra chua tinh chinh (R09s van 331/156).',
        reversed_count, errors,
    )
