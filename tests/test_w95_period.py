# -*- coding: utf-8 -*-
"""W9.5 — hàng rào khóa sổ theo NGÀY; trải kỳ theo quy tắc niên độ."""
import logging
from datetime import date

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged, TransactionCase

_logger = logging.getLogger(__name__)


@tagged('post_install', '-at_install', 'connecta_vas_w95')
class TestW95PeriodFence(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.country_id = cls.env.ref('base.vn')
        vnd = cls.env.ref('base.VND')
        if cls.company.currency_id != vnd:
            cls.company.currency_id = vnd
        if not cls.company.vas_regime_id:
            cls.company.vas_regime_id = cls.env.ref('connecta_vas.vas_regime_tt133')
        # Quy tắc niên độ Odoo: mặc định 31/12 (năm dương lịch)
        cls.company.fiscalyear_last_day = 31
        cls.company.fiscalyear_last_month = '12'
        # Cutoff phải ≤ mọi ngày bút toán trong file (2075, 2097, 2055…).
        # Đỏ vì thiếu/sai mốc — sửa fixture, không nới guard.
        cls.company.vas_start_date = '2000-01-01'
        cls.fy = cls.env['vas.fiscalyear'].create({
            'name': 'W95-2099',
            'date_from': '2099-01-01',
            'date_to': '2099-12-31',
            'company_id': cls.company.id,
            'state': 'open',
        })
        cls.period_mar = cls.fy.period_ids.filtered(
            lambda p: p.date_start.month == 3 and p.date_start.year == 2099)[:1]
        cls.period_jun = cls.fy.period_ids.filtered(
            lambda p: p.date_start.month == 6 and p.date_start.year == 2099)[:1]
        if not cls.period_mar or not cls.period_jun:
            raise AssertionError(
                'FY W95-2099 missing Mar/Jun periods: %s'
                % cls.fy.period_ids.mapped('name')
            )
        cls.journal = cls.env['vas.journal'].search([
            ('company_id', '=', cls.company.id),
            ('code', '=', 'THU'),
        ], limit=1)
        cls.acc_111 = cls.env['vas.account'].search([
            ('regime_id', '=', cls.company.vas_regime_id.id),
            ('code', '=', '111'),
        ], limit=1)
        cls.acc_1111 = cls.env['vas.account'].search([
            ('regime_id', '=', cls.company.vas_regime_id.id),
            ('code', '=', '1111'),
        ], limit=1) or cls.acc_111
        cls.acc_331 = cls.env['vas.account'].search([
            ('regime_id', '=', cls.company.vas_regime_id.id),
            ('code', '=', '331'),
        ], limit=1)

    def _balanced_lines(self, amount=1000.0):
        from odoo import Command
        debit_acc = self.acc_1111 or self.acc_111
        credit_acc = self.acc_331 or self.acc_111
        return [
            Command.create({
                'sequence': 10, 'account_id': debit_acc.id,
                'name': 'W95', 'debit': amount, 'credit': 0.0,
                'currency_id': self.company.currency_id.id,
            }),
            Command.create({
                'sequence': 20, 'account_id': credit_acc.id,
                'name': 'W95', 'debit': 0.0, 'credit': amount,
                'currency_id': self.company.currency_id.id,
            }),
        ]

    def _make_draft(self, day, amount=1000.0, **ctx):
        return self.env['vas.move'].with_context(**ctx).create({
            'date': day,
            'journal_id': self.journal.id,
            'company_id': self.company.id,
            'regime_id': self.company.vas_regime_id.id,
            'line_ids': self._balanced_lines(amount),
        })

    def test_helper_three_statuses(self):
        Period = self.env['vas.period']
        self.assertEqual(
            Period._coverage_status(self.company, date(2099, 3, 15)), 'open')
        self.period_mar.state = 'closed'
        self.assertEqual(
            Period._coverage_status(self.company, date(2099, 3, 15)), 'closed')
        # Có quy tắc → ngày chưa có bản ghi kỳ vẫn tự trải → open
        self.assertEqual(
            Period._coverage_status(self.company, date(2098, 1, 1)), 'open')
        # Không quy tắc + chưa có bản ghi → missing
        day_bare = date(2077, 8, 15)
        self.assertFalse(Period._period_covering(self.company, day_bare))
        self.assertEqual(
            Period.with_context(vas_force_no_fiscal_rule=True)._coverage_status(
                self.company, day_bare),
            'missing',
        )
        self.period_mar.state = 'open'

    def test_post_missing_blocked_draft_allowed(self):
        """missing = chưa khai quy tắc: draft OK; post bị chặn."""
        day = date(2076, 5, 15)
        draft = self._make_draft(day, vas_force_no_fiscal_rule=True)
        self.assertEqual(draft.state, 'draft')
        self.assertTrue(draft.period_missing_pending)
        with self.assertRaises(UserError):
            draft.with_context(vas_force_no_fiscal_rule=True).action_post()
        self.assertEqual(draft.state, 'draft')

    def test_auto_materialize_allows_post(self):
        """Có quy tắc → ngày chưa có kỳ vẫn post được (tự trải)."""
        day = date(2075, 7, 20)
        Period = self.env['vas.period']
        self.assertFalse(Period._period_covering(self.company, day))
        draft = self._make_draft(day)
        self.assertFalse(draft.period_missing_pending)
        draft.action_post()
        self.assertEqual(draft.state, 'posted')
        self.assertTrue(Period._period_covering(self.company, day))

    def test_closed_blocks_even_when_period_id_false(self):
        """Ca trước đây LỌT: mồ côi + kỳ khóa → vẫn chặn sửa dòng."""
        day = date(2099, 6, 10)
        move = self._make_draft(day)
        move.action_post()
        self.period_jun.state = 'closed'
        move.with_context(
            vas_allow_posted_write=True, vas_skip_period_check=True,
        ).write({'period_id': False})
        self.assertFalse(move.period_id)
        line = move.line_ids[:1]
        with self.assertRaises(UserError):
            line.with_context(vas_allow_posted_write=True).write({'name': 'x'})
        with self.assertRaises(UserError):
            line.unlink()
        self.period_jun.state = 'open'

    def test_close_period_assigns_orphans(self):
        day = date(2099, 3, 20)
        move = self._make_draft(day)
        move.action_post()
        move.with_context(
            vas_allow_posted_write=True, vas_skip_period_check=True,
        ).write({'period_id': False})
        self.assertFalse(move.period_id)
        self.period_mar.state = 'closed'
        self.assertEqual(move.period_id, self.period_mar)
        self.period_mar.state = 'open'

    def test_sync_closed_flags_not_missing_with_rule(self):
        """Có quy tắc: thiếu bản ghi kỳ → tự post; kỳ khóa → cờ pending."""
        Sync = self.env['vas.sync']
        day = date(2097, 4, 15)
        move = self._make_draft(day)
        posted = Sync._post_or_flag_period_missing(move)
        self.assertTrue(posted)
        self.assertEqual(move.state, 'posted')
        self.assertFalse(move.period_missing_pending)
        # tạo nháp khi kỳ còn mở, rồi khóa → flag (không tạo được nháp trong kỳ khóa)
        move2 = self._make_draft(day)
        period = self.env['vas.period']._period_covering(self.company, day)
        period.state = 'closed'
        empty = Sync._post_or_flag_period_missing(move2)
        self.assertFalse(empty)
        self.assertEqual(move2.state, 'draft')
        self.assertTrue(move2.period_missing_pending)
        period.state = 'open'
        stats = Sync._retry_period_missing_drafts(self.company, '2097-01-01', '2097-12-31')
        self.assertGreaterEqual(stats['posted'], 1)
        self.assertEqual(move2.state, 'posted')

    def test_migration_assign_orphans(self):
        day = date(2099, 3, 5)
        move = self._make_draft(day)
        move.action_post()
        move.with_context(
            vas_allow_posted_write=True, vas_skip_period_check=True,
        ).write({'period_id': False})
        n = self.fy.period_ids._assign_orphan_moves()
        self.assertGreaterEqual(n, 1)
        self.assertEqual(move.period_id, self.period_mar)

    def test_opening_reopen_missing_blocked(self):
        Period = self.env['vas.period']
        day = date(2074, 1, 1)
        self.assertEqual(
            Period.with_context(vas_force_no_fiscal_rule=True)._coverage_status(
                self.company, day),
            'missing',
        )
        with self.assertRaises(UserError):
            Period.with_context(vas_force_no_fiscal_rule=True)._assert_date_writable(
                self.company, day, doc_name='SDK', allow_missing=False,
            )

    def test_overlap_constraint(self):
        """§8.7: chống chồng THỰC — giao khoảng bất kỳ; kề nhau cho qua."""
        Period = self.env['vas.period']
        fy = self.env['vas.fiscalyear'].create({
            'name': 'W95-overlap-2088',
            'date_from': '2088-01-01',
            'date_to': '2088-12-31',
            'company_id': self.company.id,
            'state': 'open',
        })
        fy.period_ids.unlink()
        a = Period.create({
            'name': 'A-01/2088',
            'date_start': '2088-01-01',
            'date_end': '2088-01-31',
            'fiscalyear_id': fy.id,
            'state': 'open',
        })
        with self.assertRaises(ValidationError):
            with self.env.cr.savepoint():
                Period.create({
                    'name': 'B-partial',
                    'date_start': '2088-01-15',
                    'date_end': '2088-02-15',
                    'fiscalyear_id': fy.id,
                    'state': 'open',
                })
        with self.assertRaises(ValidationError):
            with self.env.cr.savepoint():
                Period.create({
                    'name': 'Big-contain',
                    'date_start': '2087-12-01',
                    'date_end': '2088-02-28',
                    'fiscalyear_id': fy.id,
                    'state': 'open',
                })
        exact = Period.create({
            'name': 'A-exact-dup',
            'date_start': '2088-01-01',
            'date_end': '2088-01-31',
            'fiscalyear_id': fy.id,
            'state': 'open',
        })
        self.assertEqual(exact.id, a.id)
        adj = Period.create({
            'name': 'C-adjacent',
            'date_start': '2088-02-01',
            'date_end': '2088-02-29',
            'fiscalyear_id': fy.id,
            'state': 'open',
        })
        self.assertTrue(adj.id)
        self.assertEqual(adj.date_start, date(2088, 2, 1))

    def test_cancel_closed_by_date_flags_pending(self):
        day = date(2099, 6, 15)
        move = self._make_draft(day)
        move.action_post()
        move.with_context(
            vas_allow_posted_write=True, vas_skip_period_check=True,
        ).write({'period_id': False})
        self.period_jun.state = 'closed'
        Period = self.env['vas.period']
        self.assertTrue(Period._date_in_closed_period(self.company, day))
        move.with_context(
            vas_allow_posted_write=True, vas_skip_period_check=True,
        ).write({'source_cancel_pending': True})
        self.assertTrue(move.source_cancel_pending)
        self.assertEqual(move.state, 'posted')
        self.period_jun.state = 'open'

    def test_asset_loan_full_schedule_auto_periods(self):
        """(b)(c) Asset 10y / loan dài → đủ lịch nhờ tự trải kỳ."""
        regime = self.company.vas_regime_id
        Acc = self.env['vas.account']
        acc = {
            c: Acc.search([('regime_id', '=', regime.id), ('code', '=', c)], limit=1)
            for c in ('2111', '2141', '6422', '3411', '635', '335')
        }
        journal = self.env['vas.journal'].search([
            ('company_id', '=', self.company.id), ('code', '=', 'TH'),
        ], limit=1)
        # Chỉ có FY 2055 trước confirm
        fy = self.env['vas.fiscalyear'].create({
            'name': 'W95-only-2055',
            'date_from': '2055-01-01',
            'date_to': '2055-12-31',
            'company_id': self.company.id,
            'state': 'open',
        })
        self.assertEqual(len(fy.period_ids), 12)
        asset = self.env['vas.asset'].create({
            'code': 'W95-A10',
            'name': 'TSCĐ 10y auto',
            'company_id': self.company.id,
            'regime_id': regime.id,
            'asset_type': 'tscd',
            'original_value': 120_000_000,
            'salvage_value': 0,
            'date_start': '2055-03-15',
            'useful_life_years': 10,
            'method': 'straight_line',
            'prorata': True,
            'account_gross_id': acc['2111'].id,
            'account_accum_id': acc['2141'].id,
            'account_expense_id': acc['6422'].id,
            'journal_id': journal.id if journal else False,
        })
        asset.action_confirm()
        self.assertEqual(asset.state, 'running')
        self.assertEqual(len(asset.line_ids), 120)
        starts = asset.line_ids.mapped('period_id.date_start')
        print(
            f'\n=== W95 asset lines={len(asset.line_ids)} '
            f'first={min(starts)} last={max(starts)} ===\n'
        )

        loan = self.env['vas.loan'].create({
            'name': 'Vay 10y auto',
            'code': 'W95-L10',
            'company_id': self.company.id,
            'regime_id': regime.id,
            'date_start': '2055-03-01',
            'date_end': '2065-02-28',
            'principal': 100_000_000,
            'interest_rate': 0.12,
            'account_loan_id': acc['3411'].id,
            'account_interest_expense_id': acc['635'].id,
            'account_interest_payable_id': acc['335'].id,
            'journal_id': journal.id if journal else False,
        })
        loan.action_confirm()
        self.assertEqual(loan.state, 'running')
        self.assertGreaterEqual(len(loan.line_ids), 100)
        years = {d.year for d in loan.line_ids.mapped('period_id.date_start')}
        self.assertIn(2055, years)
        self.assertIn(2064, years)
        print(f'\n=== W95 loan lines={len(loan.line_ids)} years={sorted(years)} ===\n')

    def test_asset_no_rule_rolls_back_clean(self):
        """Không quy tắc → không line, state draft (hoàn tác trọn)."""
        regime = self.company.vas_regime_id
        Acc = self.env['vas.account']
        acc = {
            c: Acc.search([('regime_id', '=', regime.id), ('code', '=', c)], limit=1)
            for c in ('2111', '2141', '6422')
        }
        asset = self.env['vas.asset'].with_context(
            vas_force_no_fiscal_rule=True,
        ).create({
            'code': 'W95-A-NORULE',
            'name': 'TSCĐ no rule',
            'company_id': self.company.id,
            'regime_id': regime.id,
            'asset_type': 'tscd',
            'original_value': 120_000_000,
            'date_start': '2054-03-15',
            'useful_life_years': 10,
            'method': 'straight_line',
            'prorata': True,
            'account_gross_id': acc['2111'].id,
            'account_accum_id': acc['2141'].id,
            'account_expense_id': acc['6422'].id,
        })
        with self.assertRaises(UserError):
            asset.with_context(vas_force_no_fiscal_rule=True).action_confirm()
        asset.invalidate_recordset()
        self.assertEqual(asset.state, 'draft')
        self.assertEqual(len(asset.line_ids), 0)
