# -*- coding: utf-8 -*-
"""W10 chặng 1: gán ending_balance_policy cho TK TT133 từ Danh_Muc_TK."""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

# Ánh xạ mã TK → policy (cột «Tính chất số dư» sheet Danh_Muc_TK).
# debit_or_credit = mọi biến thể «có thể dư Nợ/Có».
POLICY_BY_CODE = {
    '111': 'debit',
    '1111': 'debit',
    '1112': 'debit',
    '112': 'debit',
    '1121': 'debit',
    '1122': 'debit',
    '121': 'debit',
    '128': 'debit',
    '1281': 'debit',
    '1288': 'debit',
    '131': 'debit_or_credit',
    '133': 'debit',
    '1331': 'debit',
    '1332': 'debit',
    '136': 'debit',
    '1361': 'debit',
    '1368': 'debit',
    '138': 'debit_or_credit',
    '1381': 'debit_or_credit',
    '1386': 'debit_or_credit',
    '1388': 'debit_or_credit',
    '141': 'debit',
    '151': 'debit',
    '152': 'debit',
    '153': 'debit',
    '154': 'debit',
    '155': 'debit',
    '156': 'debit',
    '157': 'debit',
    '211': 'debit',
    '2111': 'debit',
    '2112': 'debit',
    '2113': 'debit',
    '214': 'credit',
    '2141': 'credit',
    '2142': 'credit',
    '2143': 'credit',
    '2147': 'credit',
    '217': 'debit',
    '228': 'debit',
    '2281': 'debit',
    '2288': 'debit',
    '229': 'credit',
    '2291': 'credit',
    '2292': 'credit',
    '2293': 'credit',
    '2294': 'credit',
    '241': 'debit',
    '2411': 'debit',
    '2412': 'debit',
    '2413': 'debit',
    '242': 'debit',
    '331': 'debit_or_credit',
    '333': 'debit_or_credit',
    '3331': 'debit_or_credit',
    '33311': 'debit_or_credit',
    '33312': 'debit_or_credit',
    '3332': 'debit_or_credit',
    '3333': 'debit_or_credit',
    '3334': 'debit_or_credit',
    '3335': 'debit_or_credit',
    '3336': 'debit_or_credit',
    '3337': 'debit_or_credit',
    '3338': 'debit_or_credit',
    '33381': 'debit_or_credit',
    '33382': 'debit_or_credit',
    '3339': 'debit_or_credit',
    '334': 'debit_or_credit',
    '335': 'credit',
    '336': 'credit',
    '3361': 'credit',
    '3368': 'credit',
    '338': 'debit_or_credit',
    '3381': 'debit_or_credit',
    '3382': 'debit_or_credit',
    '3383': 'debit_or_credit',
    '3384': 'debit_or_credit',
    '3385': 'debit_or_credit',
    '3386': 'debit_or_credit',
    '3387': 'debit_or_credit',
    '3388': 'debit_or_credit',
    '341': 'credit',
    '3411': 'credit',
    '3412': 'credit',
    '352': 'credit',
    '3521': 'credit',
    '3522': 'credit',
    '3524': 'credit',
    '353': 'credit',
    '3531': 'credit',
    '3532': 'credit',
    '3533': 'credit',
    '3534': 'credit',
    '356': 'credit',
    '3561': 'credit',
    '3562': 'credit',
    '411': 'credit',
    '4111': 'credit',
    '4112': 'debit_or_credit',
    '4118': 'credit',
    '413': 'none',
    '418': 'credit',
    '419': 'debit',
    '421': 'debit_or_credit',
    '4211': 'debit_or_credit',
    '4212': 'debit_or_credit',
    '511': 'none',
    '5111': 'none',
    '5112': 'none',
    '5113': 'none',
    '5118': 'none',
    '515': 'none',
    '611': 'none',
    '631': 'none',
    '632': 'none',
    '635': 'none',
    '642': 'none',
    '6421': 'none',
    '6422': 'none',
    '711': 'none',
    '811': 'none',
    '821': 'none',
    '911': 'none',
}


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Account = env['vas.account'].with_context(active_test=False)
    updated = 0
    missing_map = []
    empty_after = []
    for account in Account.search([]):
        policy = POLICY_BY_CODE.get(account.code)
        if not policy:
            if not account.ending_balance_policy:
                if account.parent_id and account.parent_id.ending_balance_policy:
                    account.ending_balance_policy = account.parent_id.ending_balance_policy
                    updated += 1
                else:
                    missing_map.append(account.code)
            continue
        if account.ending_balance_policy != policy:
            account.ending_balance_policy = policy
            updated += 1
    for account in Account.search([('ending_balance_policy', '=', False)]):
        empty_after.append('%s(%s)' % (account.code, account.regime_id.code or ''))
    _logger.info(
        'VAS W10 migrate ending_balance_policy: updated=%s missing_map=%s empty_after=%s',
        updated, missing_map, empty_after,
    )
    if empty_after:
        raise RuntimeError(
            'W10 migration: TK còn trống ending_balance_policy: %s' % ', '.join(empty_after)
        )
