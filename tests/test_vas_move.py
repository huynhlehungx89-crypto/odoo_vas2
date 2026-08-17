# -*- coding: utf-8 -*-
from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged, TransactionCase


@tagged('connecta_vas')
class TestVasMove(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.vnd = cls.env.ref('base.VND')
        cls.usd = cls.env.ref('base.USD')

        cls.regime = cls.env['vas.regime'].create({
            'code': 'TT133_TEST',
            'name': 'TT133 Test Regime',
        })
        cls.account_debit = cls.env['vas.account'].create({
            'code': '111',
            'name': 'Cash',
            'regime_id': cls.regime.id,
            'account_type': 'asset',
            'ending_balance_policy': 'debit',
        })
        cls.account_credit = cls.env['vas.account'].create({
            'code': '511',
            'name': 'Revenue',
            'regime_id': cls.regime.id,
            'account_type': 'income',
            'ending_balance_policy': 'none',
        })
        cls.account_recon = cls.env['vas.account'].create({
            'code': '131',
            'name': 'Receivable',
            'regime_id': cls.regime.id,
            'account_type': 'asset',
            'ending_balance_policy': 'debit',
            'reconcile': True,
        })

        cls.sequence = cls.env['ir.sequence'].create({
            'name': 'VAS Test Journal Sequence',
            'code': 'vas.move.test',
            'prefix': 'VAS/%(year)s/',
            'padding': 4,
            'company_id': cls.company.id,
        })
        cls.journal = cls.env['vas.journal'].create({
            'code': 'TST',
            'name': 'General Test',
            'type': 'general',
            'regime_id': cls.regime.id,
            'sequence_id': cls.sequence.id,
            'company_id': cls.company.id,
        })

        cls.fiscalyear = cls.env['vas.fiscalyear'].create({
            'name': '2099',
            'date_from': '2099-01-01',
            'date_to': '2099-12-31',
            'state': 'open',
            'company_id': cls.company.id,
        })
        cls.period = cls.env['vas.period'].create({
            'name': '01/2099',
            'date_start': '2099-01-01',
            'date_end': '2099-01-31',
            'fiscalyear_id': cls.fiscalyear.id,
            'state': 'open',
        })
        # Hàng rào cutoff lúc post: fixture phải khai mốc ≤ ngày bút toán test.
        cls.company.vas_start_date = '2099-01-01'

    def _make_move(self, debit=100.0, credit=100.0, **move_vals):
        vals = {
            'date': '2099-01-15',
            'journal_id': self.journal.id,
            'regime_id': self.regime.id,
            'move_kind': 'manual',
            'company_id': self.company.id,
            'currency_id': self.vnd.id,
            'line_ids': [
                fields.Command.create({
                    'account_id': self.account_debit.id,
                    'name': 'Debit line',
                    'debit': debit,
                    'credit': 0.0,
                    'currency_id': self.vnd.id,
                }),
                fields.Command.create({
                    'account_id': self.account_credit.id,
                    'name': 'Credit line',
                    'debit': 0.0,
                    'credit': credit,
                    'currency_id': self.vnd.id,
                }),
            ],
        }
        vals.update(move_vals)
        return self.env['vas.move'].create(vals)

    def test_a_post_balanced_ok_unbalanced_raises(self):
        move = self._make_move(debit=100.0, credit=100.0)
        move.action_post()
        self.assertEqual(move.state, 'posted')
        self.assertTrue(move.name and move.name != '/')

        unbalanced = self._make_move(debit=100.0, credit=50.0)
        with self.assertRaises(UserError):
            unbalanced.action_post()
        self.assertEqual(unbalanced.state, 'draft')

    def test_b_closed_period_blocks_create_and_write(self):
        self.period.state = 'closed'
        with self.assertRaises(UserError):
            self._make_move()

        self.period.state = 'open'
        move = self._make_move()
        self.period.state = 'closed'
        with self.assertRaises(UserError):
            move.write({'ref': 'should fail'})

    def test_c_posted_immutable_and_reverse(self):
        move = self._make_move(debit=200.0, credit=200.0)
        move.action_post()
        original_name = move.name
        debit_line = move.line_ids.filtered(lambda l: l.debit)[:1]

        with self.assertRaises(UserError):
            debit_line.write({'debit': 250.0})

        action = move.action_reverse()
        reverse = self.env['vas.move'].browse(action['res_id'])
        self.assertTrue(reverse.exists())
        self.assertTrue(reverse.is_reversal)
        self.assertEqual(reverse.state, 'posted')
        self.assertEqual(move.state, 'reversed')
        self.assertEqual(move.reversal_move_id, reverse)

        # Reversing lines: debit/credit swapped
        self.assertAlmostEqual(sum(reverse.line_ids.mapped('debit')), 200.0)
        self.assertAlmostEqual(sum(reverse.line_ids.mapped('credit')), 200.0)
        orig_debit_account = self.account_debit
        rev_credit_on_cash = reverse.line_ids.filtered(
            lambda l: l.account_id == orig_debit_account and l.credit > 0
        )
        self.assertTrue(rev_credit_on_cash)
        self.assertNotEqual(reverse.name, original_name)

    def test_d_duplicate_source_raises(self):
        move_vals = {
            'source_model': 'account.move',
            'source_res_id': 4242,
            'move_kind': 'sale_inv',
        }
        first = self._make_move(**move_vals)
        first.action_post()

        with self.assertRaises(ValidationError):
            self._make_move(**move_vals)

        # Manual (empty source) allowed multiple times
        self._make_move()
        self._make_move()
