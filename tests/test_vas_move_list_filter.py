# -*- coding: utf-8 -*-
"""List bút toán: mặc định ẩn cặp đã đảo; tắt filter thì hiện đủ; số dư không đổi."""
from odoo import fields
from odoo.tests import tagged, TransactionCase

from odoo.addons.connecta_vas.models.vas_move import VasMove


@tagged('connecta_vas', 'connecta_vas_list_filter')
class TestVasMoveListHideReversed(TransactionCase):
    """Ba điểm nghiệm thu lớp HIỂN THỊ — không đụng cơ chế đảo / báo cáo."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.vnd = cls.env.ref('base.VND')
        cls.regime = cls.env['vas.regime'].create({
            'code': 'TT133_LIST',
            'name': 'TT133 List Filter',
        })
        cls.acc_156 = cls.env['vas.account'].create({
            'code': '156L',
            'name': 'Hang hoa list-test',
            'regime_id': cls.regime.id,
            'account_type': 'asset',
            'ending_balance_policy': 'debit',
        })
        cls.acc_632 = cls.env['vas.account'].create({
            'code': '632L',
            'name': 'Gia von list-test',
            'regime_id': cls.regime.id,
            'account_type': 'expense',
            'ending_balance_policy': 'none',
        })
        cls.sequence = cls.env['ir.sequence'].create({
            'name': 'VAS List Filter Seq',
            'code': 'vas.move.list.filter',
            'prefix': 'LST/%(year)s/',
            'padding': 4,
            'company_id': cls.company.id,
        })
        cls.journal = cls.env['vas.journal'].create({
            'code': 'LST',
            'name': 'List filter journal',
            'type': 'general',
            'regime_id': cls.regime.id,
            'sequence_id': cls.sequence.id,
            'company_id': cls.company.id,
        })
        fy = cls.env['vas.fiscalyear'].create({
            'name': '2098',
            'date_from': '2098-01-01',
            'date_to': '2098-12-31',
            'state': 'open',
            'company_id': cls.company.id,
        })
        cls.env['vas.period'].create({
            'name': '01/2098',
            'date_start': '2098-01-01',
            'date_end': '2098-01-31',
            'fiscalyear_id': fy.id,
            'state': 'open',
        })
        # Cutoff ≤ ngày bút toán list-filter (2098-01-10).
        cls.company.vas_start_date = '2098-01-01'

    def _make_posted(self, amount=20_000.0, **extra):
        move = self.env['vas.move'].create({
            'date': '2098-01-10',
            'journal_id': self.journal.id,
            'regime_id': self.regime.id,
            'move_kind': extra.pop('move_kind', 'cogs'),
            'company_id': self.company.id,
            'currency_id': self.vnd.id,
            'line_ids': [
                fields.Command.create({
                    'account_id': self.acc_632.id,
                    'name': 'GV',
                    'debit': amount,
                    'credit': 0.0,
                }),
                fields.Command.create({
                    'account_id': self.acc_156.id,
                    'name': 'Kho',
                    'debit': 0.0,
                    'credit': amount,
                }),
            ],
            **extra,
        })
        move.action_post()
        return move

    def _balance(self, account):
        """Cách báo cáo/engine đọc số dư: search line, KHÔNG gắn list filter."""
        lines = self.env['vas.move.line'].search([
            ('account_id', '=', account.id),
            ('move_id.company_id', '=', self.company.id),
            ('move_id.journal_id', '=', self.journal.id),
        ])
        return round(sum(l.debit - l.credit for l in lines), 2)

    def _scenario_reverse_and_replace(self):
        """Giống B7: bản cũ → đảo → bản mới (thay ánh xạ). Trả (old, rev, new)."""
        old = self._make_posted(
            amount=20_000.0,
            source_model='stock.move',
            source_res_id=900001,
            source_ref='S00207-TEST/Stock>Customers',
        )
        action = old.action_reverse()
        rev = self.env['vas.move'].browse(action['res_id'])
        new = self._make_posted(
            amount=20_000.0,
            source_model='stock.move',
            source_res_id=900001,
            source_ref='S00207-TEST/Stock>Customers',
        )
        return old, rev, new

    def test_schema_distinguishes_reversed_and_reversal(self):
        old, rev, new = self._scenario_reverse_and_replace()
        self.assertEqual(old.state, 'reversed')
        self.assertFalse(old.is_reversal)
        self.assertEqual(old.reversal_move_id, rev)
        self.assertTrue(rev.is_reversal)
        self.assertEqual(rev.state, 'posted')
        self.assertEqual(new.state, 'posted')
        self.assertFalse(new.is_reversal)

    def test_list_default_hides_reversed_pair_shows_effective(self):
        old, rev, new = self._scenario_reverse_and_replace()
        Move = self.env['vas.move']
        # Bút toán đảo không copy source_* — lọc theo journal của ca này.
        base = [
            ('company_id', '=', self.company.id),
            ('journal_id', '=', self.journal.id),
        ]
        full = Move.search(base)
        effective = Move.search(base + VasMove.LIST_HIDE_REVERSED_DOMAIN)
        self.assertEqual(
            set(full.ids), {old.id, rev.id, new.id},
            f'Đủ 3: cũ+đảo+mới, được {full.mapped("name")}',
        )
        self.assertEqual(len(effective), 1, f'Chỉ bản mới, được {effective.mapped("name")}')
        self.assertEqual(effective, new)

        action = self.env.ref('connecta_vas.action_vas_move')
        ctx = action.context or {}
        if isinstance(ctx, str):
            from odoo.tools.safe_eval import safe_eval
            ctx = safe_eval(ctx)
        self.assertEqual(
            ctx.get('search_default_hide_reversed_adjustments'), 1,
            'Action list phải bật filter ẩn đã đảo/điều chỉnh mặc định',
        )

    def test_balance_unchanged_between_display_modes(self):
        """Hai chế độ list chỉ khác domain đếm dòng — số dư account không đổi."""
        old, rev, new = self._scenario_reverse_and_replace()
        bal_156 = self._balance(self.acc_156)
        bal_632 = self._balance(self.acc_632)
        # Cặp cũ+đảo = 0; chỉ còn hiệu lực của bản mới
        self.assertAlmostEqual(bal_156, -20_000.0)
        self.assertAlmostEqual(bal_632, 20_000.0)

        Move = self.env['vas.move']
        base = [('journal_id', '=', self.journal.id)]
        # "Chế độ mặc định" vs "hiện đủ" — cùng một hàm số dư (không gắn list domain)
        _ = Move.search(base + VasMove.LIST_HIDE_REVERSED_DOMAIN)
        _ = Move.search(base)
        self.assertAlmostEqual(self._balance(self.acc_156), bal_156)
        self.assertAlmostEqual(self._balance(self.acc_632), bal_632)

        # Bản ghi vẫn nguyên trong DB
        self.assertTrue(old.exists() and old.state == 'reversed')
        self.assertTrue(rev.exists() and rev.is_reversal)
        self.assertTrue(new.exists() and new.state == 'posted')
