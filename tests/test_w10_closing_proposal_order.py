# -*- coding: utf-8 -*-
"""W10 — đề xuất KC tuần tự: cửa chung + cùng lần bấm thấy bước trước."""
from calendar import monthrange
from datetime import date

from odoo.exceptions import UserError
from odoo.tests import tagged, TransactionCase
from odoo.tools.float_utils import float_compare

from odoo.addons.connecta_vas.models.res_company import (
    W11_BCTC_CIT_AMOUNT,
)


@tagged('post_install', '-at_install', 'connecta_vas', 'connecta_vas_w10')
class TestW10ClosingProposalOrder(TransactionCase):
    """Công ty riêng — không đụng env.company / vas_start_date chung."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.regime = cls.env.ref('connecta_vas.vas_regime_tt133')
        vnd = cls.env.ref('base.VND')
        cls.company = cls.env['res.company'].create({
            'name': 'PO-Closing-Order',
            'currency_id': vnd.id,
            'vas_regime_id': cls.regime.id,
            'vas_start_date': '2097-01-01',
            'fiscalyear_last_day': 31,
            'fiscalyear_last_month': '12',
        })
        cls.usd = cls.env.ref('base.USD')
        cls.usd.active = True

        # Sao chép sổ KC/TH từ công ty chính (có sequence)
        for src_code in ('KC', 'TH', 'GEN'):
            src = cls.env['vas.journal'].search([
                ('company_id', '=', cls.env.company.id),
                ('code', '=', src_code),
            ], limit=1)
            if not src:
                continue
            if cls.env['vas.journal'].search([
                ('company_id', '=', cls.company.id), ('code', '=', src.code),
            ], limit=1):
                continue
            cls.env['vas.journal'].create({
                'name': src.name,
                'code': src.code,
                'type': src.type,
                'regime_id': cls.regime.id,
                'company_id': cls.company.id,
                'sequence_id': src.sequence_id.id,
            })
        cls.journal = cls.env['vas.journal'].search([
            ('company_id', '=', cls.company.id), ('code', '=', 'KC'),
        ], limit=1) or cls.env['vas.journal'].search([
            ('company_id', '=', cls.company.id),
        ], limit=1)

        fy = cls.env['vas.fiscalyear'].create({
            'name': 'PO-2097',
            'date_from': '2097-01-01',
            'date_to': '2097-12-31',
            'state': 'open',
            'company_id': cls.company.id,
        })
        cls.fy = fy
        for m in range(1, 13):
            last = monthrange(2097, m)[1]
            if not cls.env['vas.period'].search([
                ('fiscalyear_id', '=', fy.id),
                ('date_start', '=', '2097-%02d-01' % m),
            ], limit=1):
                cls.env['vas.period'].create({
                    'name': '%02d/2097-PO' % m,
                    'date_start': '2097-%02d-01' % m,
                    'date_end': '2097-%02d-%02d' % (m, last),
                    'fiscalyear_id': fy.id,
                    'state': 'open',
                })
        fy2 = cls.env['vas.fiscalyear'].create({
            'name': 'PO-2098',
            'date_from': '2098-01-01',
            'date_to': '2098-12-31',
            'state': 'open',
            'company_id': cls.company.id,
        })
        cls.fy2 = fy2
        if not cls.env['vas.period'].search([
            ('fiscalyear_id', '=', fy2.id),
            ('date_start', '=', '2098-01-01'),
        ], limit=1):
            cls.env['vas.period'].create({
                'name': '01/2098-PO',
                'date_start': '2098-01-01',
                'date_end': '2098-01-31',
                'fiscalyear_id': fy2.id,
                'state': 'open',
            })
        cls.Entry = cls.env['vas.closing.entry']

    def _acc(self, code):
        return self.env.ref('connecta_vas.vas_account_tt133_%s' % code)

    def _post_pair(self, day, debit, credit, amount, name='PO',
                   currency=None, amount_currency=None):
        vals_d = {
            'account_id': debit.id, 'name': name,
            'debit': amount, 'credit': 0.0,
        }
        vals_c = {
            'account_id': credit.id, 'name': name,
            'debit': 0.0, 'credit': amount,
        }
        if currency and amount_currency is not None:
            vals_d.update({
                'currency_id': currency.id,
                'amount_currency': amount_currency,
            })
            vals_c.update({
                'currency_id': currency.id,
                'amount_currency': -amount_currency,
            })
        move = self.env['vas.move'].create({
            'date': day,
            'journal_id': self.journal.id,
            'regime_id': self.regime.id,
            'company_id': self.company.id,
            'ref': name,
            'move_kind': 'manual',
            'line_ids': [(0, 0, vals_d), (0, 0, vals_c)],
        })
        move.action_post()
        return move

    def _set_usd_rate(self, day, rate):
        Rate = self.env['res.currency.rate']
        existing = Rate.search([
            ('currency_id', '=', self.usd.id),
            ('name', '=', day),
            ('company_id', 'in', (False, self.company.id)),
        ], limit=1)
        if existing:
            existing.write({'rate': 1.0 / rate, 'company_id': self.company.id})
        else:
            Rate.create({
                'currency_id': self.usd.id,
                'name': day,
                'rate': 1.0 / rate,
                'company_id': self.company.id,
            })

    def test_01_cit_same_click_closes_821_and_b02_51(self):
        self._post_pair('2097-12-05', self._acc('156'), self._acc('111'), 200_000, 'NH')
        self._post_pair('2097-12-10', self._acc('111'), self._acc('511'), 500_000, 'DT')
        self._post_pair('2097-12-11', self._acc('632'), self._acc('156'), 200_000, 'GV')
        entry = self.Entry.create({
            'company_id': self.company.id,
            'date_from': '2097-01-01',
            'date_to': '2097-12-31',
            'run_kqkd': True,
            'run_cit': True,
            'cit_amount': 30_000.0,
            'cit_nature': 'provisional',
        })
        self.assertTrue(entry.is_year_end)
        entry.action_fetch_data()
        self.assertTrue(any(
            l.account_debit_id.code == '821' and l.account_credit_id.code == '3334'
            for l in entry.line_ids
        ))
        self.assertTrue(any(
            {'821', '911'} <= {l.account_debit_id.code, l.account_credit_id.code}
            for l in entry.line_ids
        ))
        amt_4212 = next(
            l.amount for l in entry.line_ids
            if {l.account_debit_id.code, l.account_credit_id.code} == {'911', '4212'}
        )
        self.assertEqual(float_compare(amt_4212, 270_000.0, 2), 0, amt_4212)
        entry.action_post()
        Rule = self.env['vas.closing.rule']
        _a821, s821 = Rule.compute_closing_amount(
            self._acc('821'), self.company, '2097-01-01', '2097-12-31', 'both',
        )
        self.assertFalse(s821, '821 phải về 0 sau KC')
        p01 = self.env['vas.period'].search([
            ('fiscalyear_id', '=', self.fy.id), ('date_start', '=', '2097-01-01'),
        ], limit=1)
        p12 = self.env['vas.period'].search([
            ('fiscalyear_id', '=', self.fy.id), ('date_start', '=', '2097-12-01'),
        ], limit=1)
        b02 = self.env['vas.report.snapshot'].generate_b02(
            self.company, p01, p12, hide_reversed=True,
        )
        by = {l.code: l.amount_closing for l in b02.line_ids}
        self.assertEqual(float_compare(by['51'], -30_000.0, 2), 0, by['51'])
        self.assertEqual(float_compare(by['60'], 270_000.0, 2), 0, by['60'])
        self.assertEqual(float_compare(b02.check_60_4212_diff, 0.0, 2), 0)
        self.assertNotIn('chưa kết chuyển', (b02.warning_text or '').lower())

    def test_02_fx_same_click_515_to_911_and_4212(self):
        self._set_usd_rate('2097-06-01', 25_000.0)
        self._set_usd_rate('2097-06-30', 26_000.0)
        self._post_pair(
            '2097-06-05', self._acc('1122'), self._acc('511'), 2_500_000,
            'USD', currency=self.usd, amount_currency=100.0,
        )
        entry = self.Entry.create({
            'company_id': self.company.id,
            'date_from': '2097-06-01',
            'date_to': '2097-06-30',
            'run_kqkd': True,
            'run_fx': True,
        })
        entry.action_fetch_data()
        self.assertTrue(any(
            l.account_debit_id.code == '413' and l.account_credit_id.code == '515'
            for l in entry.line_ids
        ))
        self.assertTrue(any(
            l.account_debit_id.code == '515' and l.account_credit_id.code == '911'
            for l in entry.line_ids
        ))
        amt = next(
            l.amount for l in entry.line_ids
            if l.account_debit_id.code == '911' and l.account_credit_id.code == '4212'
        )
        self.assertEqual(float_compare(amt, 2_600_000.0, 2), 0, amt)

    def test_03_c01_same_click_expense_to_911(self):
        asset = self.env['vas.asset'].create({
            'name': 'PO prepaid',
            'code': 'PO-PP-01',
            'company_id': self.company.id,
            'regime_id': self.regime.id,
            'asset_type': 'prepaid',
            'asset_kind': 'prepaid_service',
            'original_value': 1_200_000,
            'date_start': date(2097, 6, 1),
            'method': 'straight_line',
            'duration_months': 2,
            'prorata': False,
            'account_gross_id': self._acc('242').id,
            'account_accum_id': self._acc('242').id,
            'account_expense_id': self._acc('6422').id,
            'journal_id': self.journal.id,
            'source_mode': 'manual',
        })
        asset.action_confirm()
        period = self.env['vas.period'].search([
            ('fiscalyear_id', '=', self.fy.id), ('date_start', '=', '2097-06-01'),
        ], limit=1)
        planned = asset.line_ids.filtered(
            lambda l: l.state == 'planned' and l.period_id == period
        )
        self.assertTrue(planned)
        expected = planned[0].amount
        self._post_pair('2097-06-10', self._acc('111'), self._acc('511'), 900_000, 'DT')
        entry = self.Entry.create({
            'company_id': self.company.id,
            'date_from': '2097-06-01',
            'date_to': '2097-06-30',
            'run_kqkd': True,
            'run_prepaid': True,
        })
        entry.action_fetch_data()
        self.assertTrue(any(
            l.account_debit_id.code == '6422' and l.account_credit_id.code == '242'
            for l in entry.line_ids
        ))
        self.assertTrue(any(
            l.account_debit_id.code == '911' and l.account_credit_id.code == '6422'
            for l in entry.line_ids
        ))
        close_6422 = sum(
            l.amount for l in entry.line_ids
            if l.account_debit_id.code == '911' and l.account_credit_id.code == '6422'
        )
        self.assertEqual(float_compare(close_6422, expected, 2), 0, close_6422)

    def test_04_year_start_same_click_sees_4212_from_kqkd(self):
        self._post_pair('2098-01-10', self._acc('111'), self._acc('511'), 400_000, 'DT')
        entry = self.Entry.create({
            'company_id': self.company.id,
            'date_from': '2098-01-01',
            'date_to': '2098-01-31',
            'run_kqkd': True,
            'run_year_start': True,
        })
        entry.action_fetch_data()
        self.assertTrue(any(
            l.account_debit_id.code == '911' and l.account_credit_id.code == '4212'
            for l in entry.line_ids
        ))
        self.assertTrue(any(
            l.account_debit_id.code == '4212' and l.account_credit_id.code == '4211'
            for l in entry.line_ids
        ))
        amt = next(
            l.amount for l in entry.line_ids
            if l.account_debit_id.code == '4212' and l.account_credit_id.code == '4211'
        )
        self.assertEqual(float_compare(amt, 400_000.0, 2), 0, amt)

    def test_05_balance_door_blocks_direct_read_during_fetch(self):
        entry = self.Entry.create({
            'company_id': self.company.id,
            'date_from': '2097-01-01',
            'date_to': '2097-12-31',
            'run_kqkd': True,
        })
        entry_ctx = entry.with_context(
            vas_closing_fetch_active=True,
            vas_closing_proposal_pending=[],
        )
        with self.assertRaises(UserError) as err:
            entry_ctx._ending_side_balance(self._acc('511'), 'credit')
        self.assertIn('cửa chung', err.exception.args[0].lower())
        with self.assertRaises(UserError):
            entry_ctx._account_net_balance(self._acc('511'))

    def test_06_w11_bctc_amounts_unchanged(self):
        self.env['res.company']._vas_w11_ensure_bctc_demo()
        company = self.env['res.company'].search(
            [('name', '=', 'W11-Thử BCTC')], limit=1,
        )
        self.assertTrue(company)
        p01 = self.env['vas.period'].search([
            ('fiscalyear_id.company_id', '=', company.id),
            ('date_start', '=', '2026-01-01'),
        ], limit=1)
        p12 = self.env['vas.period'].search([
            ('fiscalyear_id.company_id', '=', company.id),
            ('date_start', '=', '2026-12-01'),
        ], limit=1)
        b01 = self.env['vas.report.snapshot'].generate_b01a(
            company, p01, p12, hide_reversed=True,
        )
        from odoo.addons.connecta_vas.models.res_company import (
            W11_BCTC_EXPECT_BS,
            W11_BCTC_EXPECT_PNL60,
        )
        by1 = {l.code: l.amount_closing for l in b01.line_ids}
        self.assertEqual(float_compare(by1['200'], W11_BCTC_EXPECT_BS, 2), 0, by1['200'])
        self.assertEqual(float_compare(by1['500'], W11_BCTC_EXPECT_BS, 2), 0, by1['500'])
        b02 = self.env['vas.report.snapshot'].generate_b02(
            company, p01, p12, hide_reversed=True,
        )
        by2 = {l.code: l.amount_closing for l in b02.line_ids}
        self.assertEqual(float_compare(by2['60'], W11_BCTC_EXPECT_PNL60, 2), 0, by2['60'])
        self.assertEqual(float_compare(by2['51'], -W11_BCTC_CIT_AMOUNT, 2), 0)
        self.assertEqual(float_compare(b02.check_60_4212_diff, 0.0, 2), 0)
        self.assertEqual(float_compare(b02.check_60_b01a_417_diff, 0.0, 2), 0)
        self.assertIn('800000', (b02.warning_text or '').replace(',', ''))
        self.assertNotIn('Chỉ tiêu 51', b02.warning_text or '')
