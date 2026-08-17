# -*- coding: utf-8 -*-
"""W8 — vas.asset: 3 phương pháp TT45 + pass sinh kỳ + CCDC + cancel."""
from datetime import date

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged, TransactionCase
from odoo.tools.float_utils import float_compare

from odoo.addons.connecta_vas.models.vas_asset_schedule import (
    build_straight_line,
    build_declining,
    build_prepaid_equal,
    build_units_period_amount,
    units_rate,
)


@tagged('connecta_vas', 'connecta_vas_w8')
class TestW8Asset(TransactionCase):

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
        cls.acc = {
            code: cls.env['vas.account'].search([
                ('regime_id', '=', cls.regime.id), ('code', '=', code),
            ], limit=1)
            for code in (
                '2111', '2141', '214', '153', '242', '6422', '3533', '154', '632',
            )
        }
        # Fallback create if chart not loaded in some paths
        for code, name in (
            ('2111', 'TSCĐ HH'), ('2141', 'HM TSCĐ'), ('214', 'HM'),
            ('153', 'CCDC'), ('242', 'CP trả trước'), ('6422', 'CP QLDN'),
            ('3533', 'Quỹ phúc lợi'), ('154', 'CPSX dở dang'), ('632', 'Giá vốn'),
        ):
            if not cls.acc.get(code):
                atype = 'asset' if code[0] in '12' else 'expense'
                cls.acc[code] = cls.env['vas.account'].create({
                    'code': code, 'name': name, 'regime_id': cls.regime.id,
                    'account_type': atype,
                    'ending_balance_policy': 'debit' if atype == 'asset' else 'none',
                })
        cls.journal = cls.env['vas.journal'].search([
            ('company_id', '=', cls.company.id), ('code', '=', 'TH'),
        ], limit=1)
        if not cls.journal:
            cls.journal = cls.env['vas.journal'].create({
                'code': 'TH', 'name': 'Tổng hợp', 'type': 'general',
                'company_id': cls.company.id,
            })
        # §8.1: asset không tự đẻ kỳ — cần FY phủ cả lịch KH (10 năm từ 2099)
        for year in range(2099, 2110):
            name = 'W8-%s' % year
            fy = cls.env['vas.fiscalyear'].search([
                ('company_id', '=', cls.company.id),
                ('name', '=', name),
            ], limit=1)
            if not fy:
                cls.env['vas.fiscalyear'].create({
                    'name': name,
                    'date_from': '%s-01-01' % year,
                    'date_to': '%s-12-31' % year,
                    'company_id': cls.company.id,
                    'state': 'open',
                })
        cls.fy = cls.env['vas.fiscalyear'].search([
            ('company_id', '=', cls.company.id),
            ('name', '=', 'W8-2099'),
        ], limit=1)

    def _acc(self, code):
        return self.acc[code]

    # ------------------------------------------------------------------
    # Pure builders (TT45 numbers)
    # ------------------------------------------------------------------

    def test_straight_line_tt45_mid_month(self):
        """NG 120tr, 10 năm, 15/03 → T3=548.387; T4=1.000.000; tổng=120tr."""
        lines = build_straight_line(
            120_000_000, 10, date(2099, 3, 15), prorata=True,
        )
        self.assertEqual(len(lines), 120)
        self.assertEqual(lines[0]['amount'], 548_387.0)
        self.assertEqual(lines[1]['amount'], 1_000_000.0)
        self.assertEqual(lines[2]['amount'], 1_000_000.0)
        total = sum(l['amount'] for l in lines)
        self.assertEqual(total, 120_000_000.0)
        self.assertEqual(lines[-1]['amount'], 120_000_000.0 - sum(
            l['amount'] for l in lines[:-1]
        ))

    def test_declining_tt45_example(self):
        """NG 50tr, 5 năm → năm 20/12/7.2/5.4/5.4 tr; tổng=50tr."""
        lines = build_declining(50_000_000, 5, date(2013, 1, 1), prorata=True)
        self.assertEqual(len(lines), 60)
        years = []
        for i in range(5):
            chunk = lines[i * 12:(i + 1) * 12]
            years.append(sum(l['amount'] for l in chunk))
        self.assertEqual(years[0], 20_000_000.0)
        self.assertEqual(years[1], 12_000_000.0)
        self.assertEqual(years[2], 7_200_000.0)
        self.assertEqual(years[3], 5_400_000.0)
        self.assertEqual(years[4], 5_400_000.0)
        self.assertEqual(sum(years), 50_000_000.0)

    def test_units_tt45_example(self):
        """Máy ủi 450tr / 2.400.000 m³ = 187,5; năm = 35.437.500."""
        rate = units_rate(450_000_000, 2_400_000)
        self.assertEqual(rate, 187.5)
        qtys = [
            14000, 15000, 18000, 16000, 15000, 14000,
            15000, 14000, 16000, 16000, 18000, 18000,
        ]
        expected = [
            2_625_000, 2_812_500, 3_375_000, 3_000_000, 2_812_500, 2_625_000,
            2_812_500, 2_625_000, 3_000_000, 3_000_000, 3_375_000, 3_375_000,
        ]
        residual = 450_000_000.0
        total = 0.0
        for qty, exp in zip(qtys, expected):
            amt = build_units_period_amount(
                450_000_000, 2_400_000, qty, residual, is_last=False,
            )
            self.assertEqual(amt, float(exp))
            residual -= amt
            total += amt
        self.assertEqual(total, 35_437_500.0)

    def test_prepaid_equal_no_prorata(self):
        lines = build_prepaid_equal(12_000_000, 12, date(2099, 3, 15))
        self.assertEqual(len(lines), 12)
        self.assertEqual(lines[0]['amount'], 1_000_000.0)
        self.assertEqual(sum(l['amount'] for l in lines), 12_000_000.0)

    # ------------------------------------------------------------------
    # Model + pass
    # ------------------------------------------------------------------

    def _make_tscd(self, **kwargs):
        vals = {
            'code': kwargs.pop('code', 'TS-%s' % fields.Datetime.now()),
            'name': kwargs.pop('name', 'TSCĐ test'),
            'company_id': self.company.id,
            'regime_id': self.regime.id,
            'asset_type': 'tscd',
            'original_value': 120_000_000,
            'date_start': date(2099, 3, 15),
            'method': 'straight_line',
            'useful_life_years': 10,
            'duration_months': 120,
            'prorata': True,
            'account_gross_id': self._acc('2111').id,
            'account_accum_id': self._acc('2141').id,
            'account_expense_id': self._acc('6422').id,
            'journal_id': self.journal.id,
            'source_mode': 'manual',
        }
        vals.update(kwargs)
        asset = self.env['vas.asset'].create(vals)
        asset.action_confirm()
        return asset

    def test_pass_idempotent_and_workbook_a06(self):
        asset = self._make_tscd(code='A06-SL')
        self.assertEqual(asset.line_ids[0].amount, 548_387.0)
        period = asset.line_ids[0].period_id
        stats1 = self.env['vas.asset'].generate_asset_entries(self.company, period)
        self.assertEqual(stats1['created'], 1)
        move = asset.line_ids[0].move_id
        self.assertTrue(move)
        self.assertEqual(move.move_kind, 'depreciation')
        debits = {l.account_id.code: l.debit for l in move.line_ids if l.debit}
        credits = {l.account_id.code: l.credit for l in move.line_ids if l.credit}
        self.assertIn('6422', debits)
        self.assertTrue(any(c.startswith('214') for c in credits))
        stats2 = self.env['vas.asset'].generate_asset_entries(self.company, period)
        self.assertEqual(stats2['created'], 0)
        self.assertEqual(
            self.env['vas.move'].search_count([
                ('source_model', '=', 'vas.asset.line'),
                ('source_res_id', '=', asset.line_ids[0].id),
                ('move_kind', '=', 'depreciation'),
                ('is_reversal', '=', False),
                ('state', 'not in', ('reversed', 'cancelled')),
            ]),
            1,
        )

    def test_a07_welfare_3533(self):
        asset = self._make_tscd(code='A07-WF', is_welfare=True, name='TSCĐ phúc lợi')
        period = asset.line_ids[0].period_id
        self.env['vas.asset'].generate_asset_entries(self.company, period)
        move = asset.line_ids[0].move_id
        self.assertIn('3533', move.line_ids.filtered('debit').mapped('account_id.code'))

    def test_closed_period_refuse(self):
        asset = self._make_tscd(code='LOCK-1')
        period = asset.line_ids[0].period_id
        # Bypass HARD gate chỉ để dựng kỳ khóa; pass vẫn phải refuse.
        period.with_context(vas_skip_asset_lock_check=True).write({'state': 'closed'})
        with self.assertRaises(UserError):
            self.env['vas.asset'].generate_asset_entries(self.company, period)

    def test_hard_block_close_with_planned(self):
        asset = self._make_tscd(code='LOCK-2')
        period = asset.line_ids[0].period_id
        period.state = 'open'
        with self.assertRaises(UserError):
            period.write({'state': 'closed'})

    def test_recompute_keeps_posted(self):
        asset = self._make_tscd(code='RECOMP')
        period = asset.line_ids[0].period_id
        self.env['vas.asset'].generate_asset_entries(self.company, period)
        posted_amt = asset.line_ids[0].amount
        posted_id = asset.line_ids[0].id
        asset.action_recompute_schedule()
        posted = asset.line_ids.filtered(lambda l: l.id == posted_id)
        self.assertEqual(posted.state, 'posted')
        self.assertEqual(posted.amount, posted_amt)
        self.assertTrue(asset.line_ids.filtered(lambda l: l.state == 'planned'))

    def test_ccdc_once_and_multi(self):
        card = self.env['vas.asset'].create({
            'code': 'CCDC-1',
            'name': 'Dụng cụ',
            'company_id': self.company.id,
            'regime_id': self.regime.id,
            'asset_type': 'prepaid',
            'asset_kind': 'ccdc',
            'original_value': 5_000_000,
            'date_start': date(2099, 4, 1),
            'method': 'straight_line',
            'duration_months': 6,
            'prorata': False,
            'account_gross_id': self._acc('153').id,
            'account_accum_id': self._acc('242').id,
            'account_expense_id': self._acc('6422').id,
            'journal_id': self.journal.id,
        })
        move_once = card.copy({'code': 'CCDC-ONCE'}).action_issue_ccdc_once()
        self.assertEqual(move_once.move_kind, 'ccdc_issue')
        codes = set(move_once.line_ids.mapped('account_id.code'))
        self.assertIn('153', codes)
        self.assertIn('6422', codes)

        multi = card.copy({'code': 'CCDC-MULTI'})
        move_multi = multi.action_issue_ccdc_multi(duration_months=6)
        self.assertEqual(move_multi.move_kind, 'ccdc_issue')
        self.assertEqual(multi.asset_type, 'prepaid')
        self.assertEqual(multi.state, 'running')
        self.assertEqual(len(multi.line_ids), 6)
        self.assertEqual(sum(multi.line_ids.mapped('amount')), 5_000_000.0)
        self.assertEqual(multi.line_ids[0].amount, 833_333.0)

    def test_cancel_skips_planned_reverses_open(self):
        asset = self._make_tscd(code='CANCEL-1')
        period = asset.line_ids[0].period_id
        self.env['vas.asset'].generate_asset_entries(self.company, period)
        move = asset.line_ids[0].move_id
        asset.action_cancel()
        self.assertEqual(asset.state, 'cancelled')
        self.assertTrue(all(
            l.state == 'skipped' or l.state == 'posted'
            for l in asset.line_ids
        ))
        # posted line reversed or skipped
        move.invalidate_recordset()
        self.assertTrue(
            move.state == 'reversed'
            or asset.line_ids[0].state == 'skipped'
            or move.source_cancel_pending
        )

    def test_threshold_and_pl1_warnings(self):
        asset = self._make_tscd(
            code='WARN-1',
            original_value=10_000_000,
            useful_life_years=10,
            duration_months=120,
        )
        self.assertTrue(asset.warning_note)
        self.assertIn('30.000.000', asset.warning_note)

    def test_declining_on_asset_model(self):
        asset = self._make_tscd(
            code='DECL-1',
            original_value=50_000_000,
            date_start=date(2099, 1, 1),
            method='declining',
            useful_life_years=5,
            duration_months=60,
        )
        lines = asset.line_ids.sorted('sequence')
        y1 = sum(lines[:12].mapped('amount'))
        self.assertEqual(y1, 20_000_000.0)
        self.assertEqual(sum(lines.mapped('amount')), 50_000_000.0)

    def test_units_on_asset_model(self):
        asset = self.env['vas.asset'].create({
            'code': 'UNIT-1',
            'name': 'Máy ủi',
            'company_id': self.company.id,
            'regime_id': self.regime.id,
            'asset_type': 'tscd',
            'original_value': 450_000_000,
            'date_start': date(2099, 1, 1),
            'method': 'units',
            'units_total': 2_400_000,
            'useful_life_years': 10,
            'duration_months': 120,
            'account_gross_id': self._acc('2111').id,
            'account_accum_id': self._acc('2141').id,
            'account_expense_id': self._acc('632').id,
            'journal_id': self.journal.id,
        })
        asset.action_confirm()
        self.assertFalse(asset.line_ids)
        fy = self.env['vas.fiscalyear'].create({
            'name': '2099-U',
            'date_from': '2099-01-01',
            'date_to': '2099-12-31',
            'state': 'open',
            'company_id': self.company.id,
        })
        period = self.env['vas.period'].create({
            'name': '01/2099-U',
            'date_start': '2099-01-01',
            'date_end': '2099-01-31',
            'fiscalyear_id': fy.id,
            'state': 'open',
        })
        asset.action_set_units_qty(period, 14000)
        line = asset.line_ids[:1]
        self.assertEqual(line.amount, 2_625_000.0)
        stats = self.env['vas.asset'].generate_asset_entries(self.company, period)
        self.assertEqual(stats['created'], 1)
        self.assertEqual(line.move_id.line_ids.filtered('debit').account_id.code, '632')
