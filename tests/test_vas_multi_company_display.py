# -*- coding: utf-8 -*-
"""Cách ly hiển thị đa công ty — ir.rule trên move/journal/FY/map."""
from odoo import Command
from odoo.tests import tagged, TransactionCase


@tagged('connecta_vas', 'connecta_vas_multi_company')
class TestVasMultiCompanyDisplayRules(TransactionCase):
    """O1/O4/O5/N5/N6: chỉ thấy dữ liệu công ty đang bật (+ dòng map chung)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.env.company
        cls.company_b = cls.env['res.company'].create({
            'name': 'VAS Multi Co B',
            'currency_id': cls.env.ref('base.VND').id,
        })
        cls.regime = cls.env['vas.regime'].search([('code', '=', 'TT133')], limit=1)
        if not cls.regime:
            cls.regime = cls.env['vas.regime'].create({
                'code': 'TT133_MC',
                'name': 'TT133 Multi Co',
            })
        cls.company_a.vas_regime_id = cls.regime
        cls.company_b.vas_regime_id = cls.regime
        cls.company_a.vas_start_date = '2099-01-01'
        cls.company_b.vas_start_date = '2099-01-01'

        Journal = cls.env['vas.journal']
        cls.journal_a = Journal.create({
            'code': 'TH-A',
            'name': 'Sổ chung A',
            'type': 'general',
            'regime_id': cls.regime.id,
            'company_id': cls.company_a.id,
        })
        cls.journal_b = Journal.create({
            'code': 'TH-B',
            'name': 'Sổ chung B',
            'type': 'general',
            'regime_id': cls.regime.id,
            'company_id': cls.company_b.id,
        })

        Acc = cls.env['vas.account']
        cls.acc_111 = Acc.search([
            ('regime_id', '=', cls.regime.id), ('code', '=', '111'),
        ], limit=1) or Acc.create({
            'code': '111MC',
            'name': 'Tien mat MC',
            'regime_id': cls.regime.id,
            'account_type': 'asset',
            'ending_balance_policy': 'debit',
        })
        cls.acc_511 = Acc.search([
            ('regime_id', '=', cls.regime.id), ('code', '=', '511'),
        ], limit=1) or Acc.create({
            'code': '511MC',
            'name': 'Doanh thu MC',
            'regime_id': cls.regime.id,
            'account_type': 'income',
            'ending_balance_policy': 'none',
        })

        Move = cls.env['vas.move']
        cls.move_a = Move.create({
            'date': '2099-01-15',
            'journal_id': cls.journal_a.id,
            'regime_id': cls.regime.id,
            'company_id': cls.company_a.id,
            'currency_id': cls.env.ref('base.VND').id,
            'ref': 'MC-A',
            'line_ids': [
                Command.create({
                    'account_id': cls.acc_111.id, 'name': 'A',
                    'debit': 1000, 'credit': 0,
                }),
                Command.create({
                    'account_id': cls.acc_511.id, 'name': 'A',
                    'debit': 0, 'credit': 1000,
                }),
            ],
        })
        cls.move_b = Move.create({
            'date': '2099-01-15',
            'journal_id': cls.journal_b.id,
            'regime_id': cls.regime.id,
            'company_id': cls.company_b.id,
            'currency_id': cls.env.ref('base.VND').id,
            'ref': 'MC-B',
            'line_ids': [
                Command.create({
                    'account_id': cls.acc_111.id, 'name': 'B',
                    'debit': 2000, 'credit': 0,
                }),
                Command.create({
                    'account_id': cls.acc_511.id, 'name': 'B',
                    'debit': 0, 'credit': 2000,
                }),
            ],
        })

        FY = cls.env['vas.fiscalyear']
        cls.fy_a = FY.create({
            'name': 'FY-A-2099',
            'date_from': '2099-01-01',
            'date_to': '2099-12-31',
            'company_id': cls.company_a.id,
            'state': 'open',
        })
        cls.fy_b = FY.create({
            'name': 'FY-B-2099',
            'date_from': '2099-01-01',
            'date_to': '2099-12-31',
            'company_id': cls.company_b.id,
            'state': 'open',
        })

        categ = cls.env['product.category'].create({'name': 'MC Categ'})
        Map = cls.env['vas.account.map']
        cls.map_shared = Map.create({
            'regime_id': cls.regime.id,
            'apply_to': 'category',
            'category_id': categ.id,
            'company_id': False,
            'revenue_account_id': cls.acc_511.id,
        })
        cls.map_a = Map.create({
            'regime_id': cls.regime.id,
            'apply_to': 'category',
            'category_id': categ.id,
            'company_id': cls.company_a.id,
            'revenue_account_id': cls.acc_511.id,
        })
        cls.map_b = Map.create({
            'regime_id': cls.regime.id,
            'apply_to': 'category',
            'category_id': categ.id,
            'company_id': cls.company_b.id,
            'revenue_account_id': cls.acc_511.id,
        })

        # User chỉ thuộc công ty A
        cls.user_a = cls.env['res.users'].create({
            'name': 'VAS User A only',
            'login': 'vas_user_a_only_%s' % cls.env.uid,
            'company_id': cls.company_a.id,
            'company_ids': [Command.set([cls.company_a.id])],
            'group_ids': [Command.set([
                cls.env.ref('base.group_user').id,
                cls.env.ref('base.group_system').id,
            ])],
        })

    def test_o1_move_isolated_by_allowed_companies(self):
        Move = self.env['vas.move']
        moves_a = Move.with_company(self.company_a).with_context(
            allowed_company_ids=[self.company_a.id],
        ).search([('id', 'in', (self.move_a | self.move_b).ids)])
        self.assertEqual(moves_a, self.move_a)

        moves_b = Move.with_company(self.company_b).with_context(
            allowed_company_ids=[self.company_b.id],
        ).search([('id', 'in', (self.move_a | self.move_b).ids)])
        self.assertEqual(moves_b, self.move_b)

    def test_n5_fiscalyear_isolated(self):
        FY = self.env['vas.fiscalyear']
        seen_b = FY.with_company(self.company_b).with_context(
            allowed_company_ids=[self.company_b.id],
        ).search([('id', 'in', (self.fy_a | self.fy_b).ids)])
        self.assertEqual(seen_b, self.fy_b)

        periods_b = self.env['vas.period'].with_company(self.company_b).with_context(
            allowed_company_ids=[self.company_b.id],
        ).search([('fiscalyear_id', 'in', (self.fy_a | self.fy_b).ids)])
        self.assertTrue(periods_b)
        self.assertTrue(all(p.fiscalyear_id == self.fy_b for p in periods_b))

    def test_n6_journal_isolated(self):
        Journal = self.env['vas.journal']
        seen_b = Journal.with_company(self.company_b).with_context(
            allowed_company_ids=[self.company_b.id],
        ).search([('id', 'in', (self.journal_a | self.journal_b).ids)])
        self.assertEqual(seen_b, self.journal_b)

    def test_o5_account_map_shared_plus_own_only(self):
        Map = self.env['vas.account.map']
        ids = (self.map_shared | self.map_a | self.map_b).ids
        seen_a = Map.with_company(self.company_a).with_context(
            allowed_company_ids=[self.company_a.id],
        ).search([('id', 'in', ids)])
        self.assertEqual(seen_a, self.map_shared | self.map_a)

        seen_b = Map.with_company(self.company_b).with_context(
            allowed_company_ids=[self.company_b.id],
        ).search([('id', 'in', ids)])
        self.assertEqual(seen_b, self.map_shared | self.map_b)

    def test_o4_user_a_cannot_see_move_b(self):
        Move = self.env['vas.move'].with_user(self.user_a).with_company(
            self.company_a,
        ).with_context(allowed_company_ids=[self.company_a.id])
        seen = Move.search([('id', 'in', (self.move_a | self.move_b).ids)])
        self.assertEqual(seen, self.move_a)
