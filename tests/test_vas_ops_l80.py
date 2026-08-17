# -*- coding: utf-8 -*-
"""L80 — ops khấu hao/vay/thuế + nút thông minh số dư TK."""
from odoo import fields
from odoo.tests import tagged, TransactionCase
from odoo.tools.float_utils import float_compare


@tagged('post_install', '-at_install', 'connecta_vas', 'connecta_vas_l80')
class TestVasOpsL80(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.regime = cls.env.ref('connecta_vas.vas_regime_tt133')
        vnd = cls.env.ref('base.VND')
        today = fields.Date.context_today(cls.env.user)
        cls.company = cls.env['res.company'].create({
            'name': 'L80 Ops Co',
            'currency_id': vnd.id,
            'vas_regime_id': cls.regime.id,
            'vas_start_date': '2000-01-01',
        })
        cls.env.user.company_ids = [(4, cls.company.id)]
        cls.env.user.company_id = cls.company
        import datetime
        cls.fy = cls.env['vas.fiscalyear'].create({
            'name': 'L80-%s' % today.year,
            'date_from': '%s-01-01' % today.year,
            'date_to': '%s-12-31' % today.year,
            'state': 'open',
            'company_id': cls.company.id,
        })
        month_start = today.replace(day=1)
        if today.month == 12:
            month_end = today.replace(day=31)
        else:
            month_end = (
                today.replace(month=today.month + 1, day=1)
                - datetime.timedelta(days=1)
            )
        cls.period = cls.env['vas.period'].create({
            'name': '%02d/%s' % (today.month, today.year),
            'date_start': month_start,
            'date_end': month_end,
            'fiscalyear_id': cls.fy.id,
            'state': 'open',
        })
        cls.env['vas.journal']._ensure_journals_for_company(cls.company)
        cls.journal = cls.env['vas.journal'].search([
            ('company_id', '=', cls.company.id), ('code', '=', 'TH'),
        ], limit=1)

    def _acc(self, code):
        return self.env.ref('connecta_vas.vas_account_tt133_%s' % code)

    def _post(self, date_str, lines, ref='L80'):
        move = self.env['vas.move'].create({
            'date': date_str,
            'journal_id': self.journal.id,
            'regime_id': self.regime.id,
            'company_id': self.company.id,
            'ref': ref,
            'move_kind': 'manual',
            'line_ids': [(0, 0, {
                'account_id': acc.id,
                'name': name,
                'debit': deb,
                'credit': cre,
            }) for acc, name, deb, cre in lines],
        })
        move.action_post()
        return move

    def test_l80_actions_and_ops_wiring(self):
        from odoo.tools.safe_eval import safe_eval

        def _domain(act):
            dom = act.domain or []
            if isinstance(dom, str):
                dom = safe_eval(dom)
            return list(dom)

        def _ctx(act):
            ctx = act.context or {}
            if isinstance(ctx, str):
                ctx = safe_eval(ctx)
            return ctx

        dep = self.env.ref('connecta_vas.action_vas_move_depreciation')
        self.assertEqual(dep.res_model, 'vas.move')
        self.assertIn(('move_kind', '=', 'depreciation'), _domain(dep))
        self.assertIn('search_default_group_asset', _ctx(dep))

        li = self.env.ref('connecta_vas.action_vas_move_loan_interest')
        self.assertIn(('move_kind', '=', 'loan_interest'), _domain(li))
        self.assertIn('search_default_group_loan', _ctx(li))

        pay_i = self.env.ref('connecta_vas.action_vas_payment_loan_interest')
        self.assertEqual(pay_i.res_model, 'account.payment')
        self.assertIn(
            ('vas_operation_type', '=', 'loan_interest_pay'),
            _domain(pay_i),
        )
        pay_r = self.env.ref('connecta_vas.action_vas_payment_loan_repay')
        self.assertIn(('vas_operation_type', '=', 'loan_repay'), _domain(pay_r))

        self.assertFalse(
            self.env['ir.model.data'].search([
                ('module', '=', 'connecta_vas'),
                ('name', '=', 'vas_ops_btn_tax_pay'),
            ]),
        )

        Group = self.env['vas.ops.group']
        tax = Group.get_workflow_payload('tax')
        all_labels = (
            [p['label'] for p in tax['process']]
            + [d['label'] for d in tax['detached']]
        )
        self.assertNotIn('Nộp thuế GTGT', all_labels)
        self.assertIn('Khấu trừ GTGT (L06)', all_labels)
        self.assertIn('GTGT hàng nhập khẩu', all_labels)

        vay = Group.get_workflow_payload('vay')
        self.assertEqual([p['label'] for p in vay['process']], [
            'Khế ước vay',
            'Ghi lãi định kỳ',
            'Trả lãi',
            'Trả gốc',
            'Tất toán',
        ])

        asset = Group.get_workflow_payload('asset')
        dep_btn = next(
            p for p in asset['process'] if p['label'] == 'Tính khấu hao định kỳ'
        )
        self.assertEqual(
            dep_btn['action_xmlid'],
            'connecta_vas.action_vas_move_depreciation',
        )

    def test_l80_smart_button_balance_matches_f01(self):
        today = fields.Date.to_string(fields.Date.context_today(self.env.user))
        # Cân: Nợ 111 5tr + 411 Có 5tr
        self._post(today, [
            (self._acc('1111'), 'cash', 5_000_000, 0),
            (self._acc('4111'), 'cap', 0, 5_000_000),
        ])
        acc = self._acc('1111')
        # Force recompute in company context
        acc.invalidate_recordset(['vas_balance', 'vas_balance_period_id'])
        balance = acc.vas_balance
        period = acc.vas_balance_period_id
        self.assertTrue(period)
        self.assertEqual(period.id, self.period.id)

        wiz = self.env['vas.trial.balance.wizard'].create({
            'company_id': self.company.id,
            'period_from_id': period.id,
            'period_to_id': period.id,
            'hide_reversed': True,
        })
        row = wiz._books_account_row(
            self.company, acc, period.date_start, period.date_end, True,
        )
        self.assertEqual(
            float_compare(balance, row['closing'], 2), 0,
            'smart=%s f01_closing=%s' % (balance, row['closing']),
        )
        self.assertEqual(float_compare(balance, 5_000_000, 2), 0)

        act = acc.action_view_vas_move_lines()
        self.assertEqual(act['res_model'], 'vas.move.line')
        self.assertEqual(act['domain'], [('account_id', '=', acc.id)])
        self.assertTrue(act['context'].get('search_default_hide_reversed_adjustments'))

    def test_l80_smart_button_zero_empty_list(self):
        acc = self._acc('1121')
        acc.invalidate_recordset(['vas_balance'])
        self.assertEqual(float_compare(acc.vas_balance, 0.0, 2), 0)
        act = acc.action_view_vas_move_lines()
        lines = self.env['vas.move.line'].search(act['domain'])
        self.assertFalse(lines)
        self.assertIn('Chưa có phát sinh', act.get('help') or '')

    def test_l80_move_source_links_for_group(self):
        """move_kind depreciation/loan_interest liên kết thẻ để gom nhóm."""
        asset = self.env['vas.asset'].create({
            'code': 'L80-A1',
            'name': 'L80 Asset',
            'company_id': self.company.id,
            'regime_id': self.regime.id,
            'asset_type': 'tscd',
            'original_value': 30_000_000,
            'date_start': self.period.date_start,
            'duration_months': 36,
            'method': 'straight_line',
            'account_gross_id': self._acc('2111').id,
            'account_accum_id': self._acc('2141').id,
            'account_expense_id': self._acc('6422').id,
            'source_mode': 'manual',
            'state': 'running',
        })
        line = self.env['vas.asset.line'].create({
            'asset_id': asset.id,
            'sequence': 1,
            'period_id': self.period.id,
            'date': self.period.date_end,
            'amount': 100_000,
            'state': 'planned',
        })
        move = self.env['vas.move'].create({
            'date': self.period.date_end,
            'journal_id': self.journal.id,
            'regime_id': self.regime.id,
            'company_id': self.company.id,
            'move_kind': 'depreciation',
            'source_model': 'vas.asset.line',
            'source_res_id': line.id,
            'ref': 'L80 dep',
            'line_ids': [
                (0, 0, {
                    'account_id': self._acc('6422').id,
                    'name': 'dep', 'debit': 100_000, 'credit': 0,
                }),
                (0, 0, {
                    'account_id': self._acc('2141').id,
                    'name': 'dep', 'debit': 0, 'credit': 100_000,
                }),
            ],
        })
        move.action_post()
        self.assertEqual(move.vas_asset_id, asset)
