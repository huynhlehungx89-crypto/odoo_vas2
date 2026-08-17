# -*- coding: utf-8 -*-
"""W10 chặng 5 — gate đóng kỳ P&L (A1=C) + đảo V09 DELTA."""
from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged, TransactionCase
from odoo.tools.float_utils import float_compare


@tagged('post_install', '-at_install', 'connecta_vas', 'connecta_vas_w10')
class TestW10PeriodGateAndV09Delta(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.regime = cls.env.ref('connecta_vas.vas_regime_tt133')
        if not cls.company.vas_regime_id:
            cls.company.vas_regime_id = cls.regime
        cls.company.vas_start_date = '2093-01-01'
        cls.company.fiscalyear_last_day = 31
        cls.company.fiscalyear_last_month = '12'
        vnd = cls.env.ref('base.VND')
        if cls.company.currency_id != vnd:
            cls.company.currency_id = vnd
        cls.usd = cls.env.ref('base.USD')
        cls.usd.active = True

        fy = cls.env['vas.fiscalyear'].search([
            ('company_id', '=', cls.company.id),
            ('date_from', '=', '2093-01-01'),
            ('date_to', '=', '2093-12-31'),
        ], limit=1)
        if not fy:
            fy = cls.env['vas.fiscalyear'].create({
                'name': 'W10G-2093',
                'date_from': '2093-01-01',
                'date_to': '2093-12-31',
                'state': 'open',
                'company_id': cls.company.id,
            })
        cls.fy = fy
        for start, end, name in (
            ('2093-06-01', '2093-06-30', '06/2093-G'),
            ('2093-12-01', '2093-12-31', '12/2093-G'),
        ):
            p = cls.env['vas.period'].search([
                ('fiscalyear_id', '=', fy.id),
                ('date_start', '=', start),
            ], limit=1)
            if not p:
                p = cls.env['vas.period'].create({
                    'name': name,
                    'date_start': start,
                    'date_end': end,
                    'fiscalyear_id': fy.id,
                    'state': 'open',
                })
            if start.startswith('2093-06'):
                cls.period_jun = p
            else:
                cls.period_dec = p

        cls.journal = cls.env['vas.journal'].search([
            ('company_id', '=', cls.company.id), ('code', '=', 'KC'),
        ], limit=1)
        if not cls.journal:
            cls.journal = cls.env['vas.journal'].search([
                ('company_id', '=', cls.company.id),
            ], limit=1)
        cls.Entry = cls.env['vas.closing.entry']

    def _acc(self, code):
        return self.env.ref('connecta_vas.vas_account_tt133_%s' % code)

    def _post_pair(self, day, debit_acc, credit_acc, amount, name='W10G',
                   currency=None, amount_currency=None):
        vals_d = {
            'account_id': debit_acc.id, 'name': name,
            'debit': amount, 'credit': 0.0,
        }
        vals_c = {
            'account_id': credit_acc.id, 'name': name,
            'debit': 0.0, 'credit': amount,
        }
        if currency and amount_currency is not None:
            vals_d.update({
                'currency_id': currency.id,
                'amount_currency': abs(amount_currency),
            })
        move = self.env['vas.move'].create({
            'date': day,
            'journal_id': self.journal.id,
            'regime_id': self.regime.id,
            'move_kind': 'manual',
            'company_id': self.company.id,
            'ref': name,
            'line_ids': [(0, 0, vals_d), (0, 0, vals_c)],
        })
        move.action_post()
        return move

    def _set_usd_rate(self, day, vnd_per_usd):
        Rate = self.env['res.currency.rate']
        rate_val = 1.0 / vnd_per_usd
        existing = Rate.search([
            ('currency_id', '=', self.usd.id),
            ('name', '=', day),
            ('company_id', '=', self.company.id),
        ], limit=1)
        if existing:
            existing.rate = rate_val
        else:
            Rate.create({
                'currency_id': self.usd.id,
                'name': day,
                'company_id': self.company.id,
                'rate': rate_val,
            })
        got = self.usd._convert(100.0, self.env.ref('base.VND'), self.company, day)
        if float_compare(got, 100.0 * vnd_per_usd, precision_digits=0) != 0:
            Rate.search([
                ('currency_id', '=', self.usd.id),
                ('name', '=', day),
                ('company_id', '=', self.company.id),
            ], limit=1).rate = vnd_per_usd

    def test_01_year_end_open_pl_blocks_close(self):
        self.assertTrue(self.period_dec._is_fiscal_year_end_period())
        self._post_pair('2093-12-10', self._acc('111'), self._acc('511'), 200_000, 'DT')
        open_list = self.period_dec._find_open_pl_none_balances()
        self.assertTrue(any(a.code == '511' for a, _amt, _s in open_list))
        with self.assertRaises(UserError) as err:
            self.period_dec.with_context(vas_skip_asset_lock_check=True).write({
                'state': 'closed',
            })
        msg = err.exception.args[0]
        self.assertIn('511', msg)
        self.assertIn('kết chuyển', msg.lower())
        self.assertNotIn('ending_balance_policy', msg)
        self.assertEqual(self.period_dec.state, 'open')

    def test_02_year_end_after_close_ok(self):
        self._post_pair('2093-12-10', self._acc('111'), self._acc('511'), 150_000, 'DT')
        entry = self.Entry.create({
            'company_id': self.company.id,
            'date_from': '2093-12-01',
            'date_to': '2093-12-31',
            'run_kqkd': True,
        })
        self.assertTrue(entry.is_year_end)
        entry.action_fetch_data()
        entry.action_post()
        open_list = self.period_dec._find_open_pl_none_balances()
        self.assertFalse(any(
            a.code in ('511', '911') for a, _a, _s in open_list
        ))
        # Các TK none khác cũng phải sạch trong năm test riêng 2093
        self.assertFalse(open_list, open_list)
        self.period_dec.with_context(vas_skip_asset_lock_check=True).write({
            'state': 'closed',
        })
        self.assertEqual(self.period_dec.state, 'closed')
        self.period_dec.with_context(vas_skip_asset_lock_check=True).write({
            'state': 'open',
        })

    def test_03_mid_year_warn_allows_close(self):
        self.assertFalse(self.period_jun._is_fiscal_year_end_period())
        self._post_pair('2093-06-10', self._acc('111'), self._acc('511'), 80_000, 'DT')
        open_list = self.period_jun._find_open_pl_none_balances()
        self.assertTrue(any(a.code == '511' for a, _a, _s in open_list))
        self.period_jun.with_context(vas_skip_asset_lock_check=True).write({
            'state': 'closed',
        })
        self.assertEqual(self.period_jun.state, 'closed')
        self.period_jun.with_context(vas_skip_asset_lock_check=True).write({
            'state': 'open',
        })

    def test_05_v09_reverse_delta_zero_net(self):
        """Đảo phiếu V09: cả 2 move đảo; không orphan; DELTA số dư FX về 0."""
        self._set_usd_rate('2093-06-01', 25_000.0)
        self._set_usd_rate('2093-06-30', 26_000.0)
        self._post_pair(
            '2093-06-05', self._acc('1122'), self._acc('511'), 2_500_000,
            'USD', currency=self.usd, amount_currency=100.0,
        )
        Move = self.env['vas.move']
        Line = self.env['vas.move.line']
        before_m = Move.search_count([('company_id', '=', self.company.id)])
        before_l = Line.search_count([('company_id', '=', self.company.id)])
        amt0, side0 = self.env['vas.closing.rule'].compute_closing_amount(
            self._acc('413'), self.company, '2000-01-01', '2093-06-30', 'both',
        )
        entry = self.Entry.create({
            'company_id': self.company.id,
            'date_from': '2093-06-01',
            'date_to': '2093-06-30',
            'run_kqkd': False,
            'run_fx': True,
        })
        entry.action_fetch_data()
        entry.action_post()
        batch = entry._batch_active_moves()
        self.assertTrue(batch.filtered(lambda m: m.move_kind == 'forex_reval'))
        self.assertTrue(batch.filtered(lambda m: m.move_kind == 'closing'))
        mid_m = Move.search_count([('company_id', '=', self.company.id)])
        mid_l = Line.search_count([('company_id', '=', self.company.id)])
        n_batch = len(batch)
        n_lines = sum(len(m.line_ids) for m in batch)
        self.assertEqual(mid_m, before_m + n_batch)
        entry.action_reverse_entry()
        after_m = Move.search_count([('company_id', '=', self.company.id)])
        after_l = Line.search_count([('company_id', '=', self.company.id)])
        self.assertEqual(after_m - mid_m, n_batch)
        self.assertEqual(after_l - mid_l, n_lines)
        self.assertFalse(Move.search([
            ('company_id', '=', self.company.id),
            ('state', '=', 'draft'),
            ('is_reversal', '=', True),
        ]))
        amt1, side1 = self.env['vas.closing.rule'].compute_closing_amount(
            self._acc('413'), self.company, '2000-01-01', '2093-06-30', 'both',
        )
        self.assertEqual(side0, side1)
        self.assertEqual(float_compare(amt0, amt1, precision_digits=2), 0)

    def test_06_gate_open_pl_after_reverse_not_doubled(self):
        """Gate đóng kỳ: sau đảo lô, số dư P&L mở = lần đầu (không gấp đôi)."""
        self._post_pair('2093-12-10', self._acc('111'), self._acc('511'), 200_000, 'DT')
        open0 = self.period_dec._find_open_pl_none_balances()
        amt0 = next(amt for a, amt, _s in open0 if a.code == '511')
        self.assertEqual(float_compare(amt0, 200_000.0, 2), 0)
        entry = self.Entry.create({
            'company_id': self.company.id,
            'date_from': '2093-12-01',
            'date_to': '2093-12-31',
            'run_kqkd': True,
        })
        entry.action_fetch_data()
        entry.action_post()
        self.assertFalse(any(
            a.code == '511' for a, _a, _s in self.period_dec._find_open_pl_none_balances()
        ))
        entry.action_reverse_entry()
        open1 = self.period_dec._find_open_pl_none_balances()
        amt1 = next(amt for a, amt, _s in open1 if a.code == '511')
        self.assertEqual(
            float_compare(amt1, amt0, 2), 0,
            'gate 511 sau đảo: %s ≠ %s (gấp đôi?)' % (amt1, amt0),
        )
        e2 = self.Entry.create({
            'company_id': self.company.id,
            'date_from': '2093-12-01',
            'date_to': '2093-12-31',
            'run_kqkd': True,
        })
        e2.action_fetch_data()
        e2.action_post()
        self.assertFalse(any(
            a.code == '511' for a, _a, _s in self.period_dec._find_open_pl_none_balances()
        ))
