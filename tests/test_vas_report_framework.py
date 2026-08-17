# -*- coding: utf-8 -*-
"""Pha 1 — Hợp đồng get_report_data + regression F01 (số y hệt wizard cũ)."""
from odoo import fields
from odoo.tests import tagged, TransactionCase
from odoo.tools import float_compare

from odoo.addons.connecta_vas.models.vas_trial_balance import F01_COLUMNS


@tagged('connecta_vas', 'connecta_vas_report_framework')
class TestVasReportFrameworkP1(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.vnd = cls.env.ref('base.VND')
        if cls.company.currency_id != cls.vnd:
            cls.company.currency_id = cls.vnd

        cls.regime = cls.env['vas.regime'].create({
            'code': 'TT133_FW1',
            'name': 'TT133 Framework P1',
        })
        cls.company.vas_regime_id = cls.regime
        cls.company.vas_start_date = '2095-01-01'

        Account = cls.env['vas.account']

        def mk(code, name, atype='asset'):
            pol = {
                'asset': 'debit', 'liability': 'credit', 'equity': 'debit_or_credit',
                'income': 'none', 'expense': 'none', 'other_income': 'none',
                'other_expense': 'none', 'pl': 'none',
            }.get(atype, 'debit_or_credit')
            return Account.create({
                'code': code,
                'name': name,
                'regime_id': cls.regime.id,
                'account_type': atype,
                'ending_balance_policy': pol,
            })

        cls.acc_111 = mk('111', 'TM FW')
        cls.acc_156 = mk('156', 'HH FW')
        cls.acc_411 = mk('411', 'Von FW', 'equity')
        cls.acc_632 = mk('632', 'GV FW', 'expense')

        cls.sequence = cls.env['ir.sequence'].create({
            'name': 'VAS FW1 Seq',
            'code': 'vas.move.fw1.test',
            'prefix': 'FW1/%(year)s/',
            'padding': 4,
            'company_id': cls.company.id,
        })
        cls.journal = cls.env['vas.journal'].create({
            'code': 'FW1',
            'name': 'FW1 journal',
            'type': 'general',
            'regime_id': cls.regime.id,
            'sequence_id': cls.sequence.id,
            'company_id': cls.company.id,
        })
        cls.fy = cls.env['vas.fiscalyear'].create({
            'name': '2095',
            'date_from': '2095-01-01',
            'date_to': '2095-12-31',
            'state': 'open',
            'company_id': cls.company.id,
        })
        cls.p01 = cls.env['vas.period'].create({
            'name': '01/2095',
            'date_start': '2095-01-01',
            'date_end': '2095-01-31',
            'fiscalyear_id': cls.fy.id,
            'state': 'open',
        })
        cls.p02 = cls.env['vas.period'].create({
            'name': '02/2095',
            'date_start': '2095-02-01',
            'date_end': '2095-02-28',
            'fiscalyear_id': cls.fy.id,
            'state': 'open',
        })

    def _post(self, date, lines, move_kind='manual', **extra):
        move = self.env['vas.move'].create({
            'date': date,
            'journal_id': self.journal.id,
            'regime_id': self.regime.id,
            'move_kind': move_kind,
            'company_id': self.company.id,
            'currency_id': self.vnd.id,
            'ref': extra.pop('ref', 'FW1'),
            'line_ids': [
                fields.Command.create({
                    'account_id': vals['account'].id,
                    'name': 'l',
                    'debit': vals.get('debit', 0.0),
                    'credit': vals.get('credit', 0.0),
                })
                for vals in lines
            ],
            **extra,
        })
        move.action_post()
        return move

    def _seed(self):
        self._post('2095-01-01', [
            {'account': self.acc_111, 'debit': 8_000_000},
            {'account': self.acc_156, 'debit': 2_000_000},
            {'account': self.acc_411, 'credit': 10_000_000},
        ], move_kind='opening', ref='SDK')
        self._post('2095-02-10', [
            {'account': self.acc_632, 'debit': 400_000},
            {'account': self.acc_156, 'credit': 400_000},
        ], move_kind='cogs', ref='GV')

    def _options(self, hide_reversed=True):
        return {
            'company_id': self.company.id,
            'period_from_id': self.p02.id,
            'period_to_id': self.p02.id,
            'hide_reversed': hide_reversed,
        }

    def test_p1_contract_shape(self):
        self._seed()
        data = self.env['vas.trial.balance.wizard'].get_report_data(self._options())
        self.assertEqual([c['name'] for c in data['columns']], [c['name'] for c in F01_COLUMNS])
        self.assertTrue(data['lines'])
        for line in data['lines']:
            self.assertEqual(len(line['values']), len(data['columns']))
            self.assertIn('id', line)
            self.assertIn('level', line)
            self.assertIn('unfoldable', line)
            self.assertIn('is_total', line)
        self.assertTrue(any(l['is_total'] for l in data['lines']))
        self.assertEqual(data['meta']['form_code'], 'F01-DNN')
        self.assertTrue(data['checks']['is_balanced'])
        print(f'\n=== P1 contract lines={len(data["lines"])} balanced={data["checks"]["is_balanced"]} ===\n')

    def test_p1_numbers_match_wizard_compute(self):
        """a — F01 qua hợp đồng = đúng từng số bản wizard cũ."""
        self._seed()
        opts = self._options()
        data = self.env['vas.trial.balance.wizard'].get_report_data(opts)

        wiz = self.env['vas.trial.balance.wizard'].create({
            'company_id': self.company.id,
            'period_from_id': self.p02.id,
            'period_to_id': self.p02.id,
            'hide_reversed': True,
        })
        wiz.action_compute()

        by_code = {
            l.account_code: l
            for l in wiz.line_ids if l.row_type == 'account'
        }
        for line in data['lines']:
            if line['is_total']:
                total = wiz.line_ids.filtered(lambda l: l.row_type == 'total')
                self.assertEqual(line['values'][2], total.opening_debit)
                self.assertEqual(line['values'][3], total.opening_credit)
                self.assertEqual(line['values'][4], total.ps_debit)
                self.assertEqual(line['values'][5], total.ps_credit)
                self.assertEqual(line['values'][6], total.closing_debit)
                self.assertEqual(line['values'][7], total.closing_credit)
                continue
            # Pha 2: dòng cha (rollup) không có trong wizard flat — chỉ đối chiếu LÁ
            if not line.get('is_leaf', True):
                continue
            code = line['values'][0]
            old = by_code[code]
            self.assertEqual(line['values'][2], old.opening_debit, code)
            self.assertEqual(line['values'][3], old.opening_credit, code)
            self.assertEqual(line['values'][4], old.ps_debit, code)
            self.assertEqual(line['values'][5], old.ps_credit, code)
            self.assertEqual(line['values'][6], old.closing_debit, code)
            self.assertEqual(line['values'][7], old.closing_credit, code)

        r156 = by_code['156']
        print(
            f'\n=== P1 a regression 156 ===\n'
            f'  dauNo={r156.opening_debit} PSCo={r156.ps_credit} cuoiNo={r156.closing_debit}\n'
            f'  totals dau={wiz.total_opening_debit}/{wiz.total_opening_credit} '
            f'PS={wiz.total_ps_debit}/{wiz.total_ps_credit}\n'
        )

    def test_p1_hide_toggle_closing_stable(self):
        """b — công tắc ẩn/hiện đảo: kiểm cân + SD cuối không đổi."""
        self._seed()
        old = self._post('2095-02-12', [
            {'account': self.acc_632, 'debit': 50_000},
            {'account': self.acc_156, 'credit': 50_000},
        ], move_kind='cogs', ref='Old',
            source_model='stock.move', source_res_id=930001)
        old.action_reverse()
        self._post('2095-02-12', [
            {'account': self.acc_632, 'debit': 50_000},
            {'account': self.acc_156, 'credit': 50_000},
        ], move_kind='cogs', ref='New',
            source_model='stock.move', source_res_id=930001)

        hide = self.env['vas.trial.balance.wizard'].get_report_data(self._options(True))
        show = self.env['vas.trial.balance.wizard'].get_report_data(self._options(False))
        self.assertTrue(hide['checks']['is_balanced'] and show['checks']['is_balanced'])
        for key in ('diff_opening', 'diff_ps', 'diff_closing'):
            self.assertEqual(float_compare(hide['checks'][key], show['checks'][key], 2), 0)

        def closing_map(data):
            return {
                l['values'][0]: (l['values'][6], l['values'][7])
                for l in data['lines']
                if l.get('is_leaf') and not l['is_total']
            }

        self.assertEqual(closing_map(hide), closing_map(show))
        print(
            f'\n=== P1 b toggle ===\n'
            f'  hide checks={hide["checks"]}\n'
            f'  show checks={show["checks"]}\n'
        )

    def test_p1_xlsx_from_contract_lines(self):
        """c — XLSX sinh từ cây lines của hợp đồng."""
        self._seed()
        data = self.env['vas.trial.balance.wizard'].get_report_data(self._options())
        content = self.env['vas.report.engine'].render_xlsx_bytes(data)
        self.assertTrue(content.startswith(b'PK'))  # zip/xlsx
        self.assertGreater(len(content), 500)
        print(f'\n=== P1 c xlsx bytes={len(content)} ===\n')
