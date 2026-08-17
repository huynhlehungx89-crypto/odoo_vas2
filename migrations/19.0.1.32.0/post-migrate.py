# -*- coding: utf-8 -*-
"""W9.5: gán period_id cho move mồ côi khi đã có kỳ phủ ngày (§8.2)."""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Period = env['vas.period']
    periods = Period.search([])
    assigned = periods._assign_orphan_moves()
    remaining = env['vas.move'].search_count([('period_id', '=', False)])
    _logger.info(
        'VAS W9.5 migrate: assigned=%s orphan remaining=%s',
        assigned, remaining,
    )
