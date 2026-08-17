# -*- coding: utf-8 -*-
"""Lưới an toàn: cờ TK mặc định (5 đường) + whitelist post + hủy (POS/LC ở file khác)."""
from datetime import date

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged, TransactionCase


@tagged('connecta_vas', 'connecta_vas_safety')
class TestSafetyDefaultAccountFlags(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        vnd = cls.env.ref('base.VND')
        if cls.company.currency_id != vnd:
            cls.company.currency_id = vnd
        cls.regime = cls.env['vas.regime'].search([('code', '=', 'TT133')], limit=1)
        if not cls.regime:
            cls.regime = cls.env['vas.regime'].create({
                'code': 'TT133', 'name': 'Thông tư 133/2016/TT-BTC',
            })
        cls.company.vas_regime_id = cls.regime
        cls.company.vas_start_date = '2000-01-01'
        codes = {
            '111': 'asset', '112': 'asset', '153': 'asset', '2111': 'asset',
            '2141': 'asset', '214': 'asset', '331': 'liability',
            '335': 'liability', '3411': 'liability', '4111': 'equity',
            '635': 'expense', '6422': 'expense', '154': 'expense',
        }
        cls.acc = {}
        for code, atype in codes.items():
            rec = cls.env['vas.account'].search([
                ('regime_id', '=', cls.regime.id), ('code', '=', code),
            ], limit=1)
            if not rec:
                rec = cls.env['vas.account'].create({
                    'code': code, 'name': code, 'regime_id': cls.regime.id,
                    'account_type': atype,
                    'ending_balance_policy': 'debit' if atype == 'asset' else 'none',
                })
            cls.acc[code] = rec
        cls.journal = cls.env['vas.journal'].search([
            ('company_id', '=', cls.company.id), ('code', '=', 'TH'),
        ], limit=1)
        if not cls.journal:
            seq = cls.env['ir.sequence'].create({
                'name': 'VAS Safety TH Seq',
                'code': 'vas.move.safety.th',
                'prefix': 'STH/%(year)s/',
                'padding': 4,
                'company_id': cls.company.id,
            })
            cls.journal = cls.env['vas.journal'].create({
                'code': 'TH', 'name': 'Tổng hợp', 'type': 'general',
                'company_id': cls.company.id,
                'sequence_id': seq.id,
            })
        elif not cls.journal.sequence_id:
            seq = cls.env['ir.sequence'].create({
                'name': 'VAS Safety TH Seq',
                'code': 'vas.move.safety.th',
                'prefix': 'STH/%(year)s/',
                'padding': 4,
                'company_id': cls.company.id,
            })
            cls.journal.sequence_id = seq.id
        cls.journal_thu = cls.env['vas.journal'].search([
            ('company_id', '=', cls.company.id), ('code', '=', 'THU'),
        ], limit=1)
        if not cls.journal_thu:
            cls.journal_thu = cls.env['vas.journal'].create({
                'code': 'THU', 'name': 'Thu', 'type': 'cash',
                'company_id': cls.company.id,
            })
        cls.fy = cls.env['vas.fiscalyear'].search([
            ('company_id', '=', cls.company.id),
            ('date_from', '<=', '2084-03-01'),
            ('date_to', '>=', '2084-03-31'),
        ], limit=1)
        if not cls.fy:
            cls.fy = cls.env['vas.fiscalyear'].create({
                'name': '2084-safety',
                'date_from': '2084-01-01',
                'date_to': '2084-12-31',
                'state': 'open',
                'company_id': cls.company.id,
            })
        cls.period = cls.env['vas.period'].search([
            ('fiscalyear_id', '=', cls.fy.id),
            ('date_start', '=', '2084-03-01'),
        ], limit=1)
        if not cls.period:
            cls.period = cls.env['vas.period'].create({
                'name': '03/2084',
                'date_start': '2084-03-01',
                'date_end': '2084-03-31',
                'fiscalyear_id': cls.fy.id,
                'state': 'open',
            })
        else:
            cls.period.state = 'open'

    def _assert_flagged(self, move, needle):
        self.assertTrue(move, 'Phải sinh bút toán')
        self.assertEqual(move.state, 'posted')
        self.assertTrue(move.vas_has_default_account, 'Phải mang cờ TK mặc định')
        self.assertIn(needle, move.narration or '')
        found = self.env['vas.move'].search([
            ('vas_has_default_account', '=', True),
            ('id', '=', move.id),
        ])
        self.assertIn(move, found, 'Phải hiện trên bộ lọc Dùng TK mặc định')
        with self.assertRaises(UserError) as err:
            self.period._check_no_default_account_move()
        self.assertIn('MẶC ĐỊNH', str(err.exception))

    def test_t1_asset_expense_fallback_6422(self):
        asset = self.env['vas.asset'].create({
            'code': 'SAFE-T1',
            'name': 'TSCĐ chưa khai CP',
            'company_id': self.company.id,
            'regime_id': self.regime.id,
            'asset_type': 'tscd',
            'original_value': 120_000_000,
            'date_start': date(2084, 3, 15),
            'method': 'straight_line',
            'useful_life_years': 10,
            'duration_months': 120,
            'prorata': True,
            'account_gross_id': self.acc['2111'].id,
            'account_accum_id': self.acc['2141'].id,
            'account_expense_id': False,
            'journal_id': self.journal.id,
            'source_mode': 'manual',
        })
        asset.action_confirm()
        line = asset.line_ids.filtered(lambda l: l.period_id == self.period)[:1]
        self.assertTrue(line)
        self.env['vas.asset'].generate_asset_entries(self.company, self.period)
        move = line.move_id
        self._assert_flagged(move, 'SAFE-T1')
        self.assertIn('6422', move.narration)
        self.assertIn(
            '6422',
            move.line_ids.filtered('debit').mapped('account_id.code'),
        )

    def test_t2_capital_spawn_2141_6422(self):
        rec = self.env['vas.capital.in.kind'].create({
            'date': '2084-03-10',
            'amount': 80_000_000,
            'asset_account_id': self.acc['2111'].id,
            'spawn_asset': True,
            'asset_name': 'Máy góp vốn T2',
            'ref': 'GVHV-T2',
        })
        rec.action_post()
        asset = rec.asset_id
        self.assertTrue(asset)
        self.assertFalse(asset.account_expense_id)
        asset.write({
            'useful_life_years': 10,
            'duration_months': 120,
            'journal_id': self.journal.id,
        })
        asset.action_confirm()
        line = asset.line_ids.filtered(lambda l: l.period_id == self.period)[:1]
        self.assertTrue(line)
        self.env['vas.asset'].generate_asset_entries(self.company, self.period)
        move = line.move_id
        self._assert_flagged(move, asset.display_name)
        self.assertTrue(
            '2141' in (move.narration or '') or '6422' in (move.narration or ''),
        )

    def test_t3_loan_interest_335_635(self):
        loan = self.env['vas.loan'].create({
            'code': 'SAFE-T3',
            'name': 'Vay chưa khai lãi',
            'company_id': self.company.id,
            'regime_id': self.regime.id,
            'date_start': date(2084, 3, 1),
            'date_end': date(2084, 3, 31),
            'principal': 100_000_000,
            'interest_rate': 0.12,
            'account_loan_id': self.acc['3411'].id,
            'account_interest_expense_id': False,
            'account_interest_payable_id': False,
            'journal_id': self.journal.id,
        })
        loan.action_confirm()
        self.env['vas.loan'].generate_interest_entries(self.company, self.period)
        line = loan.line_ids.filtered(lambda l: l.period_id == self.period)[:1]
        move = line.move_id
        self._assert_flagged(move, 'SAFE-T3')
        codes = set(move.line_ids.mapped('account_id.code'))
        self.assertTrue({'635', '335'} <= codes)

    def test_t4_loan_missing_term_account_3411(self):
        loan = self.env['vas.loan'].create({
            'code': 'SAFE-T4',
            'name': 'Vay chưa khai TK vay',
            'company_id': self.company.id,
            'regime_id': self.regime.id,
            'date_start': date(2084, 3, 1),
            'principal': 50_000_000,
            'interest_rate': 0.12,
            'account_loan_id': False,
            'account_interest_expense_id': self.acc['635'].id,
            'account_interest_payable_id': self.acc['335'].id,
            'journal_id': self.journal.id,
        })
        partner = self.env['res.partner'].create({'name': 'NH T4'})
        bank = self.env['account.journal'].search([
            ('company_id', '=', self.company.id), ('type', '=', 'bank'),
        ], limit=1)
        if not bank:
            self.skipTest('No bank journal')
        payment = self.env['account.payment'].create({
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'partner_id': partner.id,
            'amount': 50_000_000,
            'date': '2084-03-05',
            'journal_id': bank.id,
            'vas_operation_type': 'loan_receipt',
            'vas_loan_id': loan.id,
        })
        payment.write({'state': 'paid'})
        move = self.env['vas.sync']._sync_one_w7_payment(payment, self.company)
        self._assert_flagged(move, 'SAFE-T4')
        self.assertIn(
            '3411',
            move.line_ids.filtered('credit').mapped('account_id.code'),
        )

    def test_t5_capital_in_kind_2111(self):
        rec = self.env['vas.capital.in.kind'].create({
            'date': '2084-03-08',
            'amount': 10_000_000,
            'asset_account_id': False,
            'ref': 'GVHV-T5',
        })
        rec.action_post()
        move = rec.move_id
        self._assert_flagged(move, 'GVHV-T5')
        self.assertIn(
            '2111',
            move.line_ids.filtered('debit').mapped('account_id.code'),
        )

    def test_t6_declare_then_no_flag(self):
        asset = self.env['vas.asset'].create({
            'code': 'SAFE-T6',
            'name': 'TSCĐ khai sau',
            'company_id': self.company.id,
            'regime_id': self.regime.id,
            'asset_type': 'tscd',
            'original_value': 120_000_000,
            'date_start': date(2084, 3, 15),
            'method': 'straight_line',
            'useful_life_years': 10,
            'duration_months': 120,
            'prorata': True,
            'account_gross_id': self.acc['2111'].id,
            'account_accum_id': self.acc['2141'].id,
            'journal_id': self.journal.id,
            'source_mode': 'manual',
        })
        asset.action_confirm()
        line = asset.line_ids.filtered(lambda l: l.period_id == self.period)[:1]
        self.env['vas.asset'].generate_asset_entries(self.company, self.period)
        old = line.move_id
        self.assertTrue(old.vas_has_default_account)
        old.action_reverse()
        asset.account_expense_id = self.acc['154'].id
        line.state = 'planned'
        line.move_id = False
        self.env['vas.asset'].generate_asset_entries(self.company, self.period)
        new = asset.line_ids.filtered(lambda l: l.period_id == self.period)[:1].move_id
        self.assertTrue(new)
        self.assertFalse(new.vas_has_default_account)
        self.period._check_no_default_account_move()


@tagged('connecta_vas', 'connecta_vas_safety')
class TestSafetyPostedWhitelist(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        vnd = cls.env.ref('base.VND')
        if cls.company.currency_id != vnd:
            cls.company.currency_id = vnd
        cls.regime = cls.env['vas.regime'].search([('code', '=', 'TT133')], limit=1)
        if not cls.regime:
            cls.regime = cls.env['vas.regime'].create({
                'code': 'TT133', 'name': 'TT133',
            })
        cls.company.vas_regime_id = cls.regime
        cls.company.vas_start_date = '2000-01-01'
        acc111 = cls.env['vas.account'].search([
            ('regime_id', '=', cls.regime.id), ('code', '=', '111'),
        ], limit=1)
        acc112 = cls.env['vas.account'].search([
            ('regime_id', '=', cls.regime.id), ('code', '=', '112'),
        ], limit=1)
        if not acc111:
            acc111 = cls.env['vas.account'].create({
                'code': '111', 'name': 'TM', 'regime_id': cls.regime.id,
                'account_type': 'asset', 'ending_balance_policy': 'debit',
            })
        if not acc112:
            acc112 = cls.env['vas.account'].create({
                'code': '112', 'name': 'TG', 'regime_id': cls.regime.id,
                'account_type': 'asset', 'ending_balance_policy': 'debit',
            })
        cls.acc111, cls.acc112 = acc111, acc112
        seq = cls.env['ir.sequence'].create({
            'name': 'VAS Safety WL Seq',
            'code': 'vas.move.safety.wl',
            'prefix': 'SWL/%(year)s/',
            'padding': 4,
            'company_id': cls.company.id,
        })
        cls.journal = cls.env['vas.journal'].create({
            'code': 'SWL', 'name': 'Safety WL', 'type': 'general',
            'regime_id': cls.regime.id,
            'sequence_id': seq.id,
            'company_id': cls.company.id,
        })
        fy = cls.env['vas.fiscalyear'].search([
            ('company_id', '=', cls.company.id),
            ('date_from', '<=', '2084-04-01'),
            ('date_to', '>=', '2084-04-30'),
        ], limit=1)
        if not fy:
            fy = cls.env['vas.fiscalyear'].create({
                'name': '2084-wl',
                'date_from': '2084-01-01',
                'date_to': '2084-12-31',
                'state': 'open',
                'company_id': cls.company.id,
            })
        period = cls.env['vas.period'].search([
            ('fiscalyear_id', '=', fy.id),
            ('date_start', '=', '2084-04-01'),
        ], limit=1)
        if not period:
            cls.env['vas.period'].create({
                'name': '04/2084',
                'date_start': '2084-04-01',
                'date_end': '2084-04-30',
                'fiscalyear_id': fy.id,
                'state': 'open',
            })

    def _posted(self):
        move = self.env['vas.move'].create({
            'date': '2084-04-10',
            'journal_id': self.journal.id,
            'regime_id': self.regime.id,
            'move_kind': 'manual',
            'company_id': self.company.id,
            'currency_id': self.company.currency_id.id,
            'line_ids': [
                Command.create({
                    'account_id': self.acc111.id, 'name': 'n',
                    'debit': 1000, 'credit': 0,
                    'currency_id': self.company.currency_id.id,
                }),
                Command.create({
                    'account_id': self.acc112.id, 'name': 'c',
                    'debit': 0, 'credit': 1000,
                    'currency_id': self.company.currency_id.id,
                }),
            ],
        })
        move.action_post()
        return move

    def test_t10_non_whitelist_blocked(self):
        move = self._posted()
        with self.assertRaises(UserError):
            move.write({'ref': 'hack'})

    def test_t11_whitelist_allowed(self):
        move = self._posted()
        move.write({'source_cancel_pending': True})
        self.assertTrue(move.source_cancel_pending)
