# -*- coding: utf-8 -*-
"""P2 — Số dư đầu kỳ: import / nhập tay / xác nhận / mở lại."""
import base64

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged, TransactionCase
from odoo.tools import float_compare


@tagged('connecta_vas', 'connecta_vas_opening')
class TestVasOpeningBalance(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.vnd = cls.env.ref('base.VND')
        if cls.company.currency_id != cls.vnd:
            cls.company.currency_id = cls.vnd

        cls.regime = cls.env['vas.regime'].search([('code', '=', 'TT133')], limit=1)
        if not cls.regime:
            cls.regime = cls.env['vas.regime'].create({
                'code': 'TT133', 'name': 'Thông tư 133',
            })
        cls.company.vas_regime_id = cls.regime
        cls.company.vas_start_date = '2099-01-01'

        cls.env['vas.journal']._connecta_seed_tt133_journals()

        cls.fiscalyear = cls.env['vas.fiscalyear'].search([
            ('company_id', '=', cls.company.id),
            ('date_from', '<=', '2099-01-01'),
            ('date_to', '>=', '2099-01-01'),
        ], limit=1)
        if not cls.fiscalyear:
            cls.fiscalyear = cls.env['vas.fiscalyear'].create({
                'name': '2099',
                'date_from': '2099-01-01',
                'date_to': '2099-12-31',
                'state': 'open',
                'company_id': cls.company.id,
            })
        cls.period = cls.env['vas.period'].search([
            ('fiscalyear_id', '=', cls.fiscalyear.id),
            ('date_start', '<=', '2099-01-01'),
            ('date_end', '>=', '2099-01-01'),
        ], limit=1)
        if not cls.period:
            cls.period = cls.env['vas.period'].create({
                'name': '01/2099',
                'date_start': '2099-01-01',
                'date_end': '2099-01-31',
                'fiscalyear_id': cls.fiscalyear.id,
                'state': 'open',
            })
        else:
            cls.period.state = 'open'

        cls.Account = cls.env['vas.account']
        for code in ('111', '131', '331', '411', '156'):
            acc = cls.Account.search([
                ('regime_id', '=', cls.regime.id), ('code', '=', code),
            ], limit=1)
            assert acc, f'Thiếu vas.account {code}'
            setattr(cls, f'acc_{code}', acc)

        cls.partner_ar = cls.env['res.partner'].create({
            'name': 'KH SDK AR',
            'company_id': cls.company.id,
            'customer_rank': 1,
        })
        cls.partner_ap = cls.env['res.partner'].create({
            'name': 'NCC SDK AP',
            'company_id': cls.company.id,
            'supplier_rank': 1,
        })
        cls.partner_extra = cls.env['res.partner'].create({
            'name': 'KH SDK Extra',
            'company_id': cls.company.id,
            'customer_rank': 1,
        })

    def _csv_b64(self, body: str) -> bytes:
        return base64.b64encode(body.encode('utf-8-sig'))

    def _import(self, opening, csv_body, mode='replace'):
        wiz = self.env['vas.opening.balance.import.wizard'].create({
            'opening_id': opening.id,
            'mode': mode,
            'data_file': self._csv_b64(csv_body),
            'filename': 'sdk.csv',
        })
        wiz.action_import()
        return opening

    def _balanced_csv(self):
        # Nợ 111 5tr + 131 3tr = 8tr; Có 411 5tr + 331 3tr = 8tr
        return (
            'Mã TK,Đối tác,Nợ,Có\n'
            '111,,5000000,0\n'
            f'131,{self.partner_ar.name},3000000,0\n'
            '411,,0,5000000\n'
            f'331,{self.partner_ap.name},0,3000000\n'
        )

    def _new_draft(self):
        return self.env['vas.opening.balance'].create({
            'company_id': self.company.id,
            'regime_id': self.regime.id,
            'date': self.company.vas_start_date,
            'ref': 'SDK test',
        })

    def test_p2_01_import_balanced_confirm_opening(self):
        opening = self._new_draft()
        self._import(opening, self._balanced_csv())
        self.assertEqual(len(opening.line_ids), 4)
        opening.action_confirm()

        self.assertEqual(opening.state, 'posted')
        move = opening.move_id
        self.assertTrue(move)
        self.assertEqual(move.state, 'posted')
        self.assertEqual(move.move_kind, 'opening')
        self.assertEqual(move.date, fields.Date.to_date('2099-01-01'))

        by_code = {l.account_id.code: l for l in move.line_ids}
        self.assertEqual(by_code['111'].debit, 5_000_000.0)
        self.assertEqual(by_code['411'].credit, 5_000_000.0)

        line_131 = move.line_ids.filtered(lambda l: l.account_id.code == '131')
        line_331 = move.line_ids.filtered(lambda l: l.account_id.code == '331')
        self.assertEqual(line_131.partner_id, self.partner_ar)
        self.assertEqual(line_331.partner_id, self.partner_ap)
        self.assertEqual(line_131.debit, 3_000_000.0)
        self.assertEqual(line_331.credit, 3_000_000.0)
        self.assertEqual(
            float_compare(line_131.amount_residual, 3_000_000.0, precision_digits=2), 0,
            f'131 residual={line_131.amount_residual}',
        )
        self.assertEqual(
            float_compare(line_331.amount_residual, -3_000_000.0, precision_digits=2), 0,
            f'331 residual={line_331.amount_residual}',
        )
        print(
            f'\n=== P2.1 opening={move.name} ===\n'
            f'  lines={[(l.account_id.code, l.partner_id.name, l.debit, l.credit, l.amount_residual) for l in move.line_ids]}\n'
        )

    def test_p2_02_unbalanced_blocks_confirm(self):
        opening = self._new_draft()
        # Nợ 5tr, Có 4tr → lệch 1tr
        csv_body = (
            'Mã TK,Đối tác,Nợ,Có\n'
            '111,,5000000,0\n'
            '411,,0,4000000\n'
        )
        self._import(opening, csv_body)
        with self.assertRaises(UserError) as ctx:
            opening.action_confirm()
        msg = str(ctx.exception)
        self.assertIn('Lệch', msg)
        self.assertTrue(
            '1000000' in msg.replace(',', '').replace('.0', '')
            or '1,000,000' in msg
            or '1000000.0' in msg
            or opening.amount_diff == 1_000_000.0,
            f'Phải báo lệch 1.000.000: {msg}; diff={opening.amount_diff}',
        )
        self.assertEqual(opening.state, 'draft')
        self.assertFalse(opening.move_id)
        print(f'\n=== P2.2 blocked diff={opening.amount_diff} msg={msg} ===\n')

    def test_p2_03_manual_line_same_draft_as_import(self):
        opening = self._new_draft()
        self._import(opening, self._balanced_csv())
        # Thêm tay 1 dòng công nợ 131 + đối ứng 411 (để vẫn cân)
        self.env['vas.opening.balance.line'].create({
            'opening_id': opening.id,
            'account_id': self.acc_131.id,
            'partner_id': self.partner_extra.id,
            'debit': 1_000_000.0,
            'credit': 0.0,
        })
        self.env['vas.opening.balance.line'].create({
            'opening_id': opening.id,
            'account_id': self.acc_411.id,
            'debit': 0.0,
            'credit': 1_000_000.0,
        })
        self.assertEqual(len(opening.line_ids), 6)
        opening.action_confirm()

        move = opening.move_id
        extra = move.line_ids.filtered(
            lambda l: l.account_id.code == '131' and l.partner_id == self.partner_extra
        )
        self.assertTrue(extra, 'Dòng tay phải vào opening cùng bộ nháp import')
        self.assertEqual(extra.debit, 1_000_000.0)
        print(
            f'\n=== P2.3 shared draft ===\n'
            f'  draft_lines={len(opening.line_ids)} opening_lines={len(move.line_ids)}\n'
            f'  extra_131 partner={extra.partner_id.name} debit={extra.debit}\n'
        )

    def test_p2_04_reopen_edit_reconfirm_then_lock_blocks(self):
        opening = self._new_draft()
        self._import(opening, self._balanced_csv())
        opening.action_confirm()
        old_move = opening.move_id
        old_name = old_move.name

        opening.action_reopen()
        self.assertEqual(opening.state, 'draft')
        self.assertFalse(opening.move_id)
        self.assertEqual(old_move.state, 'reversed')
        self.assertTrue(old_move.reversal_move_id)
        self.assertEqual(old_move.reversal_move_id.state, 'posted')

        # Sửa: tăng 111 Nợ + tăng 411 Có thêm 500k
        line_111 = opening.line_ids.filtered(lambda l: l.account_id.code == '111')
        line_411 = opening.line_ids.filtered(lambda l: l.account_id.code == '411')
        line_111.debit = 5_500_000.0
        line_411.credit = 5_500_000.0

        opening.action_confirm()
        new_move = opening.move_id
        self.assertNotEqual(new_move, old_move)
        self.assertEqual(new_move.state, 'posted')
        self.assertEqual(new_move.move_kind, 'opening')
        by_code = {l.account_id.code: l for l in new_move.line_ids}
        self.assertEqual(by_code['111'].debit, 5_500_000.0)
        self.assertEqual(by_code['411'].credit, 5_500_000.0)

        # Khóa kỳ đầu → mở lại bị chặn
        self.period.state = 'closed'
        with self.assertRaises(UserError) as ctx:
            opening.action_reopen()
        self.assertIn('khóa', str(ctx.exception).lower())
        print(
            f'\n=== P2.4 reopen ===\n'
            f'  old={old_name} state={old_move.state} reverse={old_move.reversal_move_id.name}\n'
            f'  new={new_move.name} 111={by_code["111"].debit} 411={by_code["411"].credit}\n'
            f'  locked reopen blocked: {ctx.exception}\n'
        )

    def test_p2_import_rejects_unknown_account(self):
        opening = self._new_draft()
        csv_body = (
            'Mã TK,Đối tác,Nợ,Có\n'
            '99999,,1000,0\n'
            '411,,0,1000\n'
        )
        with self.assertRaises(UserError) as ctx:
            self._import(opening, csv_body)
        self.assertIn('99999', str(ctx.exception))
        self.assertFalse(opening.line_ids)
