# -*- coding: utf-8 -*-
"""F01-DNN Bảng cân đối số phát sinh — nghiệm thu A–E."""
from odoo import fields
from odoo.tests import tagged, TransactionCase
from odoo.tools import float_compare


@tagged('connecta_vas', 'connecta_vas_trial_balance')
class TestVasTrialBalance(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.vnd = cls.env.ref('base.VND')
        if cls.company.currency_id != cls.vnd:
            cls.company.currency_id = cls.vnd

        cls.regime = cls.env['vas.regime'].create({
            'code': 'TT133_F01',
            'name': 'TT133 F01 Test',
        })
        cls.company.vas_regime_id = cls.regime
        cls.company.vas_start_date = '2096-01-01'

        Account = cls.env['vas.account']

        def mk(code, name, atype='asset', reconcile=False):
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
                'reconcile': reconcile,
            })

        cls.acc_111 = mk('111', 'Tien mat F01', 'asset')
        cls.acc_131 = mk('131', 'Phai thu F01', 'asset', reconcile=True)
        cls.acc_156 = mk('156', 'Hang hoa F01', 'asset')
        cls.acc_331 = mk('331', 'Phai tra F01', 'liability', reconcile=True)
        cls.acc_411 = mk('411', 'Von F01', 'equity')
        cls.acc_5111 = mk('5111', 'Doanh thu F01', 'income')
        cls.acc_632 = mk('632', 'Gia von F01', 'expense')

        cls.sequence = cls.env['ir.sequence'].create({
            'name': 'VAS F01 Seq',
            'code': 'vas.move.f01.test',
            'prefix': 'F01/%(year)s/',
            'padding': 4,
            'company_id': cls.company.id,
        })
        cls.journal = cls.env['vas.journal'].create({
            'code': 'F01',
            'name': 'F01 test journal',
            'type': 'general',
            'regime_id': cls.regime.id,
            'sequence_id': cls.sequence.id,
            'company_id': cls.company.id,
        })

        cls.fy = cls.env['vas.fiscalyear'].search([
            ('company_id', '=', cls.company.id),
            ('date_from', '<=', '2096-01-01'),
            ('date_to', '>=', '2096-12-31'),
        ], limit=1)
        if not cls.fy:
            cls.fy = cls.env['vas.fiscalyear'].create({
                'name': '2096',
                'date_from': '2096-01-01',
                'date_to': '2096-12-31',
                'state': 'open',
                'company_id': cls.company.id,
            })
        cls.p01 = cls.env['vas.period'].search([
            ('fiscalyear_id', '=', cls.fy.id),
            ('date_start', '=', '2096-01-01'),
        ], limit=1)
        if not cls.p01:
            cls.p01 = cls.env['vas.period'].create({
                'name': '01/2096',
                'date_start': '2096-01-01',
                'date_end': '2096-01-31',
                'fiscalyear_id': cls.fy.id,
                'state': 'open',
            })
        cls.p02 = cls.env['vas.period'].search([
            ('fiscalyear_id', '=', cls.fy.id),
            ('date_start', '=', '2096-02-01'),
        ], limit=1)
        if not cls.p02:
            cls.p02 = cls.env['vas.period'].create({
                'name': '02/2096',
                'date_start': '2096-02-01',
                'date_end': '2096-02-29',
                'fiscalyear_id': cls.fy.id,
                'state': 'open',
            })
        else:
            cls.p01.state = 'open'
            cls.p02.state = 'open'

        cls.partner = cls.env['res.partner'].create({
            'name': 'KH F01', 'company_id': cls.company.id, 'customer_rank': 1,
        })

    def _post(self, date, lines, move_kind='manual', **extra):
        move = self.env['vas.move'].create({
            'date': date,
            'journal_id': self.journal.id,
            'regime_id': self.regime.id,
            'move_kind': move_kind,
            'company_id': self.company.id,
            'currency_id': self.vnd.id,
            'ref': extra.pop('ref', 'F01 test'),
            'line_ids': [
                fields.Command.create({
                    'account_id': vals['account'].id,
                    'name': vals.get('name', 'line'),
                    'debit': vals.get('debit', 0.0),
                    'credit': vals.get('credit', 0.0),
                    'partner_id': vals['partner'].id if vals.get('partner') else False,
                })
                for vals in lines
            ],
            **extra,
        })
        move.action_post()
        return move

    def _seed_balanced_set(self):
        """Bộ bút toán cân — dùng cho A/B/C/E."""
        # Opening 01/01
        self._post('2096-01-01', [
            {'account': self.acc_111, 'debit': 10_000_000},
            {'account': self.acc_156, 'debit': 5_000_000},
            {'account': self.acc_411, 'credit': 15_000_000},
        ], move_kind='opening', ref='SDK F01')
        # Jan activity
        self._post('2096-01-15', [
            {'account': self.acc_131, 'debit': 1_100_000, 'partner': self.partner},
            {'account': self.acc_5111, 'credit': 1_000_000},
            {'account': self.acc_331, 'credit': 100_000},  # placeholder tax-like
        ], move_kind='sale_inv', ref='Ban T1')
        # Feb activity
        self._post('2096-02-10', [
            {'account': self.acc_632, 'debit': 600_000},
            {'account': self.acc_156, 'credit': 600_000},
        ], move_kind='cogs', ref='GV T2')
        self._post('2096-02-20', [
            {'account': self.acc_111, 'debit': 500_000},
            {'account': self.acc_131, 'credit': 500_000, 'partner': self.partner},
        ], move_kind='payment', ref='Thu T2')

    def _tb(self, period_from=None, period_to=None, hide_reversed=True):
        wiz = self.env['vas.trial.balance.wizard'].create({
            'company_id': self.company.id,
            'period_from_id': (period_from or self.p02).id,
            'period_to_id': (period_to or self.p02).id,
            'hide_reversed': hide_reversed,
        })
        wiz.action_compute()
        return wiz

    def _row(self, wiz, code):
        return wiz.line_ids.filtered(
            lambda l: l.row_type == 'account' and l.account_code == code
        )

    def test_a_accounts_and_balance_sides(self):
        """A — Đủ TK có PS/dư; dư Nợ → cột Nợ, dư Có → cột Có."""
        self._seed_balanced_set()
        wiz = self._tb()
        codes = wiz.line_ids.filtered(lambda l: l.row_type == 'account').mapped('account_code')
        for need in ('111', '131', '156', '331', '411', '5111', '632'):
            self.assertIn(need, codes, f'Thiếu TK {need} trên F01')

        r156 = self._row(wiz, '156')
        # Đầu: 5tr Nợ; PS Có 600k → cuối 4.4tr Nợ
        self.assertEqual(r156.opening_debit, 5_000_000.0)
        self.assertEqual(r156.opening_credit, 0.0)
        self.assertEqual(r156.ps_credit, 600_000.0)
        self.assertEqual(r156.closing_debit, 4_400_000.0)
        self.assertEqual(r156.closing_credit, 0.0)

        r411 = self._row(wiz, '411')
        self.assertEqual(r411.opening_credit, 15_000_000.0)
        self.assertEqual(r411.opening_debit, 0.0)
        self.assertEqual(r411.closing_credit, 15_000_000.0)
        print(
            f'\n=== F01 A ===\n'
            f'  TK={sorted(codes)}\n'
            f'  156 dauNo={r156.opening_debit} PSCo={r156.ps_credit} cuoiNo={r156.closing_debit}\n'
            f'  411 dauCo={r411.opening_credit}\n'
        )

    def test_b_three_pair_totals_balance(self):
        """B — Ba cặp tổng cân."""
        self._seed_balanced_set()
        wiz = self._tb()
        self.assertTrue(wiz.is_balanced, wiz.warning_text)
        self.assertEqual(wiz.diff_opening, 0.0)
        self.assertEqual(wiz.diff_ps, 0.0)
        self.assertEqual(wiz.diff_closing, 0.0)
        total = wiz.line_ids.filtered(lambda l: l.row_type == 'total')
        self.assertEqual(total.opening_debit, total.opening_credit)
        self.assertEqual(total.ps_debit, total.ps_credit)
        self.assertEqual(total.closing_debit, total.closing_credit)
        print(
            f'\n=== F01 B ===\n'
            f'  dau {total.opening_debit}/{total.opening_credit}\n'
            f'  PS  {total.ps_debit}/{total.ps_credit}\n'
            f'  cuoi {total.closing_debit}/{total.closing_credit}\n'
        )

    def test_c_cross_check_with_account_ledger(self):
        """C — F01 khớp Sổ chi tiết cùng TK + kỳ."""
        self._seed_balanced_set()
        tb = self._tb()
        r131 = self._row(tb, '131')

        led = self.env['vas.account.ledger.wizard'].create({
            'company_id': self.company.id,
            'account_id': self.acc_131.id,
            'period_from_id': self.p02.id,
            'period_to_id': self.p02.id,
            'hide_reversed': True,
        })
        led.action_compute()
        open_l = led.line_ids.filtered(lambda l: l.row_type == 'opening')
        total_l = led.line_ids.filtered(lambda l: l.row_type == 'total_ps')
        close_l = led.line_ids.filtered(lambda l: l.row_type == 'closing')

        self.assertEqual(r131.opening_debit, open_l.balance_debit)
        self.assertEqual(r131.opening_credit, open_l.balance_credit)
        self.assertEqual(r131.ps_debit, total_l.debit)
        self.assertEqual(r131.ps_credit, total_l.credit)
        self.assertEqual(r131.closing_debit, close_l.balance_debit)
        self.assertEqual(r131.closing_credit, close_l.balance_credit)
        print(
            f'\n=== F01 C cross 131 ===\n'
            f'  F01  dau={r131.opening_debit} PS={r131.ps_debit}/{r131.ps_credit} cuoi={r131.closing_debit}\n'
            f'  SCT  dau={open_l.balance_debit} PS={total_l.debit}/{total_l.credit} cuoi={close_l.balance_debit}\n'
        )

    def test_d_opening_in_opening_col_not_ps(self):
        """D — Opening vào SD đầu, không vào PS."""
        self._post('2096-01-01', [
            {'account': self.acc_111, 'debit': 2_000_000},
            {'account': self.acc_411, 'credit': 2_000_000},
        ], move_kind='opening', ref='SDK only')
        self._post('2096-01-20', [
            {'account': self.acc_156, 'debit': 100_000},
            {'account': self.acc_111, 'credit': 100_000},
        ], move_kind='stock', ref='Mua T1')

        wiz = self._tb(period_from=self.p01, period_to=self.p01)
        r111 = self._row(wiz, '111')
        # Đầu = opening 2tr; PS Có 100k (mua); cuối 1.9tr Nợ
        self.assertEqual(r111.opening_debit, 2_000_000.0)
        self.assertEqual(r111.ps_debit, 0.0)
        self.assertEqual(r111.ps_credit, 100_000.0)
        self.assertEqual(r111.closing_debit, 1_900_000.0)
        self.assertTrue(wiz.is_balanced, wiz.warning_text)
        print(
            f'\n=== F01 D opening ===\n'
            f'  111 dauNo={r111.opening_debit} PSNo={r111.ps_debit} PSCo={r111.ps_credit} cuoi={r111.closing_debit}\n'
        )

    def test_e_hide_reversed_totals_unchanged(self):
        """E — Bật/tắt ẩn đảo: SD đầu/cuối + kiểm 3 cặp không đổi.

        Σ PS gộp có thể tăng khi hiện đủ (cặp đảo hiện 2 chiều) nhưng triệt tiêu
        trên số dư — cùng nghĩa LIST_HIDE_REVERSED trên sổ chi tiết.
        """
        self._seed_balanced_set()
        old = self._post('2096-02-15', [
            {'account': self.acc_632, 'debit': 50_000},
            {'account': self.acc_156, 'credit': 50_000},
        ], move_kind='cogs', ref='Old',
            source_model='stock.move', source_res_id=920001)
        old.action_reverse()
        self._post('2096-02-15', [
            {'account': self.acc_632, 'debit': 50_000},
            {'account': self.acc_156, 'credit': 50_000},
        ], move_kind='cogs', ref='New',
            source_model='stock.move', source_res_id=920001)

        hide = self._tb(hide_reversed=True)
        show = self._tb(hide_reversed=False)
        for field in (
            'total_opening_debit', 'total_opening_credit',
            'total_closing_debit', 'total_closing_credit',
            'diff_opening', 'diff_ps', 'diff_closing',
        ):
            self.assertEqual(
                float_compare(hide[field], show[field], 2), 0,
                f'{field}: hide={hide[field]} show={show[field]}',
            )
        self.assertTrue(hide.is_balanced and show.is_balanced)
        for code in ('156', '632'):
            h = self._row(hide, code)
            s = self._row(show, code)
            self.assertEqual(h.closing_debit, s.closing_debit)
            self.assertEqual(h.closing_credit, s.closing_credit)
        print(
            f'\n=== F01 E toggle ===\n'
            f'  hide cuoi={hide.total_closing_debit}/{hide.total_closing_credit} '
            f'PS={hide.total_ps_debit}/{hide.total_ps_credit}\n'
            f'  show cuoi={show.total_closing_debit}/{show.total_closing_credit} '
            f'PS={show.total_ps_debit}/{show.total_ps_credit}\n'
        )
