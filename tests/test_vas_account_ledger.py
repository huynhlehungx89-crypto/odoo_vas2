# -*- coding: utf-8 -*-
"""Sổ chi tiết TK — nghiệm thu A–E (TT133 S19/S12)."""
from odoo import fields
from odoo.tests import tagged, TransactionCase
from odoo.tools import float_compare

from odoo.addons.connecta_vas.models.vas_move import VasMove


@tagged('connecta_vas', 'connecta_vas_ledger')
class TestVasAccountLedger(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.vnd = cls.env.ref('base.VND')
        if cls.company.currency_id != cls.vnd:
            cls.company.currency_id = cls.vnd

        cls.regime = cls.env['vas.regime'].create({
            'code': 'TT133_LED',
            'name': 'TT133 Ledger Test',
        })
        cls.company.vas_regime_id = cls.regime
        cls.company.vas_start_date = '2097-01-01'

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

        cls.acc_156 = mk('156', 'Hang hoa LED', 'asset')
        cls.acc_632 = mk('632', 'Gia von LED', 'expense')
        cls.acc_131 = mk('131', 'Phai thu LED', 'asset', reconcile=True)
        cls.acc_5111 = mk('5111', 'Doanh thu LED', 'income')
        cls.acc_33311 = mk('33311', 'Thue ra LED', 'liability')
        cls.acc_111 = mk('111', 'Tien mat LED', 'asset')
        cls.acc_411 = mk('411', 'Von LED', 'equity')

        cls.sequence = cls.env['ir.sequence'].create({
            'name': 'VAS Ledger Seq',
            'code': 'vas.move.ledger.test',
            'prefix': 'LED/%(year)s/',
            'padding': 4,
            'company_id': cls.company.id,
        })
        cls.journal = cls.env['vas.journal'].create({
            'code': 'LED',
            'name': 'Ledger test journal',
            'type': 'general',
            'regime_id': cls.regime.id,
            'sequence_id': cls.sequence.id,
            'company_id': cls.company.id,
        })

        cls.fy = cls.env['vas.fiscalyear'].search([
            ('company_id', '=', cls.company.id),
            ('date_from', '<=', '2097-01-01'),
            ('date_to', '>=', '2097-12-31'),
        ], limit=1)
        if not cls.fy:
            cls.fy = cls.env['vas.fiscalyear'].create({
                'name': '2097',
                'date_from': '2097-01-01',
                'date_to': '2097-12-31',
                'state': 'open',
                'company_id': cls.company.id,
            })
        cls.p01 = cls.env['vas.period'].search([
            ('fiscalyear_id', '=', cls.fy.id),
            ('date_start', '=', '2097-01-01'),
        ], limit=1)
        if not cls.p01:
            cls.p01 = cls.env['vas.period'].create({
                'name': '01/2097',
                'date_start': '2097-01-01',
                'date_end': '2097-01-31',
                'fiscalyear_id': cls.fy.id,
                'state': 'open',
            })
        cls.p02 = cls.env['vas.period'].search([
            ('fiscalyear_id', '=', cls.fy.id),
            ('date_start', '=', '2097-02-01'),
        ], limit=1)
        if not cls.p02:
            cls.p02 = cls.env['vas.period'].create({
                'name': '02/2097',
                'date_start': '2097-02-01',
                'date_end': '2097-02-28',
                'fiscalyear_id': cls.fy.id,
                'state': 'open',
            })
        else:
            cls.p01.state = 'open'
            cls.p02.state = 'open'

        cls.partner_a = cls.env['res.partner'].create({
            'name': 'KH Ledger A', 'company_id': cls.company.id, 'customer_rank': 1,
        })
        cls.partner_b = cls.env['res.partner'].create({
            'name': 'KH Ledger B', 'company_id': cls.company.id, 'customer_rank': 1,
        })

    def _post(self, date, lines, move_kind='manual', **extra):
        move = self.env['vas.move'].create({
            'date': date,
            'journal_id': self.journal.id,
            'regime_id': self.regime.id,
            'move_kind': move_kind,
            'company_id': self.company.id,
            'currency_id': self.vnd.id,
            'ref': extra.pop('ref', 'Ledger test'),
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

    def _wizard(self, account, period_from=None, period_to=None, hide_reversed=True, partner=None):
        wiz = self.env['vas.account.ledger.wizard'].create({
            'company_id': self.company.id,
            'account_id': account.id,
            'period_from_id': (period_from or self.p02).id,
            'period_to_id': (period_to or self.p02).id,
            'hide_reversed': hide_reversed,
            'partner_id': partner.id if partner else False,
        })
        wiz.action_compute()
        return wiz

    def _rows(self, wiz, book_sequence=None, row_type=None):
        lines = wiz.line_ids
        if book_sequence is not None:
            lines = lines.filtered(lambda l: l.book_sequence == book_sequence)
        if row_type:
            lines = lines.filtered(lambda l: l.row_type == row_type)
        return lines.sorted(lambda l: (l.book_sequence, l.sequence, l.id))

    def test_a_regular_account_running_balance(self):
        """A — TK thường 156: đầu kỳ, PS, SD 2 cột, cuối = đầu + PS."""
        # Trước kỳ xem (01): nhập kho Nợ 156 5tr / Có 411
        self._post('2097-01-10', [
            {'account': self.acc_156, 'debit': 5_000_000},
            {'account': self.acc_411, 'credit': 5_000_000},
        ], move_kind='stock', ref='Nhap kho 01')
        # Trong kỳ 02: xuất Nợ 632 2tr / Có 156; rồi nhập thêm Nợ 156 1tr / Có 411
        self._post('2097-02-05', [
            {'account': self.acc_632, 'debit': 2_000_000},
            {'account': self.acc_156, 'credit': 2_000_000},
        ], move_kind='cogs', ref='Xuat kho')
        self._post('2097-02-20', [
            {'account': self.acc_156, 'debit': 1_000_000},
            {'account': self.acc_411, 'credit': 1_000_000},
        ], move_kind='stock', ref='Nhap them')

        wiz = self._wizard(self.acc_156)
        self.assertEqual(wiz.layout, 'regular')
        self.assertEqual(wiz.form_code, 'S19-DNN')

        opening = self._rows(wiz, row_type='opening')
        self.assertEqual(len(opening), 1)
        self.assertEqual(opening.balance_debit, 5_000_000.0)
        self.assertEqual(opening.balance_credit, 0.0)

        moves = self._rows(wiz, row_type='move')
        self.assertEqual(len(moves), 2)
        # Xuất: Có 156 → SD = 5tr - 2tr = 3tr Nợ
        self.assertEqual(moves[0].credit, 2_000_000.0)
        self.assertEqual(moves[0].counterpart_code, '632')
        self.assertEqual(moves[0].balance_debit, 3_000_000.0)
        # Nhập: Nợ 156 → SD = 4tr Nợ
        self.assertEqual(moves[1].debit, 1_000_000.0)
        self.assertEqual(moves[1].counterpart_code, '411')
        self.assertEqual(moves[1].balance_debit, 4_000_000.0)

        total = self._rows(wiz, row_type='total_ps')
        self.assertEqual(total.debit, 1_000_000.0)
        self.assertEqual(total.credit, 2_000_000.0)

        closing = self._rows(wiz, row_type='closing')
        self.assertEqual(closing.balance_debit, 4_000_000.0)
        # cuối = đầu + PS Nợ − PS Có
        expected = opening.balance_debit + total.debit - total.credit
        self.assertEqual(closing.balance_debit, expected)
        print(
            f'\n=== A 156 S19 ===\n'
            f'  dau ky SD No={opening.balance_debit}\n'
            f'  PS No={total.debit} PS Co={total.credit}\n'
            f'  cuoi ky SD No={closing.balance_debit}\n'
        )

    def test_b_multi_counterpart_split(self):
        """B — HĐ bán Nợ131/Có5111/Có33311 → sổ 131 ra đúng 2 dòng con."""
        tax_code = self.acc_33311.code
        self._post('2097-02-12', [
            {'account': self.acc_131, 'debit': 110_000, 'partner': self.partner_a},
            {'account': self.acc_5111, 'credit': 100_000},
            {'account': self.acc_33311, 'credit': 10_000},
        ], move_kind='sale_inv', ref='HD ban VAT')

        wiz = self._wizard(self.acc_131, partner=self.partner_a)
        moves = self._rows(wiz, row_type='move')
        self.assertEqual(len(moves), 2, f'Phải 2 dòng con, được {moves.mapped("counterpart_code")}')
        by_c = {m.counterpart_code: m for m in moves}
        self.assertIn('5111', by_c)
        self.assertIn(tax_code, by_c)
        self.assertEqual(by_c['5111'].debit, 100_000.0)
        self.assertEqual(by_c[tax_code].debit, 10_000.0)
        self.assertEqual(sum(moves.mapped('debit')), 110_000.0)
        print(
            f'\n=== B 131 split ===\n'
            f'  {[ (m.counterpart_code, m.debit) for m in moves ]}\n'
        )

    def test_c_ar_by_partner_with_discount_column(self):
        """C — 131 theo từng đối tượng; cột thời hạn CK trống; dư đầu/cuối riêng."""
        self._post('2097-01-15', [
            {'account': self.acc_131, 'debit': 200_000, 'partner': self.partner_a},
            {'account': self.acc_5111, 'credit': 200_000},
        ], move_kind='sale_inv', ref='Ban A T1')
        self._post('2097-01-16', [
            {'account': self.acc_131, 'debit': 50_000, 'partner': self.partner_b},
            {'account': self.acc_5111, 'credit': 50_000},
        ], move_kind='sale_inv', ref='Ban B T1')
        self._post('2097-02-10', [
            {'account': self.acc_111, 'debit': 80_000},
            {'account': self.acc_131, 'credit': 80_000, 'partner': self.partner_a},
        ], move_kind='payment', ref='Thu A')

        wiz = self._wizard(self.acc_131)
        self.assertEqual(wiz.layout, 'ar_ap')
        self.assertEqual(wiz.form_code, 'S12-DNN')

        books = {}
        for line in wiz.line_ids:
            books.setdefault(line.book_sequence, line.partner_id)

        self.assertGreaterEqual(len(books), 2)
        # Partner A: đầu 200k, thu 80k → cuối 120k
        book_a = next(
            seq for seq, p in books.items() if p == self.partner_a
        )
        open_a = self._rows(wiz, book_sequence=book_a, row_type='opening')
        close_a = self._rows(wiz, book_sequence=book_a, row_type='closing')
        self.assertEqual(open_a.balance_debit, 200_000.0)
        self.assertEqual(close_a.balance_debit, 120_000.0)

        book_b = next(seq for seq, p in books.items() if p == self.partner_b)
        open_b = self._rows(wiz, book_sequence=book_b, row_type='opening')
        close_b = self._rows(wiz, book_sequence=book_b, row_type='closing')
        self.assertEqual(open_b.balance_debit, 50_000.0)
        self.assertEqual(close_b.balance_debit, 50_000.0)

        # Cột thời hạn chiết khấu luôn trống
        self.assertFalse(any(wiz.line_ids.mapped('discount_deadline')))
        print(
            f'\n=== C 131 theo DT ===\n'
            f'  A dau={open_a.balance_debit} cuoi={close_a.balance_debit}\n'
            f'  B dau={open_b.balance_debit} cuoi={close_b.balance_debit}\n'
            f'  discount_deadline all empty={not any(wiz.line_ids.mapped("discount_deadline"))}\n'
        )

    def test_d_opening_excluded_from_period_movements(self):
        """D — Khoảng chứa ngày opening: opening không vào PS; đầu kỳ phản ánh opening."""
        opening_move = self._post('2097-01-01', [
            {'account': self.acc_156, 'debit': 3_000_000},
            {'account': self.acc_411, 'credit': 3_000_000},
        ], move_kind='opening', ref='SDK')
        self._post('2097-01-20', [
            {'account': self.acc_156, 'debit': 500_000},
            {'account': self.acc_411, 'credit': 500_000},
        ], move_kind='stock', ref='Nhap T1')

        wiz = self._wizard(self.acc_156, period_from=self.p01, period_to=self.p01)
        opening = self._rows(wiz, row_type='opening')
        moves = self._rows(wiz, row_type='move')
        self.assertFalse(
            any(m.move_id == opening_move for m in moves),
            'Opening không được lọt vào phát sinh',
        )
        # Đầu kỳ = 3tr (opening trong khoảng); PS = 0.5tr (nhập T1)
        self.assertEqual(opening.balance_debit, 3_000_000.0)
        total = self._rows(wiz, row_type='total_ps')
        self.assertEqual(total.debit, 500_000.0)
        closing = self._rows(wiz, row_type='closing')
        self.assertEqual(closing.balance_debit, 3_500_000.0)
        print(
            f'\n=== D opening ===\n'
            f'  opening_move in PS? {any(m.move_id == opening_move for m in moves)}\n'
            f'  dau={opening.balance_debit} PS={total.debit} cuoi={closing.balance_debit}\n'
        )

    def test_e_hide_reversed_toggle_same_balance(self):
        """E — Bật/tắt ẩn đảo: số dư cuối không đổi."""
        old = self._post('2097-02-08', [
            {'account': self.acc_632, 'debit': 20_000},
            {'account': self.acc_156, 'credit': 20_000},
        ], move_kind='cogs', ref='Old cogs',
            source_model='stock.move', source_res_id=910001)
        action = old.action_reverse()
        rev = self.env['vas.move'].browse(action['res_id'])
        new = self._post('2097-02-08', [
            {'account': self.acc_632, 'debit': 20_000},
            {'account': self.acc_156, 'credit': 20_000},
        ], move_kind='cogs', ref='New cogs',
            source_model='stock.move', source_res_id=910001)

        wiz_hide = self._wizard(self.acc_156, hide_reversed=True)
        wiz_show = self._wizard(self.acc_156, hide_reversed=False)

        close_hide = self._rows(wiz_hide, row_type='closing')
        close_show = self._rows(wiz_show, row_type='closing')
        self.assertEqual(
            float_compare(close_hide.balance_debit - close_hide.balance_credit,
                          close_show.balance_debit - close_show.balance_credit, 2),
            0,
            f'hide={close_hide.balance_debit}/{close_hide.balance_credit} '
            f'show={close_show.balance_debit}/{close_show.balance_credit}',
        )
        # Chế độ ẩn: không thấy old/rev trong PS
        hide_moves = self._rows(wiz_hide, row_type='move')
        hide_ids = set(hide_moves.mapped('move_id').ids)
        self.assertNotIn(old.id, hide_ids)
        self.assertNotIn(rev.id, hide_ids)
        self.assertIn(new.id, hide_ids)
        # Chế độ hiện đủ: có cả 3 (hoặc ít nhất old+rev+new hiện diện)
        show_ids = set(self._rows(wiz_show, row_type='move').mapped('move_id').ids)
        self.assertTrue({old.id, rev.id, new.id} <= show_ids)
        # Domain tái sử dụng constant
        self.assertEqual(
            VasMove.LIST_HIDE_REVERSED_DOMAIN,
            [('state', '!=', 'reversed'), ('is_reversal', '=', False)],
        )
        print(
            f'\n=== E hide toggle ===\n'
            f'  close_hide SD={close_hide.balance_debit - close_hide.balance_credit}\n'
            f'  close_show SD={close_show.balance_debit - close_show.balance_credit}\n'
            f'  hide_moves={len(hide_moves)} show_moves={len(show_ids)}\n'
        )
